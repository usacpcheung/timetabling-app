import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_restore_invalidation_updates_missing(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    # Initial snapshot with default subjects
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    missing, _ = app.get_missing_and_counts(cur, '2024-01-01')
    assert {m['subject'] for m in missing[sid]} == {'Math', 'English'}
    conn.commit()
    conn.close()

    # Change Student 1's subjects to Science only via preset restore
    preset = app.dump_configuration()
    science_id = next(s['id'] for s in preset['data']['subjects'] if s['name'] == 'Science')
    for stu in preset['data']['students']:
        if stu['id'] == sid:
            stu['subject_ids'] = json.dumps([science_id])
            stu['subjects'] = json.dumps([])
    app.restore_configuration(preset, overwrite=True)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Without refresh flag; should reflect Science only
    missing2, _ = app.get_missing_and_counts(cur, '2024-01-01')
    conn.close()
    assert {m['subject'] for m in missing2[sid]} == {'Science'}
