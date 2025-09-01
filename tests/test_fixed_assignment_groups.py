import os
import sys

# Ensure the application package can be imported when tests are executed
# from within the ``tests`` directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app, sqlite3
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_group_fixed_assignment_priority(tmp_path):
    import app, json
    conn = setup_db(tmp_path)
    c = conn.cursor()
    # create groups and members
    c.execute("INSERT INTO groups (name, subjects) VALUES ('Group A', ?)", (json.dumps(['Math']),))
    c.execute("INSERT INTO groups (name, subjects) VALUES ('Group B', ?)", (json.dumps(['Math']),))
    c.execute("INSERT INTO group_members (group_id, student_id) VALUES (1,1)")
    c.execute("INSERT INTO group_members (group_id, student_id) VALUES (2,2)")
    conn.commit()

    # prepare POST data with both student and group set
    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1,9)}
    data = {
        'slots_per_day':'8', 'slot_duration':'30',
        'min_lessons':'1', 'max_lessons':'4',
        'teacher_min_lessons':'1', 'teacher_max_lessons':'8',
        'max_repeats':'2', 'consecutive_weight':'3',
        'attendance_weight':'10', 'well_attend_weight':'1',
        'group_weight':'2.0', 'balance_weight':'1',
        'new_assign_teacher':'1', 'new_assign_group':'2',
        'new_assign_student':'1', 'new_assign_subject':'Math',
        'new_assign_slot':'1', **slot_starts
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    row = conn.execute('SELECT teacher_id, student_id, group_id, subject, slot FROM fixed_assignments').fetchone()
    conn.close()
    assert row['student_id'] is None
    assert row['group_id'] == 2
    assert row['teacher_id'] == 1
    assert row['subject'] == 'Math'
    assert row['slot'] == 0


def test_group_fixed_assignment_suppressed(tmp_path):
    import app, json
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute("INSERT INTO groups (name, subjects) VALUES ('Group A', ?)", (json.dumps(['Math']),))
    c.execute("INSERT INTO groups (name, subjects) VALUES ('Group B', ?)", (json.dumps(['Math']),))
    c.execute("INSERT INTO group_members (group_id, student_id) VALUES (1,1)")
    c.execute("INSERT INTO group_members (group_id, student_id) VALUES (2,2)")
    conn.commit()

    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1,9)}
    data = {
        'slots_per_day':'8', 'slot_duration':'30',
        'min_lessons':'1', 'max_lessons':'4',
        'teacher_min_lessons':'1', 'teacher_max_lessons':'8',
        'max_repeats':'2', 'consecutive_weight':'3',
        'attendance_weight':'10', 'well_attend_weight':'1',
        'group_weight':'0', 'balance_weight':'1',
        'new_assign_teacher':'1', 'new_assign_group':'2',
        'new_assign_student':'1', 'new_assign_subject':'Math',
        'new_assign_slot':'1', **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    row = conn.execute('SELECT teacher_id, student_id, group_id, subject, slot FROM fixed_assignments').fetchone()
    conn.close()
    assert row['group_id'] is None
    assert row['student_id'] == 1
    assert row['teacher_id'] == 1
    assert row['subject'] == 'Math'
    assert row['slot'] == 0
