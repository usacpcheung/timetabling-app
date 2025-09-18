import os
import sys
import json
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


def test_regenerate_updates_snapshot(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    client = app.app.test_client()
    resp = client.post('/generate', data={'date': '2024-01-01', 'confirm': '1'}, follow_redirects=True)
    assert resp.status_code == 200

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


def test_snapshot_records_group_members(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute("INSERT INTO groups (name, subjects) VALUES (?, ?)", ('Group A', json.dumps([math_id])))
    group_id = cur.lastrowid
    cur.execute("INSERT INTO group_members (group_id, student_id) VALUES (?, ?)", (group_id, 1))
    cur.execute("INSERT INTO group_members (group_id, student_id) VALUES (?, ?)", (group_id, 2))
    cur.execute(
        "INSERT INTO timetable (group_id, teacher_id, subject_id, slot, date) VALUES (?, ?, ?, 0, '2024-01-01')",
        (group_id, 1, math_id),
    )
    app.get_missing_and_counts(cur, '2024-01-01', refresh=True)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT group_data FROM timetable_snapshot WHERE date='2024-01-01'").fetchone()
    conn.close()
    assert row is not None
    stored = json.loads(row['group_data'])
    assert str(group_id) in stored
    info = stored[str(group_id)]
    assert info['name'] == 'Group A'
    member_ids = {m['id'] for m in info['members']}
    assert member_ids == {1, 2}
    member_names = {m['name'] for m in info['members']}
    assert 'Student 1' in member_names
    assert 'Student 2' in member_names


def test_teacher_snapshot_preserves_deleted_teacher(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    teacher_a = cur.execute("SELECT id FROM teachers WHERE name='Teacher A'").fetchone()[0]
    teacher_b = cur.execute("SELECT id FROM teachers WHERE name='Teacher B'").fetchone()[0]

    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, date) VALUES (?, ?, ?, ?, ?)",
        (1, teacher_a, math_id, 0, '2024-01-01'),
    )
    app.get_missing_and_counts(cur, '2024-01-01', refresh=True)
    conn.commit()

    cur.execute(
        'INSERT OR IGNORE INTO teachers_archive (id, name) VALUES (?, ?)',
        (teacher_a, 'Teacher A'),
    )
    cur.execute('DELETE FROM teachers WHERE id=?', (teacher_a,))

    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, date) VALUES (?, ?, ?, ?, ?)",
        (1, teacher_b, math_id, 0, '2024-01-02'),
    )
    app.get_missing_and_counts(cur, '2024-01-02', refresh=True)
    conn.commit()
    conn.close()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT teacher_data FROM timetable_snapshot WHERE date='2024-01-01'"
    ).fetchone()
    conn.close()
    assert row is not None
    teacher_snapshot = json.loads(row['teacher_data'])
    assert any(t['name'] == 'Teacher A' for t in teacher_snapshot)

    columns_old = app.get_timetable_data('2024-01-01')[2]
    assert any(col['name'] == 'Teacher A' for col in columns_old)

    columns_new = app.get_timetable_data('2024-01-02')[2]
    assert all(col['name'] != 'Teacher A' for col in columns_new)
