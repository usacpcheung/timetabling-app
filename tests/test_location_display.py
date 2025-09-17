import json
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

def test_location_shown_in_timetable_grid(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    # create a location and assign it to a timetable entry
    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    c.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, location_id, date) VALUES (1, 1, ?, 0, 1, '2024-01-01')",
        (math_id,),
    )
    conn.commit()
    conn.close()

    (_, _, teachers, grid, _, _, _, _, _, _) = app.get_timetable_data('2024-01-01')
    # timetable entry for teacher 1 in slot 0 should include the location name
    assert 'Room A' in grid[0][teachers[0]['id']]


def test_location_view_groups_by_location(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    c.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, location_id, date) VALUES (1, 1, ?, 0, 1, '2024-01-01')",
        (math_id,),
    )
    conn.commit()
    conn.close()

    (_, _, locations, grid, _, _, _, _, _, _) = app.get_timetable_data('2024-01-01', view='location')
    assert locations[0]['name'] == 'Room A'
    assert grid[0][locations[0]['id']] == 'Student 1 (Math) with Teacher A'


def test_patient_only_view(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    c.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, location_id, date) VALUES (1, 1, ?, 0, 1, '2024-01-01')",
        (math_id,),
    )
    conn.commit()
    conn.close()

    (_, _, locations, grid, _, _, _, _, _, _) = app.get_timetable_data('2024-01-01', view='patient_only')
    assert grid[0][locations[0]['id']] == 'Student 1'


def test_deleted_group_members_display_from_snapshot(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()

    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    teacher_id = c.execute("SELECT id FROM teachers WHERE name='Teacher A'").fetchone()[0]

    c.execute("INSERT INTO groups (name, subjects) VALUES (?, ?)", ('Legacy Group', json.dumps([math_id])))
    gid = c.lastrowid
    c.executemany(
        "INSERT INTO group_members (group_id, student_id) VALUES (?, ?)",
        [(gid, 1), (gid, 2)],
    )
    c.execute(
        "INSERT INTO timetable (student_id, group_id, teacher_id, subject_id, slot, location_id, date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (None, gid, teacher_id, math_id, 0, None, '2024-01-01'),
    )

    app.get_missing_and_counts(c, '2024-01-01', refresh=True)
    conn.commit()

    c.execute('INSERT INTO groups_archive (id, name) VALUES (?, ?)', (gid, 'Legacy Group'))
    c.execute('DELETE FROM group_members WHERE group_id=?', (gid,))
    c.execute('DELETE FROM groups WHERE id=?', (gid,))
    conn.commit()
    conn.close()

    (_, _, _, grid, _, _, _, _, _, group_view) = app.get_timetable_data('2024-01-01')
    entry = grid[0][teacher_id]

    assert 'Legacy Group' in entry
    assert 'Student 1' in entry
    assert 'Student 2' in entry
    assert '[]' not in entry

    members = group_view[gid]['members']
    assert {m['name'] for m in members} >= {'Student 1', 'Student 2'}


def test_group_membership_updates_after_refresh(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()

    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    teacher_id = c.execute("SELECT id FROM teachers WHERE name='Teacher A'").fetchone()[0]

    c.execute("INSERT INTO groups (name, subjects) VALUES (?, ?)", ('Dynamic Group', json.dumps([math_id])))
    gid = c.lastrowid
    c.executemany(
        "INSERT INTO group_members (group_id, student_id) VALUES (?, ?)",
        [(gid, 1), (gid, 2)],
    )
    c.execute(
        "INSERT INTO timetable (student_id, group_id, teacher_id, subject_id, slot, location_id, date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (None, gid, teacher_id, math_id, 0, None, '2024-01-01'),
    )

    app.get_missing_and_counts(c, '2024-01-01', refresh=True)
    conn.commit()

    # Update the group membership after the snapshot has been created.
    c.execute('DELETE FROM group_members WHERE group_id=?', (gid,))
    c.executemany(
        "INSERT INTO group_members (group_id, student_id) VALUES (?, ?)",
        [(gid, 1), (gid, 3)],
    )
    conn.commit()

    # Without refreshing the snapshot the timetable view should show the old members.
    (_, _, _, grid, _, _, _, _, _, group_view) = app.get_timetable_data('2024-01-01')
    entry = grid[0][teacher_id]
    assert 'Student 2' in entry
    assert 'Student 3' not in entry
    members_before = {m['id'] for m in group_view[gid]['members']}
    assert members_before >= {1, 2}
    assert 3 not in members_before

    # Simulate pressing the refresh button which regenerates the snapshot for the date.
    app.get_missing_and_counts(c, '2024-01-01', refresh=True)
    conn.commit()

    (_, _, _, refreshed_grid, _, _, _, _, _, refreshed_group_view) = app.get_timetable_data('2024-01-01')
    refreshed_entry = refreshed_grid[0][teacher_id]
    assert 'Student 3' in refreshed_entry
    members_after = {m['id'] for m in refreshed_group_view[gid]['members']}
    assert members_after >= {1, 3}
    assert 2 not in members_after

    conn.close()


def test_deleted_location_displayed_from_snapshot(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()

    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    teacher_id = c.execute("SELECT id FROM teachers WHERE name='Teacher A'").fetchone()[0]

    c.execute("INSERT INTO locations (name) VALUES ('Room A')")
    c.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject_id, slot, location_id, date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (1, teacher_id, math_id, 0, 1, '2024-01-01'),
    )

    app.get_missing_and_counts(c, '2024-01-01', refresh=True)
    conn.commit()

    c.execute("INSERT INTO locations_archive (id, name) VALUES (?, ?)", (1, 'Room A'))
    c.execute('DELETE FROM locations WHERE id=?', (1,))
    conn.commit()
    conn.close()

    (_, _, _, teacher_grid, _, _, _, _, _, _) = app.get_timetable_data('2024-01-01')
    teacher_entry = teacher_grid[0][teacher_id]
    assert 'Room A' in teacher_entry

    (_, _, locations, location_grid, _, _, _, _, _, _) = app.get_timetable_data('2024-01-01', view='location')
    archived_col = next(col for col in locations if col['id'] == 1)
    assert archived_col['name'] == 'Room A'
    assert location_grid[0][1] == 'Student 1 (Math) with Teacher A'
