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
