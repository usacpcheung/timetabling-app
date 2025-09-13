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


def test_restore_archives_teachers(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    # Start with a clean slate
    cur.execute('DELETE FROM teachers')
    cur.execute('DELETE FROM teachers_archive')
    cur.execute('DELETE FROM timetable')
    # Existing teacher referenced by timetable
    cur.execute(
        "INSERT INTO teachers (id, name, subjects, min_lessons, max_lessons) VALUES (1, 'Old', '[]', 0, 0)"
    )
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO timetable (date, slot, student_id, teacher_id, subject_id, group_id, location_id) "
        "VALUES ('2024-01-01', 0, NULL, 1, ?, NULL, NULL)",
        (math_id,)
    )
    conn.commit()

    preset = app.dump_configuration()
    preset['data']['teachers'] = [
        {'id': 2, 'name': 'New', 'subjects': '[]', 'min_lessons': None, 'max_lessons': None}
    ]
    preset['data']['teachers_archive'] = []
    conn.close()

    app.restore_configuration(preset, overwrite=True)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    assert cur.execute('SELECT COUNT(*) FROM timetable').fetchone()[0] == 1
    assert cur.execute('SELECT name FROM teachers_archive WHERE id=1').fetchone()[0] == 'Old'
    assert cur.execute('SELECT COUNT(*) FROM teachers WHERE id=1').fetchone()[0] == 0
    row = cur.execute(
        '''SELECT COALESCE(te.name, ta.name) AS teacher FROM timetable t
           LEFT JOIN teachers te ON t.teacher_id = te.id
           LEFT JOIN teachers_archive ta ON t.teacher_id = ta.id'''
    ).fetchone()
    assert row['teacher'] == 'Old'
    conn.close()


def test_restore_archives_groups(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    cur.execute('DELETE FROM groups')
    cur.execute('DELETE FROM groups_archive')
    cur.execute('DELETE FROM timetable')
    cur.execute("INSERT INTO groups (id, name, subjects) VALUES (1, 'G1', '[]')")
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO timetable (date, slot, student_id, teacher_id, subject_id, group_id, location_id) "
        "VALUES ('2024-01-01', 0, NULL, NULL, ?, 1, NULL)",
        (math_id,)
    )
    conn.commit()

    preset = app.dump_configuration()
    preset['data']['groups'] = []
    preset['data']['group_members'] = []
    preset['data']['groups_archive'] = []
    conn.close()

    app.restore_configuration(preset, overwrite=True)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    assert cur.execute('SELECT COUNT(*) FROM timetable').fetchone()[0] == 1
    assert cur.execute('SELECT name FROM groups_archive WHERE id=1').fetchone()[0] == 'G1'
    assert cur.execute('SELECT COUNT(*) FROM groups WHERE id=1').fetchone()[0] == 0
    row = cur.execute(
        '''SELECT COALESCE(g.name, ga.name) AS gname FROM timetable t
           LEFT JOIN groups g ON t.group_id = g.id
           LEFT JOIN groups_archive ga ON t.group_id = ga.id'''
    ).fetchone()
    assert row['gname'] == 'G1'
    conn.close()


def test_restore_preserves_attendance(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    cur.execute('DELETE FROM students')
    cur.execute('DELETE FROM students_archive')
    cur.execute('DELETE FROM attendance_log')
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO attendance_log (student_id, student_name, subject_id, date) "
        "VALUES (1, 'Stu', ?, '2024-01-01')",
        (math_id,)
    )
    conn.commit()
    preset = app.dump_configuration()
    conn.close()

    app.restore_configuration(preset, overwrite=True)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    assert cur.execute('SELECT name FROM students_archive WHERE id=1').fetchone()[0] == 'Stu'
    rows = cur.execute(
        '''SELECT COALESCE(sa.name, al.student_name) AS name
           FROM attendance_log al
           LEFT JOIN students_archive sa ON al.student_id = sa.id
           LEFT JOIN students s ON al.student_id = s.id
           WHERE s.id IS NULL OR s.active=0'''
    ).fetchall()
    assert rows[0]['name'] == 'Stu'
    conn.close()
