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


def test_student_deletion_blocked_by_fixed_assignment(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()
    # create a fixed assignment for student 1
    c.execute(
        "INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot) VALUES (1, 1, NULL, 'Math', 0)"
    )
    conn.commit()

    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1, 9)}
    data = {
        'slots_per_day': '8',
        'slot_duration': '30',
        'min_lessons': '1',
        'max_lessons': '4',
        'teacher_min_lessons': '1',
        'teacher_max_lessons': '8',
        'max_repeats': '2',
        'consecutive_weight': '3',
        'attendance_weight': '10',
        'well_attend_weight': '1',
        'group_weight': '2.0',
        'balance_weight': '1',
        'student_id': '1',
        'student_delete_1': 'on',
        **slot_starts,
    }

    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    # student and fixed assignment should remain
    student = conn.execute('SELECT name FROM students WHERE id=1').fetchone()
    fa_count = conn.execute('SELECT COUNT(*) FROM fixed_assignments WHERE student_id=1').fetchone()[0]
    conn.close()

    assert student is not None
    assert fa_count == 1
