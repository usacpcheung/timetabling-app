import os
import sys
from werkzeug.datastructures import MultiDict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app, sqlite3
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_batch_teacher_unavailability(tmp_path):
    import app
    conn = setup_db(tmp_path)
    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1,9)}
    data_items = [
        ('slots_per_day', '8'), ('slot_duration', '30'),
        ('min_lessons', '1'), ('max_lessons', '4'),
        ('teacher_min_lessons', '1'), ('teacher_max_lessons', '8'),
        ('allow_repeats', '1'),
        ('max_repeats', '2'), ('consecutive_weight', '3'),
        ('attendance_weight', '10'), ('well_attend_weight', '1'),
        ('group_weight', '2.0'), ('balance_weight', '1'),
        ('new_unavail_teacher', '1'), ('new_unavail_teacher', '2'),
        ('new_unavail_slot', '1'), ('new_unavail_slot', '2'),
    ] + list(slot_starts.items())
    data = MultiDict(data_items)
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()
    rows = conn.execute('SELECT teacher_id, slot FROM teacher_unavailable').fetchall()
    conn.close()
    assert {(r['teacher_id'], r['slot']) for r in rows} == {(1,0),(1,1),(2,0),(2,1)}


def test_clear_teacher_unavailability(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.executemany(
        'INSERT INTO teacher_unavailable (teacher_id, slot) VALUES (?, ?)',
        [(1, 0), (1, 1), (2, 1), (2, 3)],
    )
    conn.commit()
    slot_starts = {f'slot_start_{i}': f'08:{30 + (i-1)*30:02d}' for i in range(1, 9)}
    data_items = [
        ('slots_per_day', '8'), ('slot_duration', '30'),
        ('min_lessons', '1'), ('max_lessons', '4'),
        ('teacher_min_lessons', '1'), ('teacher_max_lessons', '8'),
        ('allow_repeats', '1'),
        ('max_repeats', '2'), ('consecutive_weight', '3'),
        ('attendance_weight', '10'), ('well_attend_weight', '1'),
        ('group_weight', '2.0'), ('balance_weight', '1'),
        ('clear_unavail_teacher', '1'), ('clear_unavail_teacher', '2'),
        ('clear_unavail_slot', '1'), ('clear_unavail_slot', '2'),
    ] + list(slot_starts.items())
    data = MultiDict(data_items)
    with app.app.test_request_context('/config', method='POST', data=data):
        app.config()
    rows = conn.execute('SELECT teacher_id, slot FROM teacher_unavailable').fetchall()
    conn.close()
    assert {(r['teacher_id'], r['slot']) for r in rows} == {(2, 3)}
