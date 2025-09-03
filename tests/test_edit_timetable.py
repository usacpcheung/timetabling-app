import os
import sys
import sqlite3

# ensure app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_add_and_edit_lesson(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    c.execute("INSERT INTO locations (name) VALUES ('Room B')")
    conn.commit()
    conn.close()

    client = app.app.test_client()

    # add lesson with location
    resp = client.post('/edit_timetable/2024-01-01', data={
        'action': 'add',
        'slot': '0',
        'teacher': '1',
        'student_group': 's1',
        'subject': 'Math',
        'location': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, student_id, subject, location_id FROM timetable WHERE date='2024-01-01'")
    row = c.fetchone()
    assert row['student_id'] == 1
    assert row['subject'] == 'Math'
    assert row['location_id'] == 1
    entry_id = row['id']
    c.execute("SELECT student_id, subject FROM attendance_log WHERE date='2024-01-01'")
    log = c.fetchone()
    assert log['student_id'] == 1 and log['subject'] == 'Math'
    conn.close()

    # edit lesson to different student, subject and location
    resp = client.post('/edit_timetable/2024-01-01', data={
        'action': 'edit',
        'entry_id': str(entry_id),
        'student_group': 's2',
        'subject': 'English',
        'location': '2',
    }, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT student_id, subject, location_id FROM timetable WHERE id=?", (entry_id,))
    row = c.fetchone()
    assert row['student_id'] == 2
    assert row['subject'] == 'English'
    assert row['location_id'] == 2
    c.execute("SELECT student_id, subject FROM attendance_log WHERE date='2024-01-01'")
    logs = c.fetchall()
    assert len(logs) == 1
    assert logs[0]['student_id'] == 2 and logs[0]['subject'] == 'English'
    conn.close()
