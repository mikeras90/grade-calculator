import sqlite3
import csv
import io
import math
import os
from flask import Flask, render_template, request, redirect, url_for, g
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
from flask_httpauth import HTTPBasicAuth

# --- App Setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_default_secret_key') # Use environment variable for secret key
DATABASE = 'database.db'

# --- User Authentication ---
auth = HTTPBasicAuth()
users = {
    os.environ.get('APP_USERNAME'): os.environ.get('APP_PASSWORD')
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users.get(username) == password:
        return username

# --- Database Management ---
def get_db():
    # Gets a database connection. Creates one if it doesn't exist for the current request.
    if 'db' not in g:
        db_url = os.environ.get('DATABASE_URL')
        if db_url:
            # Connect to PostgreSQL on Render
            g.db = psycopg2.connect(db_url)
        else:
            # Connect to local SQLite database
            g.db = sqlite3.connect(DATABASE)
    return g.db

def close_db(e=None):
    # Closes the database connection at the end of the request.
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    #This 'with' block creates the necessary application context
    with app.app_context():
        db = get_db()
        with db.cursor() as cur:
            with open('schema.sql', 'r') as f:
                if hasattr(db, 'executescript'):
                     db.executescript(f.read())
                else:
                     cur.execute(f.read())
        db.commit()

app.teardown_appcontext(close_db)

# --- Helper Functions ---
def parse_time_to_seconds(time_str):
    parts = time_str.split(':')
    try:
        hours = int(parts[0]); minutes = int(parts[1]); seconds = float(parts[2].replace(',', '.'))
        return (hours * 3600) + (minutes * 60) + seconds
    except (ValueError, IndexError): return 0

def format_time(seconds):
    if seconds is None: return "00:00"
    minutes = math.floor(seconds / 60)
    remaining_seconds = round(seconds % 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"

app.jinja_env.filters['timeformat'] = format_time

# --- Routes ---
@app.route('/')
@auth.login_required
def index():
    db = get_db()
    # NOTE: Using 'with' statement for cursor management.
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row) as cur:
        cur.execute('SELECT * FROM classes ORDER BY name')
        classes = cur.fetchall()
    return render_template('index.html', classes=classes)

@app.route('/add_class', methods=['POST'])
@auth.login_required
def add_class():
    name = request.form['className']; semester = request.form['semester']
    db = get_db()
    with db.cursor() as cur:
        cur.execute('INSERT INTO classes (name, semester) VALUES (%s, %s) RETURNING id', (name, semester))
        class_id = cur.fetchone()[0]
        cur.execute('INSERT INTO settings (class_id) VALUES (%s)', (class_id,))
    db.commit()
    return redirect(url_for('index'))

@app.route('/class/<int:class_id>')
@auth.login_required
def class_redirect(class_id):
    return redirect(url_for('class_page', class_id=class_id, week_num=1))

@app.route('/class/<int:class_id>/week/<int:week_num>')
@auth.login_required
def class_page(class_id, week_num):
    db = get_db()
    cursor_factory = psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row
    
    with db.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute('SELECT * FROM classes WHERE id = %s', (class_id,))
        class_info = cur.fetchone()

        cur.execute('SELECT 1 FROM settings WHERE class_id = %s', (class_id,))
        if not cur.fetchone():
            cur.execute('INSERT INTO settings (class_id) VALUES (%s)', (class_id,))
            db.commit()

        cur.execute("SELECT * FROM students WHERE class_id = %s ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", (class_id,))
        students = cur.fetchall()

        cur.execute('SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = %s) AND week_number = %s', (class_id, week_num))
        weekly_data_rows = cur.fetchall()
        
    weekly_data = {row['student_id']: dict(row) for row in weekly_data_rows}
    
    return render_template('class_page.html', class_info=class_info, students=students, weekly_data=weekly_data, current_week=week_num)

@app.route('/create_roster/<int:class_id>', methods=['POST'])
@auth.login_required
def create_roster(class_id):
    try:
        num_students = int(request.form.get('num_students'))
        if num_students <= 0 or num_students > 200:
            return "Please enter a valid number of students (1-200).", 400
    except (ValueError, TypeError):
        return "Invalid input for number of students.", 400

    db = get_db()
    with db.cursor() as cur:
        cur.execute('DELETE FROM students WHERE class_id = %s', (class_id,))
        for i in range(1, num_students + 1):
            pseudonym = f'Student-{i}'
            cur.execute('INSERT INTO students (class_id, name) VALUES (%s, %s)', (class_id, pseudonym))
    db.commit()
    return redirect(url_for('class_page', class_id=class_id, week_num=1))

@app.route('/save_week/<int:class_id>/<int:week_num>', methods=['POST'])
@auth.login_required
def save_week(class_id, week_num):
    db = get_db()
    cursor_factory = psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row
    with db.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute('SELECT * FROM students WHERE class_id = %s', (class_id,))
        students = cur.fetchall()
        for student in students:
            student_id = student['id']
            sync_status = request.form.get(f'sync_status_{student_id}')
            async_status = request.form.get(f'async_status_{student_id}')
            cur.execute('SELECT id FROM weekly_data WHERE student_id = %s AND week_number = %s', (student_id, week_num))
            exists = cur.fetchone()
            if exists:
                cur.execute('UPDATE weekly_data SET sync_status = %s, async_status = %s WHERE id = %s', (sync_status, async_status, exists['id']))
            else:
                cur.execute('INSERT INTO weekly_data (student_id, week_number, sync_status, async_status) VALUES (%s, %s, %s, %s)',(student_id, week_num, sync_status, async_status))
    db.commit()
    return redirect(url_for('class_page', class_id=class_id, week_num=week_num))

@app.route('/analyze_transcript/<int:class_id>/<int:week_num>', methods=['POST'])
@auth.login_required
def analyze_transcript(class_id, week_num):
    transcript_file = request.files.get('transcript')
    if not transcript_file:
        return "No anonymized transcript file uploaded!", 400

    db = get_db()
    with db.cursor(cursor_factory=psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row) as cur:
        cur.execute("SELECT id, name FROM students WHERE class_id = %s", (class_id,))
        students = cur.fetchall()
    
    pseudonym_map = {s['name']: s['id'] for s in students}
    student_stats = {s['id']: {'time': 0, 'instances': 0, 'last_speak_time': 0} for s in students}
    speaking_order = []

    transcript_lines = transcript_file.stream.read().decode("utf-8").splitlines()

    for i, line in enumerate(transcript_lines):
        if '-->' in line and i + 1 < len(transcript_lines):
            try:
                times = line.split('-->')
                duration = parse_time_to_seconds(times[1].strip()) - parse_time_to_seconds(times[0].strip())
                start_time = parse_time_to_seconds(times[0].strip())
                
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
                        
                        if stats['last_speak_time'] == 0: is_new_instance = True
                        elif time_gap > 45: is_new_instance = True
                        else:
                            try:
                                last_idx = len(speaking_order) - 1 - speaking_order[::-1].index(pseudonym, 1)
                                intervening_speakers = speaking_order[last_idx + 1:-1]
                                if any(s in pseudonym_map for s in intervening_speakers):
                                    is_new_instance = True
                            except ValueError: is_new_instance = True

                        if is_new_instance: stats['instances'] += 1
                        stats['last_speak_time'] = start_time
            except Exception as e:
                print(f"Error processing line: {line} - {e}")

    with db.cursor() as cur:
        for student_id, stats in student_stats.items():
            if stats['time'] > 0 or stats['instances'] > 0:
                cur.execute('SELECT id FROM weekly_data WHERE student_id = %s AND week_number = %s', (student_id, week_num))
                exists = cur.fetchone()
                if exists:
                    cur.execute('UPDATE weekly_data SET speaking_time = %s, speaking_instances = %s WHERE id = %s', (stats['time'], stats['instances'], exists['id']))
                else:
                    cur.execute('INSERT INTO weekly_data (student_id, week_number, speaking_time, speaking_instances) VALUES (%s, %s, %s, %s)', (student_id, week_num, stats['time'], stats['instances']))
    db.commit() 
    return redirect(url_for('class_page', class_id=class_id, week_num=week_num))

@app.route('/grades/<int:class_id>', methods=['GET', 'POST'])
@auth.login_required
def grades_page(class_id):
    db = get_db()
    cursor_factory = psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row
    with db.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute('SELECT * FROM settings WHERE class_id = %s', (class_id,))
        settings = cur.fetchone()

    if request.method == 'POST':
        settings_keys = ['base_score', 'spread_points', 'instance_weight', 'time_weight', 'sync_penalty', 'free_sync_absences', 'async_penalty', 'free_async_misses', 'max_instances_per_week', 'free_video_off', 'video_off_penalty']
        updated_settings = {key: request.form.get(key, type=float) for key in settings_keys}
        set_clause = ', '.join([f'{key} = %s' for key in updated_settings]); values = list(updated_settings.values()); values.append(class_id)
        with db.cursor() as cur:
            cur.execute(f'UPDATE settings SET {set_clause} WHERE class_id = %s', tuple(values))
            student_ids = request.form.getlist('student_id')
            for sid in student_ids:
                adjustment = request.form.get(f'manual_adjustment_{sid}', 0, type=float)
                cur.execute('UPDATE students SET manual_adjustment = %s WHERE id = %s', (adjustment, sid))
        db.commit()
        # Re-fetch settings after update
        with db.cursor(cursor_factory=cursor_factory) as cur:
            cur.execute('SELECT * FROM settings WHERE class_id = %s', (class_id,))
            settings = cur.fetchone()

    with db.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute("SELECT * FROM students WHERE class_id = %s ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", (class_id,))
        students = cur.fetchall()
        cur.execute('SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = %s)', (class_id,))
        all_weekly_data = cur.fetchall()
        cur.execute('SELECT * FROM classes WHERE id = %s', (class_id,))
        class_info = cur.fetchone()

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
            grade = settings['base_score']; participation_points = res['raw_points']
            capped_bonus = min(participation_points, settings['spread_points']); grade += capped_bonus
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
        
    return render_template('grades_page.html', class_info=class_info, settings=settings, results=final_results, averages=averages)

@app.route('/summary/<int:class_id>')
@auth.login_required
def summary_page(class_id):
    db = get_db()
    cursor_factory = psycopg2.extras.DictCursor if hasattr(db, 'cursor') else sqlite3.Row
    with db.cursor(cursor_factory=cursor_factory) as cur:
        cur.execute('SELECT * FROM classes WHERE id = %s', (class_id,))
        class_info = cur.fetchone()
        cur.execute("SELECT * FROM students WHERE class_id = %s ORDER BY CAST(SUBSTR(name, 9) AS INTEGER)", (class_id,))
        students = cur.fetchall()
        cur.execute('SELECT * FROM weekly_data WHERE student_id IN (SELECT id FROM students WHERE class_id = %s)', (class_id,))
        all_weekly_data = cur.fetchall()
    
    summary_data = {student['id']: {} for student in students}
    for row in all_weekly_data:
        summary_data[row['student_id']][row['week_number']] = dict(row)
    
    week_numbers = range(1, 14) 
    return render_template('summary_page.html', class_info=class_info, students=students, summary_data=summary_data, week_numbers=week_numbers)

@app.route('/instructions')
@auth.login_required
def instructions():
    return render_template('instructions.html')

# NOTE: This block is for running the app locally for testing.
# Gunicorn on Render will start the app directly.
if __name__ == '__main__':
    app.run(debug=True, port=5001)