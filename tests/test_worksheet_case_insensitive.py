import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_worksheet_subject_case_insensitive(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    client = app.app.test_client()
    client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': str(sid), 'subject': 'mAtH', 'assign': '1'},
    )

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    math = next(item for item in missing[sid] if item['subject'] == 'Math')
    assert math['count'] == 1
    assert math['today']
