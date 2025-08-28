import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app


def setup_db(tmp_path):
    db_path = tmp_path / "test.db"
    app.DB_PATH = str(db_path)
    app.init_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_add_and_delete_lesson(tmp_path):
    conn = setup_db(tmp_path)
    client = app.app.test_client()

    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={
            'action': 'add',
            'slot': '0',
            'student_group': 's1',
            'subject': 'Math',
            'teacher': '1'
        },
        follow_redirects=True
    )
    assert resp.status_code == 200
    c = conn.cursor()
    c.execute("SELECT id FROM timetable WHERE date='2024-01-01'")
    rows = c.fetchall()
    assert len(rows) == 1
    entry_id = rows[0]['id']

    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'delete', 'entry_id': str(entry_id)},
        follow_redirects=True
    )
    assert resp.status_code == 200
    c.execute("SELECT id FROM timetable WHERE date='2024-01-01'")
    assert c.fetchone() is None
    conn.close()
