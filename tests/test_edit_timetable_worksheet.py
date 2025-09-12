import os
import sys
import sqlite3
import json

# ensure app can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_worksheet_toggle(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    conn.close()

    client = app.app.test_client()

    resp = client.post('/edit_timetable/2024-01-01', data={
        'action': 'worksheet',
        'student_id': '1',
        'subject_id': str(math_id),
        'assign': '1',
    }, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute(
        "SELECT 1 FROM worksheets WHERE student_id=1 AND subject_id=? AND date='2024-01-01'",
        (math_id,),
    ).fetchone()
    assert row is not None
    conn.close()

    resp = client.post('/edit_timetable/2024-01-01', data={
        'action': 'worksheet',
        'student_id': '1',
        'subject_id': str(math_id),
        'assign': '0',
    }, follow_redirects=True)
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute(
        "SELECT 1 FROM worksheets WHERE student_id=1 AND subject_id=? AND date='2024-01-01'",
        (math_id,),
    ).fetchone()
    assert row is None
    conn.close()


def test_worksheet_blank_subject_id(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    client = app.app.test_client()

    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': '1', 'subject_id': '', 'assign': '1'},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute('SELECT 1 FROM worksheets').fetchone()
    assert row is None
    conn.close()


def test_refreshes_old_snapshot_without_subject_id(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    old_missing = {1: [{"subject": "Math", "count": 0, "assigned": False}]}
    lesson_counts = {1: 0}
    c.execute(
        'INSERT INTO timetable_snapshot (date, missing, lesson_counts) VALUES (?, ?, ?)',
        ('2024-01-01', json.dumps(old_missing), json.dumps(lesson_counts)),
    )
    conn.commit()
    conn.close()

    client = app.app.test_client()
    resp = client.get('/edit_timetable/2024-01-01')
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    row = c.execute(
        'SELECT missing FROM timetable_snapshot WHERE date=?', ('2024-01-01',)
    ).fetchone()
    data = json.loads(row['missing'])
    assert 'subject_id' in data['1'][0]
    assert data['1'][0]['subject_id'] == math_id
    conn.close()
