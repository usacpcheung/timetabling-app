import os
import sys

# Ensure application package import
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app, sqlite3
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_new_entity_location_restrictions(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    # create a location to reference
    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    conn.commit()

    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1,9)}
    data = {
        'slots_per_day':'8', 'slot_duration':'30',
        'min_lessons':'1', 'max_lessons':'4',
        'teacher_min_lessons':'1', 'teacher_max_lessons':'8',
        'max_repeats':'2', 'consecutive_weight':'3',
        'attendance_weight':'10', 'well_attend_weight':'1',
        'group_weight':'2.0', 'balance_weight':'1',
        'new_student_name':'Charlie',
        'new_student_subject_ids':[str(math_id)],
        'new_student_locs':['1'],
        'new_group_name':'Group C',
        'new_group_subjects':['Math'],
        'new_group_members':['1'],
        'new_group_locs':['1'],
        **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    sid = conn.execute("SELECT id FROM students WHERE name='Charlie'").fetchone()['id']
    s_loc = conn.execute('SELECT location_id FROM student_locations WHERE student_id=?', (sid,)).fetchone()
    assert s_loc['location_id'] == 1

    gid = conn.execute("SELECT id FROM groups WHERE name='Group C'").fetchone()['id']
    g_loc = conn.execute('SELECT location_id FROM group_locations WHERE group_id=?', (gid,)).fetchone()
    assert g_loc['location_id'] == 1
    conn.close()
