import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_inactive_student_listed_in_missing(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    cur.execute("UPDATE students SET active=0 WHERE id=?", (sid,))
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid in missing
    subjects = {item['subject'] for item in missing[sid]}
    assert subjects == {'Math', 'English'}


def test_worksheet_counts_separate_by_id(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid_old = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.executemany(
        "INSERT INTO worksheets (student_id, subject_id, date) VALUES (?, ?, ?)",
        [
            (sid_old, math_id, '2024-01-01'),
            (sid_old, math_id, '2024-01-02'),
        ],
    )
    cur.execute("INSERT INTO students_archive (id, name) VALUES (?, ?)", (sid_old, 'Student 1'))
    cur.execute("DELETE FROM students WHERE id=?", (sid_old,))
    cur.execute(
        "INSERT INTO students (name, subjects, subject_ids, active) VALUES (?, ?, ?, 0)",
        ('Student 1', json.dumps(['Math']), json.dumps([math_id])),
    )
    sid_new = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-03')
    assert sid_new in missing
    math = next(item for item in missing[sid_new] if item['subject'] == 'Math')
    assert math['count'] == 0


def test_highlighted_when_worksheet_on_date(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO worksheets (student_id, subject_id, date) VALUES (?, ?, ?)",
        (sid, math_id, '2024-01-01'),
    )
    # insert a timetable row for another student so the view renders the timetable
    other = cur.execute("SELECT id FROM students WHERE name='Student 2'").fetchone()[0]
    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject, slot, date) VALUES (?, ?, ?, ?, ?)",
        (other, 1, 'Math', 0, '2024-01-01'),
    )
    conn.commit()
    conn.close()

    client = app.app.test_client()
    resp = client.get('/', query_string={'date': '2024-01-01'})
    html = resp.get_data(as_text=True)
    assert 'worksheet-assigned">Math (1)' in html
    assert 'English (0)' in html


def test_prior_lessons_included_in_counts(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    # add a previous lesson for Math
    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject, slot, date) VALUES (?, ?, ?, ?, ?)",
        (sid, 1, 'Math', 0, '2024-01-01'),
    )
    conn.commit()
    conn.close()

    # Now counts reflect worksheets only; a prior lesson does not increment worksheet count
    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-02')
    math = next(item for item in missing[sid] if item['subject'] == 'Math')
    assert math['count'] == 0


def test_deleted_student_preserved_in_missing(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject, slot, date) VALUES (?, ?, ?, ?, ?)",
        (sid, 1, 'Math', 0, '2024-01-01'),
    )
    conn.commit()
    conn.close()

    app.get_timetable_data('2024-01-01')

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO students_archive (id, name) VALUES (?, ?)", (sid, 'Student 1'))
    cur.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit()
    conn.close()

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid in missing
    subjects = {item['subject'] for item in missing[sid]}
    assert subjects == {'English'}


def test_refresh_removes_deleted_student(tmp_path):
    import app
    conn = setup_db(tmp_path)
    cur = conn.cursor()
    sid = cur.execute("SELECT id FROM students WHERE name='Student 1'").fetchone()[0]
    cur.execute(
        "INSERT INTO timetable (student_id, teacher_id, subject, slot, date) VALUES (?, ?, ?, ?, ?)",
        (sid, 1, 'Math', 0, '2024-01-01'),
    )
    conn.commit()
    conn.close()

    app.get_timetable_data('2024-01-01')

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO students_archive (id, name) VALUES (?, ?)", (sid, 'Student 1'))
    cur.execute("DELETE FROM students WHERE id=?", (sid,))
    conn.commit()
    conn.close()

    client = app.app.test_client()
    resp = client.post('/edit_timetable/2024-01-01', data={'action': 'refresh'})
    assert resp.status_code == 302

    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid not in missing


def test_added_student_not_in_missing_until_refresh(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.close()

    # generate initial snapshot for the date
    app.get_timetable_data('2024-01-01')

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    math_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO students (name, subjects, subject_ids, active) VALUES (?, ?, ?, 1)",
        ('New Student', json.dumps(['Math']), json.dumps([math_id]))
    )
    sid_new = cur.lastrowid
    conn.commit()
    conn.close()

    # simulate application restart which runs migrations
    app.init_db()

    # new student should not appear in existing missing list
    _, _, _, _, missing, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid_new not in missing

    # after manual refresh the student is included
    client = app.app.test_client()
    client.post('/edit_timetable/2024-01-01', data={'action': 'refresh'})
    _, _, _, _, missing2, _, _, _, _ = app.get_timetable_data('2024-01-01')
    assert sid_new in missing2
