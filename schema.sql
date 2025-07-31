DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS weekly_data;
DROP TABLE IF EXISTS name_aliases;
DROP TABLE IF EXISTS settings;

CREATE TABLE classes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  semester TEXT NOT NULL
);

CREATE TABLE students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  manual_adjustment REAL DEFAULT 0,
  FOREIGN KEY (class_id) REFERENCES classes (id)
);

CREATE TABLE weekly_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL,
  week_number INTEGER NOT NULL,
  sync_status TEXT,
  async_status TEXT,
  speaking_time INTEGER DEFAULT 0,
  speaking_instances INTEGER DEFAULT 0,
  FOREIGN KEY (student_id) REFERENCES students (id)
);

CREATE TABLE name_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL,
  alias TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  FOREIGN KEY (class_id) REFERENCES classes (id)
);

CREATE TABLE settings (
  class_id INTEGER PRIMARY KEY,
  base_score REAL DEFAULT 80,
  spread_points REAL DEFAULT 20,
  instance_weight REAL DEFAULT 2,
  time_weight REAL DEFAULT 0.25,
  sync_penalty REAL DEFAULT 4,
  free_sync_absences INTEGER DEFAULT 0,
  async_penalty REAL DEFAULT 3,
  free_async_misses INTEGER DEFAULT 0,
  max_instances_per_week INTEGER DEFAULT 2,
  free_video_off INTEGER DEFAULT 0,
  video_off_penalty REAL DEFAULT 2.5,
  FOREIGN KEY (class_id) REFERENCES classes (id)
);