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


def test_worksheet_subject_case_insensitive(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    client = app.app.test_client()
    client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': str(sid), 'subject': 'mAtH', 'assign': '1'},
    )

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    math = next(item for item in missing[sid] if item['subject'] == 'Math')
    assert math['count'] == 1
    assert math['today']


def test_worksheet_counts_after_subject_rename(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    subj_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    conn.commit()
    conn.close()

    client = app.app.test_client()
    client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': str(sid), 'subject': 'Math', 'assign': '1'},
    )

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE subjects SET name='Algebra' WHERE id=?", (subj_id,))
    cur.execute("DELETE FROM timetable_snapshot WHERE date='2024-01-01'")
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    item = next(entry for entry in missing[sid] if entry['subject'] == 'Algebra')
    assert item['count'] == 1
    assert item['today']


def test_timetable_subject_with_extra_spaces(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    client = app.app.test_client()
    client.post(
        '/edit_timetable/2024-01-01',
        data={'action': 'worksheet', 'student_id': str(sid), 'subject': 'Math', 'assign': '1'},
    )

    # Confirm worksheet counted before lesson exists
    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert any(item['subject'] == 'Math' for item in missing[sid])

    # Add a lesson with extra spaces around the subject
    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO timetable (student_id, group_id, teacher_id, subject, slot, date) VALUES (?, NULL, 1, ?, 0, ?)",
        (sid, '  Math  ', '2024-01-01'),
    )
    cur.execute("DELETE FROM timetable_snapshot WHERE date=?", ('2024-01-01',))
    conn.commit()
    conn.close()

    # Recompute and ensure the subject is recognised
    _, _, _, _, missing, _, _, _, lesson_counts = app.get_timetable_data('2024-01-01')
    assert all(item['subject'] != 'Math' for item in missing.get(sid, []))
    assert lesson_counts[sid] == 1
