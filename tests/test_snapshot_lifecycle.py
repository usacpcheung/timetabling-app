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


def test_generate_creates_snapshot(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    client = app.app.test_client()
    resp = client.post('/generate', data={'date': '2024-01-01', 'confirm': '1'}, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    row = conn.execute("SELECT 1 FROM timetable_snapshot WHERE date='2024-01-01'").fetchone()
    conn.close()
    assert row is not None


def test_delete_timetables_removes_snapshot(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute("INSERT INTO timetable (student_id, teacher_id, subject_id, slot, date) VALUES (1, 1, 1, 0, '2024-01-01')")
    app.get_missing_and_counts(c, '2024-01-01', refresh=True)
    conn.commit()
    conn.close()

    client = app.app.test_client()
    resp = client.post('/delete_timetables', data={'dates': ['2024-01-01']}, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    row = conn.execute("SELECT 1 FROM timetable_snapshot WHERE date='2024-01-01'").fetchone()
    conn.close()
    assert row is None
