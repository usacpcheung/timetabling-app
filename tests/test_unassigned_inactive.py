import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_inactive_student_listed_in_missing(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    cur.execute("UPDATE students SET active=0 WHERE id=?", (sid,))
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid in missing
    subjects = {item['subject'] for item in missing[sid]}
    assert subjects == {'Math', 'English'}


def test_worksheet_counts_separate_by_id(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid_old = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    cur.executemany(
        "INSERT INTO worksheets (student_id, subject, date) VALUES (?, ?, ?)",
        [
            (sid_old, 'Math', '2024-01-01'),
            (sid_old, 'Math', '2024-01-02'),
        ],
    )
    cur.execute("INSERT INTO students_archive (id, name) VALUES (?, ?)", (sid_old, 'Student 1'))
    cur.execute("DELETE FROM students WHERE id=?", (sid_old,))
    cur.execute(
        "INSERT INTO students (name, subjects, active) VALUES (?, ?, 0)",
        ('Student 1', json.dumps(['Math'])),
    )
    sid_new = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _ = app.get_timetable_data('2024-01-03')
    assert sid_new in missing
    math = next(item for item in missing[sid_new] if item['subject'] == 'Math')
    assert math['count'] == 0
