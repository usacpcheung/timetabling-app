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


def test_deleting_subject_archives(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute('DELETE FROM subjects')
    c.execute('DELETE FROM subjects_archive')
    c.execute('DELETE FROM timetable')
    conn.commit()
    c.execute("INSERT INTO subjects (id, name, min_percentage) VALUES (1, 'Sub', 0)")
    c.execute(
        "INSERT INTO timetable (date, slot, student_id, teacher_id, subject_id, group_id, location_id) "
        "VALUES ('2024-01-01', 0, NULL, NULL, 1, NULL, NULL)"
    )
    conn.commit()
    conn.close()

    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1, 9)}
    data = {
        'slots_per_day': '8',
        'slot_duration': '30',
        'min_lessons': '1',
        'max_lessons': '4',
        'teacher_min_lessons': '1',
        'teacher_max_lessons': '8',
        'allow_repeats': '1',
        'max_repeats': '2',
        'consecutive_weight': '3',
        'attendance_weight': '10',
        'well_attend_weight': '1',
        'group_weight': '2',
        'balance_weight': '1',
        'subject_id': '1',
        'subject_delete': '1',
        'subject_name_1': 'Sub',
        'subject_min_1': '0',
        **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    assert c.execute('SELECT COUNT(*) FROM subjects WHERE id=1').fetchone()[0] == 0
    assert c.execute('SELECT name FROM subjects_archive WHERE id=1').fetchone()[0] == 'Sub'
    row = c.execute(
        """
        SELECT COALESCE(sub.name, suba.name) AS subject
        FROM timetable t
        LEFT JOIN subjects sub ON t.subject_id = sub.id
        LEFT JOIN subjects_archive suba ON t.subject_id = suba.id
        """
    ).fetchone()
    assert row['subject'] == 'Sub'
    conn.close()

