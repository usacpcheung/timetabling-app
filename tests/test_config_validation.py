"""Regression tests for configuration validation logic."""

import json
import os
import sys
import sqlite3

from flask import get_flashed_messages
from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app

    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _config_row(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM config WHERE id=1').fetchone()
    conn.close()
    return dict(row)


def _valid_config_form(row):
    slot_starts = json.loads(row['slot_start_times']) if row['slot_start_times'] else []
    data = [
        ('slots_per_day', str(row['slots_per_day'])),
        ('slot_duration', str(row['slot_duration'])),
    ]
    for idx, start in enumerate(slot_starts, start=1):
        data.append((f'slot_start_{idx}', start))
    data.extend([
        ('min_lessons', str(row['min_lessons'])),
        ('max_lessons', str(row['max_lessons'])),
        ('teacher_min_lessons', str(row['teacher_min_lessons'])),
        ('teacher_max_lessons', str(row['teacher_max_lessons'])),
        ('max_repeats', str(row['max_repeats'])),
        ('consecutive_weight', str(row['consecutive_weight'])),
        ('attendance_weight', str(row['attendance_weight'])),
        ('group_weight', str(row['group_weight'])),
        ('well_attend_weight', str(row['well_attend_weight'])),
        ('balance_weight', str(row['balance_weight'])),
        ('solver_time_limit', str(row['solver_time_limit'])),
    ])
    for flag in [
        'allow_repeats',
        'prefer_consecutive',
        'allow_consecutive',
        'require_all_subjects',
        'use_attendance_priority',
        'allow_multi_teacher',
        'balance_teacher_load',
    ]:
        if row[flag]:
            data.append((flag, '1'))
    return MultiDict(data)


def test_reject_zero_slots_per_day(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = MultiDict([
        ('slots_per_day', '0'),
        ('slot_duration', '30'),
    ])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Slots per day and slot duration must be positive integers.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_negative_slot_duration(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = MultiDict([
        ('slots_per_day', '8'),
        ('slot_duration', '-5'),
    ])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Slots per day and slot duration must be positive integers.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_negative_min_lessons(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.setlist('min_lessons', ['-1'])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Minimum and maximum lessons must be zero or greater.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_negative_max_lessons(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.setlist('max_lessons', ['-3'])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Minimum and maximum lessons must be zero or greater.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_negative_teacher_lessons(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.setlist('teacher_min_lessons', ['-1'])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Global teacher minimum and maximum lessons must be zero or greater.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_min_lessons_greater_than_max(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.setlist('min_lessons', [str(original['max_lessons'] + 1)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Minimum lessons cannot exceed maximum lessons.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_min_lessons_greater_than_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    slots = original['slots_per_day']
    data.setlist('min_lessons', [str(slots + 1)])
    data.setlist('max_lessons', [str(slots + 2)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Minimum lessons cannot exceed slots per day.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_max_lessons_greater_than_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    slots = original['slots_per_day']
    data.setlist('max_lessons', [str(slots + 1)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Maximum lessons cannot exceed slots per day.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_teacher_min_lessons_greater_than_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    slots = original['slots_per_day']
    data.setlist('teacher_min_lessons', [str(slots + 1)])
    data.setlist('teacher_max_lessons', [str(slots + 2)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Global teacher minimum lessons cannot exceed slots per day.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_teacher_max_lessons_greater_than_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    slots = original['slots_per_day']
    data.setlist('teacher_max_lessons', [str(slots + 1)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Global teacher maximum lessons cannot exceed slots per day.') in flashes
    assert _config_row(app.DB_PATH) == original


def test_individual_teacher_limits_can_exceed_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    teacher = conn.execute(
        'SELECT id, name, subjects FROM teachers ORDER BY id LIMIT 1'
    ).fetchone()
    teacher_id = teacher['id']
    teacher_name = teacher['name']
    teacher_subjects = json.loads(teacher['subjects'])
    conn.close()

    base_items = list(_valid_config_form(config_row).items(multi=True))
    base_items.append(('teacher_id', str(teacher_id)))
    base_items.append((f'teacher_name_{teacher_id}', teacher_name))
    for subj_id in teacher_subjects:
        base_items.append((f'teacher_subjects_{teacher_id}', str(subj_id)))
    base_items.append((f'teacher_min_{teacher_id}', str(slots + 3)))
    base_items.append((f'teacher_max_{teacher_id}', str(slots + 4)))
    data = MultiDict(base_items)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM teachers WHERE id=?',
        (teacher_id,),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == slots + 3
    assert updated['max_lessons'] == slots + 4


def test_student_limits_ignore_global_rules(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    student = conn.execute(
        'SELECT id, name, subjects, active FROM students ORDER BY id LIMIT 1'
    ).fetchone()
    student_id = student['id']
    student_name = student['name']
    student_subjects = json.loads(student['subjects'])
    is_active = bool(student['active'])
    conn.close()

    base_items = list(_valid_config_form(config_row).items(multi=True))
    base_items.append(('student_id', str(student_id)))
    base_items.append((f'student_name_{student_id}', student_name))
    for subj_id in student_subjects:
        base_items.append((f'student_subjects_{student_id}', str(subj_id)))
    if is_active:
        base_items.append((f'student_active_{student_id}', '1'))
    base_items.append((f'student_min_{student_id}', str(slots + 8)))
    base_items.append((f'student_max_{student_id}', str(slots + 7)))
    data = MultiDict(base_items)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM students WHERE id=?',
        (student_id,),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == slots + 8
    assert updated['max_lessons'] == slots + 7
