import sqlite3
import pandas as pd
import csv
import io
import re
import math
import os
from flask import Flask, render_template, request, redirect, url_for, session, g
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
from flask_httpauth import HTTPBasicAuth


app = Flask(__name__)

#user authentication
auth = HTTPBasicAuth()
users = {
    os.environ.get('APP_USERNAME'): os.environ.get('APP_PASSWORD')
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users.get(username) == password:
        return username
app.secret_key = 'your_secret_key_for_flask_session'
DATABASE = 'database.db'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def format_time(seconds):
    if seconds is None: return "00:00"
    minutes = math.floor(seconds / 60)
    remaining_seconds = round(seconds % 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"

app.jinja_env.filters['timeformat'] = format_time

def get_db():
    if 'db' not in g:
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # Connect to PostgreSQL on Render
            g.db = psycopg2.connect(db_url)
            g.db.row_factory = psycopg2.extras.DictCursor
        else:
            # Connect to local SQLite database
            g.db = sqlite3.connect(DATABASE)
            g.db.row_factory = sqlite3.Row
    return g.db

def init_db():
    with app.app_context():
        db = get_db()
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
        with open('schema.sql', 'r') as f:
            db.executescript(f.read())
        db.commit()

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

app.teardown_appcontext(close_db)

def parse_time_to_seconds(time_str):
    parts = time_str.split(':')
    try:
        hours = int(parts[0]); minutes = int(parts[1]); seconds = float(parts[2].replace(',', '.'))
        return (hours * 3600) + (minutes * 60) + seconds
    except (ValueError, IndexError): return 0


    db = get_db()
    students = db.execute('SELECT * FROM students WHERE class_id = ?', (class_id,)).fetchall()
    roster_map = {s['name'].lower(): dict(s) for s in students}
    aliases = db.execute('SELECT alias, canonical_name FROM name_aliases WHERE class_id = ?', (class_id,)).fetchall()
    alias_map = {a['alias'].lower(): a['canonical_name'] for a in aliases}
    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript_lines = f.readlines()
    unresolved_names = set()
    student_stats = {s['id']: {'time': 0, 'instances': 0, 'last_speak_time': 0} for s in students}
    speaking_order = []
    for i, line in enumerate(transcript_lines):
        if '-->' in line:
            try:
                times = line.split('-->'); start_time = parse_time_to_seconds(times[0].strip()); end_time = parse_time_to_seconds(times[1].strip()); duration = end_time - start_time
                if i + 1 < len(transcript_lines):
                    next_line = transcript_lines[i + 1]; speaker_match = re.match(r'^(.*?):', next_line)
                    if speaker_match:
                        raw_speaker_name = speaker_match.group(1).strip(); normalized_name = raw_speaker_name.lower(); canonical_name = None; is_professor = False
                        if normalized_name in roster_map: canonical_name = roster_map[normalized_name]['name']
                        elif normalized_name in alias_map:
                            resolved_name = alias_map[normalized_name]
                            if resolved_name.upper() == 'PROFESSOR': is_professor = True; canonical_name = 'PROFESSOR'
                            elif resolved_name != 'IGNORE': canonical_name = resolved_name
                        else: unresolved_names.add(raw_speaker_name); continue
                        if canonical_name: speaking_order.append(canonical_name)
                        if not is_professor and canonical_name and canonical_name.lower() in roster_map:
                            student_id = roster_map[canonical_name.lower()]['id']; stats = student_stats[student_id]; stats['time'] += duration; time_gap = start_time - stats['last_speak_time']; is_new_instance = False
                            if stats['last_speak_time'] == 0: is_new_instance = True
                            elif time_gap > 45:
                                try:
                                    last_idx = len(speaking_order) - 1 - speaking_order[::-1].index(canonical_name, 1); intervening_speakers = speaking_order[last_idx + 1:-1]
                                    if any(s != 'PROFESSOR' for s in intervening_speakers): is_new_instance = True
                                except ValueError: is_new_instance = True
                            if is_new_instance: stats['instances'] += 1
                            stats['last_speak_time'] = start_time
            except Exception as e: print(f"Error processing line: {line} - {e}")
    if unresolved_names:
        db.close()
        return list(unresolved_names)
    for student_id, stats in student_stats.items():
        exists = db.execute('SELECT id FROM weekly_data WHERE student_id = ? AND week_number = ?', (student_id, week_num)).fetchone()
        if exists: db.execute('UPDATE weekly_data SET speaking_time = ?, speaking_instances = ? WHERE id = ?', (stats['time'], stats['instances'], exists['id']))
        else: db.execute('INSERT INTO weekly_data (student_id, week_number, speaking_time, speaking_instances) VALUES (?, ?, ?, ?)', (student_id, week_num, stats['time'], stats['instances']))
    db.commit(); db.close()
    return []

@app.route('/')
@auth.login_required
def index():
    db = get_db(); classes = db.execute('SELECT * FROM classes ORDER BY name').fetchall(); db.close()
    return render_template('index.html', classes=classes)

@app.route('/add_class', methods=['POST'])
@auth.login_required
def add_class():
    name = request.form['className']; semester = request.form['semester']
    db = get_db(); cursor = db.cursor()
    cursor.execute('INSERT INTO classes (name, semester) VALUES (?, ?)', (name, semester)); class_id = cursor.lastrowid
    cursor.execute('INSERT INTO settings (class_id) VALUES (?)', (class_id,)); db.commit(); db.close()
    return redirect(url_for('index'))

@app.route('/class/<int:class_id>')
@auth.login_required
def class_redirect(class_id):
    return redirect(url_for('class_page', class_id=class_id, week_num=1))

@app.route('/class/<int:class_id>/week/<int:week_num>')
@auth.login_required
def class_page(class_id, week_num):
    db = get_db()
    settings_exist = db.execute('SELECT 1 FROM settings WHERE class_id = ?', (class_id,)).fetchone()
    if not settings_exist: db.execute('INSERT INTO settings (class_id) VALUES (?)', (class_id,)); db.commit()
    class_info = db.execute('SELECT * FROM classes WHERE id = ?', (class_id,)).fetchone()
    
    # Sorts students numerically by their pseudonym (Student-1, Student-2, etc.)
    students = db.execute(
        "SELECT * FROM students WHERE class_id = ? ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", 
        (class_id,)
    ).fetchall()

    weekly_data_rows = db.execute('SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = ?) AND week_number = ?', (class_id, week_num)).fetchall()
    weekly_data = {}
    for row in weekly_data_rows:
        weekly_data[row['student_id']] = dict(row)
    
    return render_template('class_page.html', class_info=class_info, students=students, weekly_data=weekly_data, current_week=week_num)

@app.route('/create_roster/<int:class_id>', methods=['POST'])
@auth.login_required
def create_roster(class_id):
    try:
        num_students = int(request.form.get('num_students'))
        if num_students <= 0 or num_students > 200: # Basic validation
            return "Please enter a valid number of students (1-200).", 400
    except (ValueError, TypeError):
        return "Invalid input for number of students.", 400

    db = get_db()
    # Clear existing students to start fresh
    db.execute('DELETE FROM students WHERE class_id = ?', (class_id,))

    # Generate pseudonyms based on the number provided
    for i in range(1, num_students + 1):
        pseudonym = f'Student-{i}'
        db.execute(
            'INSERT INTO students (class_id, name) VALUES (?, ?)',
            (class_id, pseudonym)
        )

    db.commit()
    db.close()
    return redirect(url_for('class_page', class_id=class_id, week_num=1))
    key_file = request.files.get('roster') # The HTML field is still named 'roster'
    if not key_file: 
        return "No key file uploaded!", 400

    # Read the key file content
    key_content = key_file.stream.read().decode("utf-8")

    db = get_db()
    # Clear existing students for this class to prevent duplicates on re-upload
    db.execute('DELETE FROM students WHERE class_id = ?', (class_id,))

    # Read the two-column CSV (pseudonym,real_name)
    reader = csv.reader(io.StringIO(key_content))
    for row in reader:
        if len(row) == 2:
            pseudonym, real_name = row
            db.execute(
                'INSERT INTO students (class_id, name, pseudonym) VALUES (?, ?, ?)',
                (class_id, real_name.strip(), pseudonym.strip())
            )

    db.commit()
    db.close()
    return redirect(url_for('class_page', class_id=class_id, week_num=1))
    roster_file = request.files.get('roster')
    if not roster_file: 
        return "No file uploaded!", 400

    # Check the state of the checkbox from the form
    has_header = request.form.get('rosterHasHeader') == 'true'

    roster_content = roster_file.stream.read().decode("utf-8")

    # Use pandas to read the CSV, telling it whether a header exists
    if has_header:
        roster_df = pd.read_csv(io.StringIO(roster_content))
    else:
        roster_df = pd.read_csv(io.StringIO(roster_content), header=None)

    # Get names from the first column
    student_names = roster_df.iloc[:, 0].tolist()

    db = get_db()
    for name in student_names:
        db.execute('INSERT INTO students (class_id, name) VALUES (?, ?)', (class_id, name))
    db.commit()
    db.close()
    return redirect(url_for('class_page', class_id=class_id, week_num=1))
    roster_file = request.files.get('roster')
    if not roster_file: return "No file uploaded!", 400
    roster_content = roster_file.stream.read().decode("utf-8"); roster_df = pd.read_csv(io.StringIO(roster_content))
    student_names = roster_df.iloc[:, 0].tolist()
    db = get_db()
    for name in student_names:
        db.execute('INSERT INTO students (class_id, name) VALUES (?, ?)', (class_id, name))
    db.commit(); db.close()
    return redirect(url_for('class_page', class_id=class_id, week_num=1))

@app.route('/save_week/<int:class_id>/<int:week_num>', methods=['POST'])
@auth.login_required
def save_week(class_id, week_num):
    db = get_db()
    students = db.execute('SELECT * FROM students WHERE class_id = ?', (class_id,)).fetchall()
    for student in students:
        student_id = student['id']; sync_status = request.form.get(f'sync_status_{student_id}'); async_status = request.form.get(f'async_status_{student_id}')
        exists = db.execute('SELECT id FROM weekly_data WHERE student_id = ? AND week_number = ?', (student_id, week_num)).fetchone()
        if exists: db.execute('UPDATE weekly_data SET sync_status = ?, async_status = ? WHERE id = ?', (sync_status, async_status, exists['id']))
        else: db.execute('INSERT INTO weekly_data (student_id, week_number, sync_status, async_status) VALUES (?, ?, ?, ?)',(student_id, week_num, sync_status, async_status))
    db.commit(); db.close()
    return redirect(url_for('class_page', class_id=class_id, week_num=week_num))

@app.route('/analyze_transcript/<int:class_id>/<int:week_num>', methods=['POST'])
@auth.login_required
def analyze_transcript(class_id, week_num):
    transcript_file = request.files.get('transcript')
    if not transcript_file:
        return "No anonymized transcript file uploaded!", 400

    db = get_db()
    students = db.execute("SELECT id, name FROM students WHERE class_id = ?", (class_id,)).fetchall()
    pseudonym_map = {s['name']: s['id'] for s in students}
    
    # Restore last_speak_time to the stats dictionary
    student_stats = {s['id']: {'time': 0, 'instances': 0, 'last_speak_time': 0} for s in students}
    speaking_order = [] # To track intervening speakers

    transcript_lines = transcript_file.stream.read().decode("utf-8").splitlines()

    for i, line in enumerate(transcript_lines):
        if '-->' in line and i + 1 < len(transcript_lines):
            try:
                times = line.split('-->')
                start_time = parse_time_to_seconds(times[0].strip())
                end_time = parse_time_to_seconds(times[1].strip())
                duration = end_time - start_time
                
                speaker_line = transcript_lines[i + 1]
                if ':' in speaker_line:
                    pseudonym = speaker_line.split(':')[0].strip()
                    
                    speaking_order.append(pseudonym)
                    
                    if pseudonym in pseudonym_map:
                        student_id = pseudonym_map[pseudonym]
                        stats = student_stats[student_id]
                        
                        stats['time'] += duration
                        
                        is_new_instance = False
                        time_gap = start_time - stats['last_speak_time']
                        
                        if stats['last_speak_time'] == 0:
                            is_new_instance = True
                        elif time_gap > 45:
                             is_new_instance = True
                        else:
                            try:
                                last_idx = len(speaking_order) - 1 - speaking_order[::-1].index(pseudonym, 1)
                                intervening_speakers = speaking_order[last_idx + 1:-1]
                                if any(s in pseudonym_map for s in intervening_speakers):
                                    is_new_instance = True
                            except ValueError:
                                is_new_instance = True

                        if is_new_instance:
                            stats['instances'] += 1
                        
                        stats['last_speak_time'] = start_time
            except Exception as e:
                print(f"Error processing line: {line} - {e}")

    for student_id, stats in student_stats.items():
        if stats['time'] > 0 or stats['instances'] > 0:
            exists = db.execute('SELECT id FROM weekly_data WHERE student_id = ? AND week_number = ?', (student_id, week_num)).fetchone()
            if exists:
                db.execute('UPDATE weekly_data SET speaking_time = ?, speaking_instances = ? WHERE id = ?', (stats['time'], stats['instances'], exists['id']))
            else:
                db.execute('INSERT INTO weekly_data (student_id, week_number, speaking_time, speaking_instances) VALUES (?, ?, ?, ?)', (student_id, week_num, stats['time'], stats['instances']))
    
    db.commit() 
    return redirect(url_for('class_page', class_id=class_id, week_num=week_num))

@app.route('/grades/<int:class_id>', methods=['GET', 'POST'])
@auth.login_required
def grades_page(class_id):
    db = get_db()
    settings = db.execute('SELECT * FROM settings WHERE class_id = ?', (class_id,)).fetchone()
    if not settings:
        db.execute('INSERT INTO settings (class_id) VALUES (?)', (class_id,)); db.commit()
        settings = db.execute('SELECT * FROM settings WHERE class_id = ?', (class_id,)).fetchone()

    if request.method == 'POST':
        settings_keys = ['base_score', 'spread_points', 'instance_weight', 'time_weight', 'sync_penalty', 'free_sync_absences', 'async_penalty', 'free_async_misses', 'max_instances_per_week', 'free_video_off', 'video_off_penalty']
        updated_settings = {key: request.form.get(key, type=float) for key in settings_keys}
        set_clause = ', '.join([f'{key} = ?' for key in updated_settings]); values = list(updated_settings.values()); values.append(class_id)
        db.execute(f'UPDATE settings SET {set_clause} WHERE class_id = ?', tuple(values))
        student_ids = request.form.getlist('student_id')
        for sid in student_ids:
            adjustment = request.form.get(f'manual_adjustment_{sid}', 0, type=float)
            db.execute('UPDATE students SET manual_adjustment = ? WHERE id = ?', (adjustment, sid))
        db.commit()
        settings = db.execute('SELECT * FROM settings WHERE class_id = ?', (class_id,)).fetchone()

    # Sorts students numerically by their pseudonym
    students = db.execute(
        "SELECT * FROM students WHERE class_id = ? ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", 
        (class_id,)
    ).fetchall()
    
    all_weekly_data = db.execute('SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = ?)', (class_id,)).fetchall()
    final_results = []
    if students:
        for student in students:
            student_id = student['id']; student_weekly_data = [row for row in all_weekly_data if row['student_id'] == student_id]
            total_absences = sum(1 for d in student_weekly_data if d['sync_status'] == 'Absent')
            total_video_off = sum(1 for d in student_weekly_data if d['sync_status'] == 'Video Off')
            total_async_misses = sum(1 for d in student_weekly_data if d['async_status'] == 'Missed')
            total_instances = sum(d['speaking_instances'] for d in student_weekly_data)
            total_time = sum(d['speaking_time'] for d in student_weekly_data)
            capped_instances = sum(min(d['speaking_instances'], settings['max_instances_per_week']) for d in student_weekly_data)
            raw_points = (capped_instances * settings['instance_weight']) + ((total_time / 60) * settings['time_weight'])
            final_results.append({'student_id': student_id, 'name': student['name'], 'absences': total_absences,'video_off': total_video_off, 'async_misses': total_async_misses, 'total_instances': total_instances,'capped_instances': capped_instances, 'total_time': total_time, 'raw_points': raw_points,'manual_adjustment': student['manual_adjustment']})
        
        for res in final_results:
            grade = settings['base_score']
            participation_points = res['raw_points']
            capped_bonus = min(participation_points, settings['spread_points'])
            grade += capped_bonus
            sync_penalty_count = max(0, res['absences'] - settings['free_sync_absences']); grade -= sync_penalty_count * settings['sync_penalty']
            async_penalty_count = max(0, res['async_misses'] - settings['free_async_misses']); grade -= async_penalty_count * settings['async_penalty']
            video_off_penalty_count = max(0, res['video_off'] - settings['free_video_off']); grade -= video_off_penalty_count * settings['video_off_penalty']
            grade += res['manual_adjustment']; res['final_grade'] = round(max(0, min(100, grade)), 2)
    
    averages = {}
    if final_results:
        num_students = len(final_results)
        averages['absences'] = round(sum(res['absences'] for res in final_results) / num_students, 1)
        averages['video_off'] = round(sum(res['video_off'] for res in final_results) / num_students, 1)
        averages['async_misses'] = round(sum(res['async_misses'] for res in final_results) / num_students, 1)
        avg_time_seconds = sum(res['total_time'] for res in final_results) / num_students
        averages['total_time'] = format_time(avg_time_seconds)
        averages['capped_instances'] = round(sum(res['capped_instances'] for res in final_results) / num_students, 1)
        averages['final_grade'] = round(sum(res['final_grade'] for res in final_results) / num_students, 2)
        
    class_info = db.execute('SELECT * FROM classes WHERE id = ?', (class_id,)).fetchone()
    return render_template('grades_page.html', class_info=class_info, settings=settings, results=final_results, averages=averages)

@app.route('/summary/<int:class_id>')
@auth.login_required
def summary_page(class_id):
    db = get_db()
    class_info = db.execute('SELECT * FROM classes WHERE id = ?', (class_id,)).fetchone()
    
    # Sorts students numerically by their pseudonym
    students = db.execute(
        "SELECT * FROM students WHERE class_id = ? ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", 
        (class_id,)
    ).fetchall()

    all_weekly_data = db.execute(
        'SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = ?)', 
        (class_id,)
    ).fetchall()
    
    summary_data = {}
    for student in students:
        summary_data[student['id']] = {}

    for row in all_weekly_data:
        summary_data[row['student_id']][row['week_number']] = dict(row)
    
    week_numbers = range(1, 14) 

    return render_template('summary_page.html', 
                           class_info=class_info, 
                           students=students, 
                           summary_data=summary_data, 
                           week_numbers=week_numbers)

@app.route('/instructions')
@auth.login_required
def instructions():
    return render_template('instructions.html')

if __name__ == '__main__':
    app.run(debug=True, port=5001)

    