import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_subject_column_removed(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    # Legacy tables storing subject names
    cur.execute('''CREATE TABLE timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        teacher_id INTEGER,
        subject TEXT,
        slot INTEGER
    )''')
    cur.execute('''CREATE TABLE fixed_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        student_id INTEGER,
        subject TEXT,
        slot INTEGER
    )''')
    cur.execute('''CREATE TABLE attendance_log (
        student_id INTEGER,
        student_name TEXT,
        subject TEXT,
        date TEXT
    )''')
    # seed sample data
    cur.execute("INSERT INTO timetable (student_id, teacher_id, subject, slot) VALUES (1, 1, 'Math', 0)")
    cur.execute("INSERT INTO fixed_assignments (teacher_id, student_id, subject, slot) VALUES (1, 1, 'Math', 0)")
    cur.execute("INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (1, 'Stu', 'Math', '2024-01-01')")
    conn.commit()
    conn.close()

    # run migration
    app.init_db()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # ensure subject column removed and subject_id populated
    for tbl in ('timetable', 'fixed_assignments', 'attendance_log'):
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info({tbl})')]
        assert 'subject' not in cols
        assert 'subject_id' in cols
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    assert cur.execute('SELECT subject_id FROM timetable').fetchone()['subject_id'] == math_id
    assert cur.execute('SELECT subject_id FROM fixed_assignments').fetchone()['subject_id'] == math_id
    assert cur.execute('SELECT subject_id FROM attendance_log').fetchone()['subject_id'] == math_id
    conn.close()
