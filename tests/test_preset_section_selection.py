import json
import os
import sys
import sqlite3


def setup_db(tmp_path):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    import app

    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_restore_selected_sections_only_updates_requested_tables(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    preset = app.dump_configuration()

    cur.execute('UPDATE config SET slot_duration = slot_duration + 5 WHERE id = 1')
    cur.execute("UPDATE subjects SET name = 'Biology' WHERE id = 1")
    cur.execute("UPDATE teachers SET name = 'Changed Teacher' WHERE id = 1")
    conn.commit()
    conn.close()

    app.restore_configuration(preset, overwrite=True, sections=['general', 'subjects'])

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    slot_duration = cur.execute('SELECT slot_duration FROM config WHERE id = 1').fetchone()[0]
    subject_name = cur.execute('SELECT name FROM subjects WHERE id = 1').fetchone()[0]
    teacher_name = cur.execute('SELECT name FROM teachers WHERE id = 1').fetchone()[0]
    conn.close()

    assert slot_duration == preset['data']['config'][0]['slot_duration']
    assert subject_name == preset['data']['subjects'][0]['name']
    assert teacher_name == 'Changed Teacher'


def test_student_section_forces_related_dependencies(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    cur.execute('SELECT id FROM locations LIMIT 1')
    if cur.fetchone() is None:
        cur.execute("INSERT INTO locations (name) VALUES ('Room A')")
        conn.commit()

    preset = app.dump_configuration()

    config_id = preset['data']['config'][0]['id']
    subject_id = preset['data']['subjects'][0]['id']
    teacher_id = preset['data']['teachers'][0]['id']
    location_rows = preset['data'].get('locations', [])
    if location_rows:
        location_id = location_rows[0]['id']
    else:
        cur.execute('INSERT INTO locations (name) VALUES (?)', ('Temp Location',))
        location_id = cur.lastrowid
    student_id = preset['data']['students'][0]['id']

    cur.execute('UPDATE config SET slot_duration = slot_duration + 10 WHERE id = ?', (config_id,))
    cur.execute("UPDATE subjects SET name = 'Biology' WHERE id = ?", (subject_id,))
    cur.execute("UPDATE teachers SET name = 'Replacement Teacher' WHERE id = ?", (teacher_id,))
    cur.execute("UPDATE locations SET name = 'Updated Location' WHERE id = ?", (location_id,))
    cur.execute("UPDATE students SET name = 'Changed Student' WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

    app.restore_configuration(preset, overwrite=True, sections=['students'])

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    slot_duration = cur.execute('SELECT slot_duration FROM config WHERE id = ?', (config_id,)).fetchone()[0]
    subject_name = cur.execute('SELECT name FROM subjects WHERE id = ?', (subject_id,)).fetchone()[0]
    teacher_name = cur.execute('SELECT name FROM teachers WHERE id = ?', (teacher_id,)).fetchone()[0]
    location_name = cur.execute('SELECT name FROM locations WHERE id = ?', (location_id,)).fetchone()[0]
    student_name = cur.execute('SELECT name FROM students WHERE id = ?', (student_id,)).fetchone()[0]
    conn.close()

    assert slot_duration == preset['data']['config'][0]['slot_duration']
    assert subject_name == preset['data']['subjects'][0]['name']
    assert teacher_name == preset['data']['teachers'][0]['name']
    assert location_name == preset['data']['locations'][0]['name']
    assert student_name == preset['data']['students'][0]['name']


def test_partial_teacher_restore_cleans_dependent_tables(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    preset = app.dump_configuration()

    student_id = preset['data']['students'][0]['id']
    subject_row = preset['data']['subjects'][0]
    subject_id = subject_row['id']
    cur.execute(
        'INSERT INTO teachers (name, subjects, needs_lessons) VALUES (?, ?, ?)',
        ('Temp Teacher', json.dumps([subject_id]), 1),
    )
    teacher_id = cur.lastrowid
    cur.execute(
        'INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
        (student_id, teacher_id),
    )
    cur.execute(
        'INSERT INTO teacher_unavailable (teacher_id, slot) VALUES (?, ?)',
        (teacher_id, 0),
    )
    cur.execute(
        'INSERT INTO fixed_assignments (teacher_id, student_id, subject_id, slot) VALUES (?, ?, ?, ?)',
        (teacher_id, student_id, subject_id, 1),
    )
    conn.commit()
    conn.close()

    app.restore_configuration(preset, overwrite=True, sections=['teachers'])

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    assert cur.execute('SELECT COUNT(*) FROM teachers WHERE id=?', (teacher_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM student_teacher_block WHERE teacher_id=?', (teacher_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM teacher_unavailable WHERE teacher_id=?', (teacher_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM fixed_assignments WHERE teacher_id=?', (teacher_id,)).fetchone()[0] == 0
    conn.close()


def test_partial_student_restore_cleans_dependent_tables(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    preset = app.dump_configuration()

    subject_row = preset['data']['subjects'][0]
    subject_id = subject_row['id']
    teacher_id = preset['data']['teachers'][0]['id']
    group_rows = preset['data'].get('groups', [])
    if group_rows:
        group_id = group_rows[0]['id']
    else:
        cur.execute('INSERT INTO groups (name, subjects) VALUES (?, ?)', ('Temp Group', json.dumps([subject_id])))
        group_id = cur.lastrowid
    location_rows = preset['data'].get('locations', [])
    if location_rows:
        location_id = location_rows[0]['id']
    else:
        cur.execute('INSERT INTO locations (name) VALUES (?)', ('Temp Location',))
        location_id = cur.lastrowid

    cur.execute(
        'INSERT INTO students (name, subjects) VALUES (?, ?)',
        ('Temp Student', json.dumps([subject_id])),
    )
    student_id = cur.lastrowid
    cur.execute(
        'INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
        (student_id, teacher_id),
    )
    cur.execute(
        'INSERT INTO student_unavailable (student_id, slot) VALUES (?, ?)',
        (student_id, 1),
    )
    cur.execute(
        'INSERT INTO student_locations (student_id, location_id) VALUES (?, ?)',
        (student_id, location_id),
    )
    cur.execute(
        'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
        (group_id, student_id),
    )
    cur.execute(
        'INSERT INTO fixed_assignments (teacher_id, student_id, subject_id, slot) VALUES (?, ?, ?, ?)',
        (teacher_id, student_id, subject_id, 2),
    )
    conn.commit()
    conn.close()

    app.restore_configuration(preset, overwrite=True, sections=['students'])

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    assert cur.execute('SELECT COUNT(*) FROM students WHERE id=?', (student_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM student_teacher_block WHERE student_id=?', (student_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM student_unavailable WHERE student_id=?', (student_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM student_locations WHERE student_id=?', (student_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM group_members WHERE student_id=?', (student_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM fixed_assignments WHERE student_id=?', (student_id,)).fetchone()[0] == 0
    conn.close()


def test_partial_location_restore_cleans_dependent_tables(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()

    preset = app.dump_configuration()

    student_id = preset['data']['students'][0]['id']
    group_rows = preset['data'].get('groups', [])
    if group_rows:
        group_id = group_rows[0]['id']
    else:
        cur.execute('INSERT INTO groups (name, subjects) VALUES (?, ?)', ('Temp Group', json.dumps([])))
        group_id = cur.lastrowid
    teacher_id = preset['data']['teachers'][0]['id']
    subject_row = preset['data']['subjects'][0]
    subject_id = subject_row['id']
    cur.execute('INSERT INTO locations (name) VALUES (?)', ('Temp Room',))
    location_id = cur.lastrowid
    cur.execute(
        'INSERT INTO student_locations (student_id, location_id) VALUES (?, ?)',
        (student_id, location_id),
    )
    cur.execute(
        'INSERT INTO group_locations (group_id, location_id) VALUES (?, ?)',
        (group_id, location_id),
    )
    conn.commit()
    conn.close()

    app.restore_configuration(preset, overwrite=True, sections=['locations'])

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    assert cur.execute('SELECT COUNT(*) FROM locations WHERE id=?', (location_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM student_locations WHERE location_id=?', (location_id,)).fetchone()[0] == 0
    assert cur.execute('SELECT COUNT(*) FROM group_locations WHERE location_id=?', (location_id,)).fetchone()[0] == 0
    has_location_column = any(row[1] == 'location_id' for row in cur.execute('PRAGMA table_info(fixed_assignments)'))
    if has_location_column:
        assert cur.execute('SELECT COUNT(*) FROM fixed_assignments WHERE location_id=?', (location_id,)).fetchone()[0] == 0
    conn.close()
