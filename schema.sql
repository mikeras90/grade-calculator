-- Drop tables if they exist to ensure a clean slate
DROP TABLE IF EXISTS weekly_data;
DROP TABLE IF EXISTS settings;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS classes;

-- Create tables with PostgreSQL-compatible syntax
CREATE TABLE classes (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  semester TEXT NOT NULL
);

CREATE TABLE students (
  id SERIAL PRIMARY KEY,
  class_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  manual_adjustment REAL DEFAULT 0,
  FOREIGN KEY (class_id) REFERENCES classes (id)
);

CREATE TABLE weekly_data (
  id SERIAL PRIMARY KEY,
  student_id INTEGER NOT NULL,
  week_number INTEGER NOT NULL,
  speaking_time REAL DEFAULT 0,
  speaking_instances INTEGER DEFAULT 0,
  sync_status TEXT DEFAULT 'Present',
  async_status TEXT DEFAULT 'Submitted',
  FOREIGN KEY (student_id) REFERENCES students (id)
);

CREATE TABLE settings (
  id SERIAL PRIMARY KEY,
  class_id INTEGER NOT NULL UNIQUE,
  base_score REAL DEFAULT 80,
  spread_points REAL DEFAULT 20,
  instance_weight REAL DEFAULT 1,
  time_weight REAL DEFAULT 1,
  sync_penalty REAL DEFAULT 1,
  free_sync_absences INTEGER DEFAULT 2,
  async_penalty REAL DEFAULT 1,
  free_async_misses INTEGER DEFAULT 2,
  max_instances_per_week INTEGER DEFAULT 5,
  free_video_off INTEGER DEFAULT 2,
  video_off_penalty REAL DEFAULT 0.5,
  FOREIGN KEY (class_id) REFERENCES classes (id)
);