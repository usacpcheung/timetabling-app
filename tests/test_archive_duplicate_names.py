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


def test_deleted_students_with_same_name_are_distinct(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute('DELETE FROM students')
    c.execute('DELETE FROM students_archive')
    conn.commit()

    c.execute("INSERT INTO students (name, subjects) VALUES (?, ?)", ("Same Student", "[]"))
    first_id = c.lastrowid
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
        'student_id': str(first_id),
        f'student_delete_{first_id}': 'on',
        **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("INSERT INTO students (name, subjects) VALUES (?, ?)", ("Same Student", "[]"))
    second_id = c.lastrowid
    conn.commit()
    conn.close()

    data2 = {
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
        'student_id': str(second_id),
        f'student_delete_{second_id}': 'on',
        **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data2):
        app.config()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT id, name FROM students_archive WHERE id IN (?, ?)', (first_id, second_id))
    rows = c.fetchall()
    conn.close()

    names = {row['id']: row['name'] for row in rows}
    assert len(names) == 2
    assert names[first_id] != names[second_id]
    assert f'id {first_id}' in names[first_id]
    assert f'id {second_id}' in names[second_id]
