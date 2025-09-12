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


def test_add_worksheet_for_archived_subject(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    # archive and delete the subject
    cur.execute(
        'INSERT INTO subjects_archive (id, name) SELECT id, name FROM subjects WHERE id=?',
        (math_id,),
    )
    cur.execute('DELETE FROM subjects WHERE id=?', (math_id,))
    conn.commit()
    conn.close()

    client = app.app.test_client()
    # page should display archived subject name in missing list
    html = client.get('/edit_timetable/2024-01-01').get_data(as_text=True)
    assert 'Math (0)' in html

    # assign worksheet for archived subject
    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': '1', 'subject': str(math_id), 'assign': '1'},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # verify worksheet added and count reflected in page
    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    row = cur.execute(
        'SELECT 1 FROM worksheets WHERE student_id=1 AND subject_id=? AND date=?',
        (math_id, '2024-01-01'),
    ).fetchone()
    assert row is not None
    conn.close()

    html = client.get('/edit_timetable/2024-01-01').get_data(as_text=True)
    assert 'Math (1)' in html


def test_add_worksheet_when_assign_flag_zero(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    client = app.app.test_client()
    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': '1', 'subject': '1', 'assign': '0'},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    row = cur.execute(
        'SELECT 1 FROM worksheets WHERE student_id=1 AND subject_id=1 AND date=?',
        ('2024-01-01',),
    ).fetchone()
    assert row is not None
    conn.close()


def test_add_worksheet_without_assign_flag(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    client = app.app.test_client()
    resp = client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': '1', 'subject': '1'},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    row = cur.execute(
        'SELECT 1 FROM worksheets WHERE student_id=1 AND subject_id=1 AND date=?',
        ('2024-01-01',),
    ).fetchone()
    assert row is not None
    conn.close()
