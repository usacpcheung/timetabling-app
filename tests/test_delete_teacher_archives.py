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


def test_deleting_teacher_archives_and_cleans(tmp_path):
    import app
    conn = setup_db(tmp_path)
    c = conn.cursor()
    c.execute('DELETE FROM teachers')
    c.execute('DELETE FROM teachers_archive')
    c.execute('DELETE FROM timetable')
    c.execute('DELETE FROM teacher_unavailable')
    c.execute('DELETE FROM student_teacher_block')
    c.execute('DELETE FROM fixed_assignments')
    conn.commit()
    math_id = c.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    c.execute("INSERT INTO teachers (id, name, subjects, min_lessons, max_lessons) VALUES (1, 'Teach', '[]', 0, 0)")
    c.execute("INSERT INTO timetable (date, slot, student_id, teacher_id, subject_id, group_id, location_id) VALUES ('2024-01-01', 0, NULL, 1, ?, NULL, NULL)", (math_id,))
    c.execute("INSERT INTO teacher_unavailable (teacher_id, slot) VALUES (1, 0)")
    c.execute("INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (1, 1)")
    c.execute("INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject_id, slot) VALUES (1, NULL, NULL, ?, 0)", (math_id,))
    c.execute('UPDATE students SET active=0')
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
        'teacher_id': '1',
        'teacher_delete_1': 'on',
        'teacher_need_lessons_1': '1',
        **slot_starts,
    }
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    assert c.execute('SELECT COUNT(*) FROM teachers WHERE id=1').fetchone()[0] == 0
    assert c.execute('SELECT name FROM teachers_archive WHERE id=1').fetchone()[0] == 'Teach'
    assert c.execute('SELECT COUNT(*) FROM teacher_unavailable WHERE teacher_id=1').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM student_teacher_block WHERE teacher_id=1').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM fixed_assignments WHERE teacher_id=1').fetchone()[0] == 0
    row = c.execute("""
        SELECT COALESCE(te.name, ta.name) AS tname
        FROM timetable t
        LEFT JOIN teachers te ON t.teacher_id = te.id
        LEFT JOIN teachers_archive ta ON t.teacher_id = ta.id
    """).fetchone()
    assert row['tname'] == 'Teach'
    conn.close()
