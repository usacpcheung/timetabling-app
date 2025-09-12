import os
import sys
import sqlite3

# Ensure the application package can be imported when tests are executed
# from within the ``tests`` directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_fixed_assignment_accepts_subject_name(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1,9)}
    data = {
        'slots_per_day':'8', 'slot_duration':'30',
        'min_lessons':'1', 'max_lessons':'4',
        'teacher_min_lessons':'1', 'teacher_max_lessons':'8',
        'max_repeats':'2', 'consecutive_weight':'3',
        'attendance_weight':'10', 'well_attend_weight':'1',
        'group_weight':'2.0', 'balance_weight':'1',
        'new_assign_teacher':'1', 'new_assign_student':'1',
        'new_assign_subject':'Math',
        'new_assign_slot':'1', **slot_starts
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    row = conn.execute('SELECT teacher_id, student_id, subject_id, slot FROM fixed_assignments').fetchone()
    conn.close()
    assert row['teacher_id'] == 1
    assert row['student_id'] == 1
    assert row['subject_id'] == math_id
    assert row['slot'] == 0
