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


def test_restore_only_updates_config(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()

    # Insert timetable entry to ensure it survives preset restore
    cur.execute(
        "INSERT INTO timetable (date, slot, student_id, teacher_id, subject, group_id, location_id) "
        "VALUES ('2024-01-01', 0, 1, 1, 'Math', NULL, NULL)"
    )
    conn.commit()

    # Capture preset of current configuration
    preset = app.dump_configuration()
    assert 'timetable' not in preset['data']
    assert 'worksheets' not in preset['data']

    # Modify configuration
    cur.execute('UPDATE config SET slot_duration = 45 WHERE id = 1')
    conn.commit()
    conn.close()

    # Restore configuration from preset
    app.restore_configuration(preset, overwrite=True)

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    slot_duration = cur.execute('SELECT slot_duration FROM config').fetchone()[0]
    timetable_count = cur.execute('SELECT COUNT(*) FROM timetable').fetchone()[0]
    conn.close()

    # Slot duration reverted, timetable unaffected
    assert slot_duration == preset['data']['config'][0]['slot_duration']
    assert timetable_count == 1
