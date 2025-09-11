import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_worksheet_migration_preserves_distinct_subjects(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    # legacy worksheets table without subject_id
    cur.execute('''CREATE TABLE worksheets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        subject TEXT,
        date TEXT
    )''')
    # seed multiple subjects for same student/date
    for subj in ('Math', 'English', 'Science'):
        cur.execute(
            "INSERT INTO worksheets (student_id, subject, date) VALUES (28, ?, '2025-09-12')",
            (subj,),
        )
    conn.commit()
    conn.close()

    # run migration
    app.init_db()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        '''SELECT w.student_id, w.date, s.name FROM worksheets w
           JOIN subjects s ON w.subject_id = s.id
           WHERE w.student_id = 28 AND w.date = '2025-09-12' '''
    ).fetchall()
    assert len(rows) == 3
    assert {r['name'] for r in rows} == {'Math', 'English', 'Science'}
    conn.close()
