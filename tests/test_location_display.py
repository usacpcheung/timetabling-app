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

    (_, _, teachers, grid, _, _, _, _, _) = app.get_timetable_data('2024-01-01')
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

    (_, _, locations, grid, _, _, _, _, _) = app.get_timetable_data('2024-01-01', view='location')
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

    (_, _, locations, grid, _, _, _, _, _) = app.get_timetable_data('2024-01-01', view='patient_only')
    assert grid[0][locations[0]['id']] == 'Student 1'
