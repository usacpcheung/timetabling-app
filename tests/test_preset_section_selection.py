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
    location_id = preset['data']['locations'][0]['id']
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
