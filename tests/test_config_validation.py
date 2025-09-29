"""Regression tests for configuration validation logic."""

import json
import os
import sys
import sqlite3
from html.parser import HTMLParser

from flask import get_flashed_messages
from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


from cp_sat_timetable import build_model


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
        ('attendance_weight', str(row['attendance_weight'])),
        ('group_weight', str(row['group_weight'])),
        ('well_attend_weight', str(row['well_attend_weight'])),
        ('balance_weight', str(row['balance_weight'])),
        ('solver_time_limit', str(row['solver_time_limit'])),
    ])
    if row['allow_repeats']:
        data.extend([
            ('max_repeats', str(row['max_repeats'])),
            ('consecutive_weight', str(row['consecutive_weight'])),
        ])
    repeat_flags = {'allow_consecutive', 'prefer_consecutive'}
    for flag in [
        'allow_repeats',
        'prefer_consecutive',
        'allow_consecutive',
        'require_all_subjects',
        'use_attendance_priority',
        'allow_multi_teacher',
        'balance_teacher_load',
    ]:
        if not row[flag]:
            continue
        if flag in repeat_flags and not row['allow_repeats']:
            continue
        data.append((flag, '1'))
    return MultiDict(data)


def _teacher_edit_form(config_row, teacher_row):
    data = _valid_config_form(config_row)
    tid = teacher_row['id']
    data.add('teacher_id', str(tid))
    data.add(f'teacher_name_{tid}', teacher_row['name'])
    for subj_id in json.loads(teacher_row['subjects']):
        data.add(f'teacher_subjects_{tid}', str(subj_id))
    needs_lessons = teacher_row['needs_lessons'] if 'needs_lessons' in teacher_row.keys() else 1
    if needs_lessons:
        data.add(f'teacher_need_lessons_{tid}', '1')
    return data


def _teachers_form(config_row, teacher_rows):
    data = _valid_config_form(config_row)
    for teacher in teacher_rows:
        tid = teacher['id']
        data.add('teacher_id', str(tid))
        data.add(f'teacher_name_{tid}', teacher['name'])
        for subj_id in json.loads(teacher['subjects']):
            data.add(f'teacher_subjects_{tid}', str(subj_id))
        needs_lessons = teacher.get('needs_lessons', 1)
        if needs_lessons:
            data.add(f'teacher_need_lessons_{tid}', '1')
        if teacher.get('min_lessons') is not None:
            data.add(f'teacher_min_{tid}', str(teacher['min_lessons']))
        if teacher.get('max_lessons') is not None:
            data.add(f'teacher_max_{tid}', str(teacher['max_lessons']))
    return data


def _student_edit_form(config_row, student_row):
    data = _valid_config_form(config_row)
    sid = student_row['id']
    data.add('student_id', str(sid))
    data.add(f'student_name_{sid}', student_row['name'])
    for subj_id in json.loads(student_row['subjects']):
        data.add(f'student_subjects_{sid}', str(subj_id))
    if student_row['active']:
        data.add(f'student_active_{sid}', '1')
    return data


def _post_invalid_weight(tmp_path, field, value, expected_error, extra_updates=None):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    if extra_updates:
        for key, update in extra_updates.items():
            if isinstance(update, (list, tuple)):
                values = [str(item) for item in update]
            else:
                values = [str(update)]
            data.setlist(key, values)
    data.setlist(field, [str(value)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', expected_error) in flashes
    assert (
        'error',
        'Configuration not saved; changes have been rolled back.',
    ) in flashes
    assert _config_row(app.DB_PATH) == original


def test_reject_negative_consecutive_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'consecutive_weight',
        '-1',
        'Consecutive weight must be at least 1.',
        extra_updates={'allow_repeats': '1', 'max_repeats': '2'},
    )


def test_reject_non_numeric_consecutive_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'consecutive_weight',
        'abc',
        'Consecutive weight must be an integer.',
        extra_updates={'allow_repeats': '1', 'max_repeats': '2'},
    )


def test_reject_negative_attendance_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'attendance_weight',
        '-5',
        'Attendance weight must be at least 1.',
    )


def test_reject_non_numeric_attendance_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'attendance_weight',
        'oops',
        'Attendance weight must be an integer.',
    )


def test_reject_negative_well_attend_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'well_attend_weight',
        '-0.5',
        'Well-attend weight must be zero or greater.',
    )


def test_reject_non_numeric_well_attend_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'well_attend_weight',
        'bad',
        'Well-attend weight must be a number.',
    )


def test_reject_negative_group_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'group_weight',
        '-0.5',
        'Group weight must be zero or greater.',
    )


def test_reject_non_numeric_group_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'group_weight',
        'invalid',
        'Group weight must be a number.',
    )


def test_reject_negative_balance_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'balance_weight',
        '-1',
        'Balance weight must be at least 1.',
    )


def test_reject_non_numeric_balance_weight(tmp_path):
    _post_invalid_weight(
        tmp_path,
        'balance_weight',
        'nope',
        'Balance weight must be an integer.',
    )


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


def test_reject_student_minimum_exceeding_available_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    student_row = conn.execute('SELECT * FROM students LIMIT 1').fetchone()
    original_student = dict(student_row)
    original_unavail = [
        row['slot']
        for row in conn.execute(
            'SELECT slot FROM student_unavailable WHERE student_id=? ORDER BY slot',
            (student_row['id'],),
        )
    ]
    conn.close()

    data = _student_edit_form(config_row, student_row)
    sid = student_row['id']
    assert config_row['slots_per_day'] >= 2
    blocked_slots = [str(i) for i in range(config_row['slots_per_day'] - 1)]
    desired_min = min(config_row['slots_per_day'], config_row['min_lessons'] + 2)
    data.setlist(f'student_min_{sid}', [str(desired_min)])
    data.setlist(f'student_max_{sid}', [str(config_row['slots_per_day'])])
    data.setlist(f'student_unavail_{sid}', blocked_slots)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = (
        'error',
        f"Student minimum lessons cannot exceed available slots after marking unavailability for {student_row['name']}.",
    )
    assert expected in flashes

    assert _config_row(app.DB_PATH) == config_row

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute('SELECT min_lessons, max_lessons FROM students WHERE id=?', (sid,)).fetchone()
    updated_unavail = [
        row['slot']
        for row in conn.execute(
            'SELECT slot FROM student_unavailable WHERE student_id=? ORDER BY slot',
            (sid,),
        )
    ]
    conn.close()

    assert updated['min_lessons'] == original_student['min_lessons']
    assert updated['max_lessons'] == original_student['max_lessons']
    assert updated_unavail == original_unavail


def test_allow_repeats_without_multi_teacher(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.add('allow_repeats', '1')
    data.pop('allow_multi_teacher', None)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert (
        'error',
        'Cannot allow repeats when different teachers per subject are disallowed.',
    ) not in flashes
    updated = _config_row(app.DB_PATH)
    assert updated['allow_repeats'] == 1
    assert updated['allow_multi_teacher'] == 0


def test_reject_repeat_settings_when_repeats_disabled(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_row(app.DB_PATH)

    data = _valid_config_form(original)
    data.pop('allow_repeats', None)
    data.setlist('max_repeats', ['3'])
    data.setlist('consecutive_weight', ['2'])
    data.setlist('allow_consecutive', ['1'])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Repeated lesson settings require "Allow repeated lessons?" to be enabled.'
    assert ('error', expected) in flashes
    updated = _config_row(app.DB_PATH)
    assert updated['allow_repeats'] == original['allow_repeats']
    assert updated['max_repeats'] == original['max_repeats']
    assert updated['allow_consecutive'] == original['allow_consecutive']
    assert updated['consecutive_weight'] == original['consecutive_weight']


def test_disable_repeats_without_repeat_inputs(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.execute(
        'UPDATE config SET allow_repeats=1, max_repeats=4, allow_consecutive=1, '
        'prefer_consecutive=1, consecutive_weight=5 WHERE id=1'
    )
    conn.commit()
    conn.close()

    original = _config_row(app.DB_PATH)
    assert original['allow_repeats'] == 1

    data = _valid_config_form(original)
    for field in (
        'allow_repeats',
        'max_repeats',
        'allow_consecutive',
        'prefer_consecutive',
        'consecutive_weight',
    ):
        data.pop(field, None)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert not any(category == 'error' for category, _ in flashes)

    updated = _config_row(app.DB_PATH)
    assert updated['allow_repeats'] == 0
    assert updated['max_repeats'] == 1
    assert updated['allow_consecutive'] == 0
    assert updated['prefer_consecutive'] == 0
    assert updated['consecutive_weight'] == 5


def test_repeat_controls_render_disabled_when_repeats_off(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()

    with app.app.test_client() as client:
        response = client.get('/config')

    assert response.status_code == 200
    html = response.get_data(as_text=True)

    class InputCollector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inputs = []
            self.labels = {}

        def handle_starttag(self, tag, attrs):
            if tag != 'input':
                if tag == 'label':
                    attrs_dict = dict(attrs)
                    target = attrs_dict.get('for')
                    if target:
                        self.labels[target] = attrs_dict
                return
            self.inputs.append(dict(attrs))

    parser = InputCollector()
    parser.feed(html)

    def find_input(name):
        for attrs in parser.inputs:
            if attrs.get('name') == name:
                return attrs
        raise AssertionError(f'Could not find input named {name}')

    for field in ('max_repeats', 'allow_consecutive', 'prefer_consecutive'):
        attrs = find_input(field)
        assert 'disabled' in attrs, f'{field} should render disabled when repeats are off'

    weight_attrs = find_input('consecutive_weight')
    assert 'disabled' not in weight_attrs, 'consecutive_weight should remain enabled for form submission'
    assert 'readonly' in weight_attrs, 'consecutive_weight should render readonly when repeats are off'
    assert weight_attrs.get('aria-disabled') == 'true'

    def assert_dimmed(field_id):
        attrs = parser.labels.get(field_id)
        assert attrs is not None, f'Label for {field_id} should be present'
        classes = attrs.get('class', '')
        class_list = classes.split()
        assert 'repeat-control' in class_list, f'Label for {field_id} should mark repeat-control'
        assert 'repeat-disabled' in class_list, f'Label for {field_id} should be dimmed when repeats are off'

    for label_id in ('max_repeats', 'allow_consecutive', 'prefer_consecutive', 'consecutive_weight'):
        assert_dimmed(label_id)


def test_student_consecutive_bonus_preserved_when_repeats_disabled():
    students = [
        {'id': 1, 'subjects': json.dumps([1])},
        {'id': 2, 'subjects': json.dumps([1])},
    ]
    teachers = [
        {'id': 1, 'subjects': json.dumps([1]), 'min_lessons': None, 'max_lessons': None},
    ]
    student_repeat = {
        1: {
            'allow_repeats': True,
            'max_repeats': 2,
            'allow_consecutive': True,
            'prefer_consecutive': True,
        },
        2: {
            'allow_repeats': False,
            'max_repeats': 1,
            'allow_consecutive': False,
            'prefer_consecutive': False,
        },
    }

    model, _, _, _ = build_model(
        students,
        teachers,
        slots=3,
        min_lessons=0,
        max_lessons=3,
        allow_repeats=False,
        max_repeats=1,
        prefer_consecutive=False,
        allow_consecutive=False,
        consecutive_weight=5,
        student_repeat=student_repeat,
    )

    proto = model.Proto()
    var_names = {idx: var.name for idx, var in enumerate(proto.variables)}
    adjacency_coeffs = {
        var_names[idx]: coeff
        for idx, coeff in zip(proto.objective.vars, proto.objective.coeffs)
        if var_names[idx].startswith('adj_')
    }

    assert adjacency_coeffs, 'Expected adjacency bonuses when a student prefers consecutive lessons'
    assert all(name.startswith('adj_s1') for name in adjacency_coeffs), (
        'Only the student with the preference should receive adjacency bonuses'
    )
    expected_coeff = -int(round(5 * 100))
    assert all(coeff == expected_coeff for coeff in adjacency_coeffs.values())


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


def test_reject_teacher_individual_min_exceeding_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    teacher = conn.execute(
        'SELECT id, name, subjects, min_lessons, max_lessons FROM teachers ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _teacher_edit_form(config_row, teacher)
    data.setlist(f'teacher_min_{teacher["id"]}', [str(slots + 1)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Teacher minimum lessons cannot exceed slots per day for ' + teacher['name'] + '.'
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM teachers WHERE id=?',
        (teacher['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == teacher['min_lessons']
    assert updated['max_lessons'] == teacher['max_lessons']


def test_reject_teacher_individual_max_exceeding_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    teacher = conn.execute(
        'SELECT id, name, subjects, min_lessons, max_lessons FROM teachers ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _teacher_edit_form(config_row, teacher)
    data.setlist(f'teacher_max_{teacher["id"]}', [str(slots + 2)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Teacher maximum lessons cannot exceed slots per day for ' + teacher['name'] + '.'
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM teachers WHERE id=?',
        (teacher['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == teacher['min_lessons']
    assert updated['max_lessons'] == teacher['max_lessons']


def test_reject_teacher_individual_min_greater_than_max(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    teacher = conn.execute(
        'SELECT id, name, subjects, min_lessons, max_lessons FROM teachers ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _teacher_edit_form(config_row, teacher)
    data.setlist(f'teacher_min_{teacher["id"]}', [str(slots)])
    data.setlist(f'teacher_max_{teacher["id"]}', [str(max(slots - 1, 0))])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Teacher min lessons greater than max for ' + teacher['name']
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM teachers WHERE id=?',
        (teacher['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == teacher['min_lessons']
    assert updated['max_lessons'] == teacher['max_lessons']


def test_reject_teacher_unavailability_that_breaks_minimum(tmp_path):
    import app

    conn = setup_db(tmp_path)
    teacher_row = conn.execute('SELECT id, name FROM teachers WHERE name=?', ('Teacher A',)).fetchone()
    assert teacher_row is not None
    original_unavailability = [
        (row['teacher_id'], row['slot'])
        for row in conn.execute('SELECT teacher_id, slot FROM teacher_unavailable').fetchall()
    ]
    conn.close()

    original_config = _config_row(app.DB_PATH)

    data = _valid_config_form(original_config)
    data.setlist('teacher_min_lessons', ['5'])
    data.add('new_unavail_teacher', str(teacher_row['id']))
    for slot in ['1', '2', '3', '4', '5']:
        data.add('new_unavail_slot', slot)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected_message = (
        f"{teacher_row['name']} requires at least 5 lessons but only 3 slots remain after marking unavailability."
    )
    assert ('error', expected_message) in flashes
    assert _config_row(app.DB_PATH) == original_config

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_unavailability = [
        (row['teacher_id'], row['slot'])
        for row in conn.execute('SELECT teacher_id, slot FROM teacher_unavailable').fetchall()
    ]
    conn.close()
    assert updated_unavailability == original_unavailability


def test_warn_when_disabling_last_teacher_for_subject(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    teacher = conn.execute(
        'SELECT * FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher is not None

    subject_ids = [int(sid) for sid in json.loads(teacher['subjects'])]
    assert len(subject_ids) == 1
    subject_id = subject_ids[0]
    subject_row = conn.execute(
        'SELECT name FROM subjects WHERE id=?',
        (subject_id,),
    ).fetchone()
    assert subject_row is not None
    subject_name = subject_row['name']

    students = conn.execute('SELECT * FROM students').fetchall()
    target_student = None
    for student in students:
        subjects = [int(sid) for sid in json.loads(student['subjects'])]
        if subject_id in subjects:
            target_student = student
            break
    assert target_student is not None
    student_name = target_student['name']

    conn.close()

    data = _teacher_edit_form(config_row, teacher)
    data.pop(f'teacher_need_lessons_{teacher["id"]}', None)

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = (
        'warning',
        f'No teacher scheduled for {subject_name} for student {student_name}; the solver will skip this subject.',
    )
    assert expected in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT needs_lessons FROM teachers WHERE id=?',
        (teacher['id'],),
    ).fetchone()
    conn.close()

    assert updated['needs_lessons'] == 0


def test_warn_when_disabling_last_teacher_for_group_subject(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert subject_row is not None

    teacher_row = conn.execute(
        'SELECT * FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    member_rows = conn.execute(
        'SELECT id, name FROM students WHERE name IN (?, ?)',
        ('Student 2', 'Student 4'),
    ).fetchall()
    member_ids = [row['id'] for row in member_rows]
    assert member_ids, 'Expected at least one student requiring Science'

    group_name = 'Science Group'
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO groups (name, subjects) VALUES (?, ?)',
        (group_name, json.dumps([subject_row['id']])),
    )
    group_id = cursor.lastrowid
    for sid in member_ids:
        cursor.execute(
            'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
            (group_id, sid),
        )
    conn.commit()
    conn.close()

    data = _teacher_edit_form(config_row, teacher_row)
    data.pop(f'teacher_need_lessons_{teacher_row["id"]}', None)
    data.add('group_id', str(group_id))
    data.add(f'group_name_{group_id}', group_name)
    data.setlist(f'group_subjects_{group_id}', [str(subject_row['id'])])
    data.setlist(f'group_members_{group_id}', [str(sid) for sid in member_ids])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert (
        'success',
        'Configuration saved successfully.',
    ) in flashes
    expected_student_warning = (
        'warning',
        f'No teacher scheduled for {subject_row["name"]} for student Student 2; the solver will skip this subject.',
    )
    assert expected_student_warning in flashes
    expected_group_warning = (
        'warning',
        f'No teacher scheduled for {subject_row["name"]} in group {group_name}; the solver will skip this subject.',
    )
    assert expected_group_warning in flashes
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_teacher = conn.execute(
        'SELECT needs_lessons FROM teachers WHERE id=?',
        (teacher_row['id'],),
    ).fetchone()
    assert updated_teacher['needs_lessons'] == 0
    persisted_group = conn.execute(
        'SELECT name FROM groups WHERE id=?',
        (group_id,),
    ).fetchone()
    assert persisted_group is not None
    conn.close()


def test_student_validation_warns_when_all_teachers_blocked(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert subject_row is not None

    teacher_row = conn.execute(
        'SELECT id FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    student_row = conn.execute(
        'SELECT * FROM students WHERE name=?',
        ('Student 2',),
    ).fetchone()
    assert student_row is not None

    conn.execute(
        'INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
        (student_row['id'], teacher_row['id']),
    )
    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    data.setlist('solver_time_limit', ['135'])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert (
        'success',
        'Configuration saved successfully.',
    ) in flashes
    expected_warning = (
        'warning',
        f'No teacher available for {subject_row["name"]} for student {student_row["name"]}; the solver will skip this subject.',
    )
    assert expected_warning in flashes
    assert all(category != 'error' for category, _ in flashes)

    updated_config = _config_row(app.DB_PATH)
    assert updated_config['solver_time_limit'] == 135


def test_batch_subject_removal_auto_deletes_group(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    math_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Math',),
    ).fetchone()
    assert math_row is not None

    student_rows = conn.execute(
        'SELECT * FROM students WHERE name IN (?, ?)',
        ('Student 1', 'Student 2'),
    ).fetchall()
    assert len(student_rows) == 2

    group_name = 'Math Club'
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO groups (name, subjects) VALUES (?, ?)',
        (group_name, json.dumps([math_row['id']])),
    )
    group_id = cursor.lastrowid
    for row in student_rows:
        cursor.execute(
            'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
            (group_id, row['id']),
        )
    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    for row in student_rows:
        sid = row['id']
        data.add('student_id', str(sid))
        data.add(f'student_name_{sid}', row['name'])
        for subj_id in json.loads(row['subjects']):
            data.add(f'student_subjects_{sid}', str(subj_id))
        if row['active']:
            data.add(f'student_active_{sid}', '1')

    data.add('group_id', str(group_id))
    data.add(f'group_name_{group_id}', group_name)
    data.setlist(f'group_subjects_{group_id}', [str(math_row['id'])])
    data.setlist(
        f'group_members_{group_id}',
        [str(row['id']) for row in student_rows],
    )

    # Remove Math from Student 2 via the batch subject controls.
    student_ids = sorted(row['id'] for row in student_rows)
    data.setlist('batch_students', [str(sid) for sid in student_ids])
    data.add('batch_subject_action', 'remove')
    data.add('batch_subjects', str(math_row['id']))

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)
    removal_notice = [
        message
        for category, message in flashes
        if category == 'info'
        and 'Removed Math' in message
        and group_name in message
    ]
    assert removal_notice, f'Expected removal notice in flashes, saw: {flashes}'
    auto_delete_notice = [
        message
        for category, message in flashes
        if category == 'info'
        and 'Auto-removed' in message
        and group_name in message
    ]
    assert auto_delete_notice, f'Expected auto-removal notice, saw: {flashes}'

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_group = conn.execute(
        'SELECT 1 FROM groups WHERE id=?',
        (group_id,),
    ).fetchone()
    assert updated_group is None
    remaining_members = conn.execute(
        'SELECT 1 FROM group_members WHERE group_id=?',
        (group_id,),
    ).fetchone()
    assert remaining_members is None
    remaining_locations = conn.execute(
        'SELECT 1 FROM group_locations WHERE group_id=?',
        (group_id,),
    ).fetchone()
    assert remaining_locations is None
    updated_students = conn.execute(
        'SELECT id, subjects FROM students WHERE id IN (?, ?)',
        tuple(student_ids),
    ).fetchall()
    conn.close()

    subjects_by_id = {row['id']: json.loads(row['subjects']) for row in updated_students}
    assert math_row['id'] not in subjects_by_id[student_ids[0]]
    assert math_row['id'] not in subjects_by_id[student_ids[1]]


def test_batch_subject_removal_clears_group_fixed_assignments(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    math_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Math',),
    ).fetchone()
    science_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert math_row is not None and science_row is not None

    student_rows = conn.execute(
        'SELECT * FROM students WHERE name IN (?, ?)',
        ('Student 2', 'Student 4'),
    ).fetchall()
    assert len(student_rows) == 2

    group_name = 'STEM Club'
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO groups (name, subjects) VALUES (?, ?)',
        (group_name, json.dumps([math_row['id'], science_row['id']])),
    )
    group_id = cursor.lastrowid
    for row in student_rows:
        cursor.execute(
            'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
            (group_id, row['id']),
        )

    teacher_row = conn.execute(
        'SELECT id FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    cursor.execute(
        'INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject_id, slot) '
        'VALUES (?, NULL, ?, ?, 0)',
        (teacher_row['id'], group_id, science_row['id']),
    )
    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    for row in student_rows:
        sid = row['id']
        data.add('student_id', str(sid))
        data.add(f'student_name_{sid}', row['name'])
        for subj_id in json.loads(row['subjects']):
            data.add(f'student_subjects_{sid}', str(subj_id))
        if row['active']:
            data.add(f'student_active_{sid}', '1')

    data.add('group_id', str(group_id))
    data.add(f'group_name_{group_id}', group_name)
    data.setlist(
        f'group_subjects_{group_id}',
        [str(math_row['id']), str(science_row['id'])],
    )
    data.setlist(
        f'group_members_{group_id}',
        [str(row['id']) for row in student_rows],
    )

    student_two = next(row for row in student_rows if row['name'] == 'Student 2')
    data.setlist('batch_students', [str(student_two['id'])])
    data.add('batch_subject_action', 'remove')
    data.add('batch_subjects', str(science_row['id']))

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    removal_notice = [
        message
        for category, message in flashes
        if category == 'info'
        and f'Removed {science_row["name"]}' in message
        and group_name in message
    ]
    assert removal_notice, f'Expected subject removal notice, saw: {flashes}'

    fixed_notice = [
        message
        for category, message in flashes
        if category == 'info'
        and 'Removed fixed assignments' in message
        and science_row['name'] in message
        and group_name in message
    ]
    assert fixed_notice, f'Expected fixed-assignment removal notice, saw: {flashes}'

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_subjects = conn.execute(
        'SELECT subjects FROM groups WHERE id=?',
        (group_id,),
    ).fetchone()
    assert updated_subjects is not None
    assert json.loads(updated_subjects['subjects']) == [math_row['id']]
    remaining_fixed = conn.execute(
        'SELECT 1 FROM fixed_assignments WHERE group_id=? AND subject_id=?',
        (group_id, science_row['id']),
    ).fetchone()
    conn.close()

    assert remaining_fixed is None


def test_batch_location_add_and_remove(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    cursor = conn.cursor()
    cursor.execute('INSERT INTO locations (name) VALUES (?)', ('Room A',))
    room_a_id = cursor.lastrowid
    cursor.execute('INSERT INTO locations (name) VALUES (?)', ('Room B',))
    room_b_id = cursor.lastrowid

    student_rows = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM students WHERE name IN (?, ?)',
            ('Student 1', 'Student 2'),
        ).fetchall()
    ]
    assert len(student_rows) == 2
    student_lookup = {row['name']: row for row in student_rows}
    cursor.execute(
        'INSERT INTO student_locations (student_id, location_id) VALUES (?, ?)',
        (student_lookup['Student 1']['id'], room_a_id),
    )
    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    for row in student_rows:
        sid = row['id']
        data.add('student_id', str(sid))
        data.add(f'student_name_{sid}', row['name'])
        for subj_id in json.loads(row['subjects']):
            data.add(f'student_subjects_{sid}', str(subj_id))
        if row['active']:
            data.add(f'student_active_{sid}', '1')
    data.setlist(f"student_locs_{student_lookup['Student 1']['id']}", [str(room_a_id)])
    batch_ids = [str(row['id']) for row in student_rows]
    data.setlist('batch_students', batch_ids)
    data.add('batch_location_action', 'add')
    data.setlist('batch_locations', [str(room_b_id)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)
    added_notice = [
        message
        for category, message in flashes
        if category == 'info' and 'Added' in message and 'Room B' in message
    ]
    assert added_notice, f'Expected added location notice, saw: {flashes}'

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    location_rows = conn.execute(
        'SELECT student_id, location_id FROM student_locations WHERE student_id IN (?, ?)',
        (student_lookup['Student 1']['id'], student_lookup['Student 2']['id']),
    ).fetchall()
    location_by_student = {}
    for row in location_rows:
        location_by_student.setdefault(row['student_id'], set()).add(row['location_id'])
    assert location_by_student.get(student_lookup['Student 1']['id'], set()) == {room_a_id, room_b_id}
    assert location_by_student.get(student_lookup['Student 2']['id'], set()) == {room_b_id}

    data_remove = _valid_config_form(config_row)
    for row in student_rows:
        sid = row['id']
        data_remove.add('student_id', str(sid))
        data_remove.add(f'student_name_{sid}', row['name'])
        for subj_id in json.loads(row['subjects']):
            data_remove.add(f'student_subjects_{sid}', str(subj_id))
        if row['active']:
            data_remove.add(f'student_active_{sid}', '1')
        current_locations = sorted(location_by_student.get(sid, set()))
        if current_locations:
            data_remove.setlist(
                f'student_locs_{sid}',
                [str(loc_id) for loc_id in current_locations],
            )
    data_remove.setlist('batch_students', [str(student_lookup['Student 1']['id'])])
    data_remove.add('batch_location_action', 'remove')
    data_remove.setlist('batch_locations', [str(room_b_id)])

    with app.app.test_request_context('/config', method='POST', data=data_remove):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)
    removed_notice = [
        message
        for category, message in flashes
        if category == 'info' and 'Removed' in message and 'Room B' in message
    ]
    assert removed_notice, f'Expected removed location notice, saw: {flashes}'

    updated_rows = conn.execute(
        'SELECT student_id, location_id FROM student_locations WHERE student_id IN (?, ?)',
        (student_lookup['Student 1']['id'], student_lookup['Student 2']['id']),
    ).fetchall()
    updated_locations = {}
    for row in updated_rows:
        updated_locations.setdefault(row['student_id'], set()).add(row['location_id'])
    assert updated_locations.get(student_lookup['Student 1']['id'], set()) == {room_a_id}
    assert updated_locations.get(student_lookup['Student 2']['id'], set()) == {room_b_id}
    conn.close()


def test_batch_active_toggle(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    cursor = conn.cursor()
    student_rows = [
        dict(row)
        for row in cursor.execute(
            'SELECT * FROM students WHERE name IN (?, ?)',
            ('Student 1', 'Student 2'),
        ).fetchall()
    ]
    assert len(student_rows) == 2
    conn.close()

    def _build_student_payload(students):
        data = _valid_config_form(config_row)
        for row in students:
            sid = row['id']
            data.add('student_id', str(sid))
            data.add(f'student_name_{sid}', row['name'])
            for subj_id in json.loads(row['subjects']):
                data.add(f'student_subjects_{sid}', str(subj_id))
            if row['active']:
                data.add(f'student_active_{sid}', '1')
        return data

    student_ids = [row['id'] for row in student_rows]
    deactivate_data = _build_student_payload(student_rows)
    deactivate_data.setlist('batch_students', [str(sid) for sid in student_ids])
    deactivate_data.add('batch_active_action', 'deactivate')

    with app.app.test_request_context('/config', method='POST', data=deactivate_data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    inactive_rows = conn.execute(
        'SELECT id, active FROM students WHERE id IN (?, ?)',
        (student_ids[0], student_ids[1]),
    ).fetchall()
    assert all(row['active'] == 0 for row in inactive_rows)

    refreshed_rows = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM students WHERE id IN (?, ?)',
            (student_ids[0], student_ids[1]),
        ).fetchall()
    ]
    conn.close()

    activate_data = _build_student_payload(refreshed_rows)
    activate_data.setlist('batch_students', [str(sid) for sid in student_ids])
    activate_data.add('batch_active_action', 'activate')

    with app.app.test_request_context('/config', method='POST', data=activate_data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    active_rows = conn.execute(
        'SELECT id, active FROM students WHERE id IN (?, ?)',
        (student_ids[0], student_ids[1]),
    ).fetchall()
    conn.close()

    assert all(row['active'] == 1 for row in active_rows)


def test_batch_teacher_subject_add(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_rows = conn.execute('SELECT id, name FROM subjects').fetchall()
    subject_lookup = {row['name']: row['id'] for row in subject_rows}
    required_subjects = {'Math', 'Science', 'English'}
    missing = required_subjects - subject_lookup.keys()
    assert not missing, f'Missing expected subjects: {missing}'

    teacher_specs = [
        ('Batch Teacher 1', ['Math'], 1),
        ('Batch Teacher 2', ['Science'], 1),
        ('Batch Teacher 3', ['Math'], 1),
    ]
    cursor = conn.cursor()
    for name, subject_names, needs_lessons in teacher_specs:
        subject_ids = [subject_lookup[sub] for sub in subject_names]
        cursor.execute(
            'INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) VALUES (?, ?, ?, ?, ?)',
            (name, json.dumps(subject_ids), None, None, needs_lessons),
        )
    conn.commit()

    teacher_rows = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM teachers WHERE name IN (?, ?, ?)',
            tuple(spec[0] for spec in teacher_specs),
        ).fetchall()
    ]
    original_subjects = {
        row['id']: set(json.loads(row['subjects']))
        for row in teacher_rows
    }
    conn.close()

    english_id = subject_lookup['English']
    selected_ids = [teacher_rows[0]['id'], teacher_rows[1]['id']]

    data = _teachers_form(config_row, teacher_rows)
    data.setlist('batch_teachers', [str(tid) for tid in selected_ids])
    data.add('batch_teacher_subject_action', 'add')
    data.setlist('batch_teacher_subjects', [str(english_id)])
    data.add('batch_teacher_need_action', 'no-change')

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_rows = conn.execute(
        'SELECT id, subjects FROM teachers WHERE id IN (?, ?, ?)',
        (teacher_rows[0]['id'], teacher_rows[1]['id'], teacher_rows[2]['id']),
    ).fetchall()
    conn.close()

    updated_subjects = {
        row['id']: set(json.loads(row['subjects']))
        for row in updated_rows
    }

    for tid in selected_ids:
        assert updated_subjects[tid] == original_subjects[tid] | {english_id}
    untouched_id = teacher_rows[2]['id']
    assert updated_subjects[untouched_id] == original_subjects[untouched_id]


def test_batch_teacher_subject_remove(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_rows = conn.execute('SELECT id, name FROM subjects').fetchall()
    subject_lookup = {row['name']: row['id'] for row in subject_rows}
    required_subjects = {'Math', 'Science', 'English'}
    missing = required_subjects - subject_lookup.keys()
    assert not missing, f'Missing expected subjects: {missing}'

    teacher_specs = [
        ('Remove Teacher 1', ['Math', 'Science'], 1),
        ('Remove Teacher 2', ['Science', 'English'], 1),
        ('Remove Teacher 3', ['Math'], 1),
    ]
    cursor = conn.cursor()
    for name, subject_names, needs_lessons in teacher_specs:
        subject_ids = [subject_lookup[sub] for sub in subject_names]
        cursor.execute(
            'INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) VALUES (?, ?, ?, ?, ?)',
            (name, json.dumps(subject_ids), None, None, needs_lessons),
        )
    conn.commit()

    teacher_rows = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM teachers WHERE name IN (?, ?, ?)',
            tuple(spec[0] for spec in teacher_specs),
        ).fetchall()
    ]
    original_subjects = {
        row['id']: set(json.loads(row['subjects']))
        for row in teacher_rows
    }
    conn.close()

    science_id = subject_lookup['Science']
    selected_ids = [teacher_rows[0]['id'], teacher_rows[1]['id']]

    data = _teachers_form(config_row, teacher_rows)
    data.setlist('batch_teachers', [str(tid) for tid in selected_ids])
    data.add('batch_teacher_subject_action', 'remove')
    data.setlist('batch_teacher_subjects', [str(science_id)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated_rows = conn.execute(
        'SELECT id, subjects FROM teachers WHERE id IN (?, ?, ?)',
        (teacher_rows[0]['id'], teacher_rows[1]['id'], teacher_rows[2]['id']),
    ).fetchall()
    conn.close()

    updated_subjects = {
        row['id']: set(json.loads(row['subjects']))
        for row in updated_rows
    }

    for tid in selected_ids:
        expected = original_subjects[tid] - {science_id}
        assert updated_subjects[tid] == expected
    untouched_id = teacher_rows[2]['id']
    assert updated_subjects[untouched_id] == original_subjects[untouched_id]


def test_batch_teacher_need_toggle(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_rows = conn.execute('SELECT id, name FROM subjects').fetchall()
    subject_lookup = {row['name']: row['id'] for row in subject_rows}
    assert 'Math' in subject_lookup, 'Expected Math subject to be present'

    teacher_specs = [
        ('Toggle Teacher 1', ['Math'], 1),
        ('Toggle Teacher 2', ['Math'], 1),
        ('Toggle Teacher 3', ['Math'], 0),
    ]
    cursor = conn.cursor()
    for name, subject_names, needs_lessons in teacher_specs:
        subject_ids = [subject_lookup[sub] for sub in subject_names]
        cursor.execute(
            'INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) VALUES (?, ?, ?, ?, ?)',
            (name, json.dumps(subject_ids), None, None, needs_lessons),
        )
    conn.commit()

    teacher_rows = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM teachers WHERE name IN (?, ?, ?)',
            tuple(spec[0] for spec in teacher_specs),
        ).fetchall()
    ]
    conn.close()

    first_pass_ids = [teacher_rows[0]['id'], teacher_rows[1]['id']]
    data = _teachers_form(config_row, teacher_rows)
    data.setlist('batch_teachers', [str(tid) for tid in first_pass_ids])
    data.add('batch_teacher_need_action', 'deactivate')

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    status_after_first = {
        row['id']: row['needs_lessons']
        for row in conn.execute(
            'SELECT id, needs_lessons FROM teachers WHERE id IN (?, ?, ?)',
            (teacher_rows[0]['id'], teacher_rows[1]['id'], teacher_rows[2]['id']),
        ).fetchall()
    }

    assert status_after_first[teacher_rows[0]['id']] == 0
    assert status_after_first[teacher_rows[1]['id']] == 0
    assert status_after_first[teacher_rows[2]['id']] == 0

    refreshed_teachers = [
        dict(row)
        for row in conn.execute(
            'SELECT * FROM teachers WHERE id IN (?, ?, ?)',
            (teacher_rows[0]['id'], teacher_rows[1]['id'], teacher_rows[2]['id']),
        ).fetchall()
    ]
    conn.close()

    config_row = _config_row(app.DB_PATH)
    second_pass_ids = [teacher_rows[1]['id'], teacher_rows[2]['id']]
    data_activate = _teachers_form(config_row, refreshed_teachers)
    data_activate.setlist('batch_teachers', [str(tid) for tid in second_pass_ids])
    data_activate.add('batch_teacher_need_action', 'activate')

    with app.app.test_request_context('/config', method='POST', data=data_activate):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    final_status = {
        row['id']: row['needs_lessons']
        for row in conn.execute(
            'SELECT id, needs_lessons FROM teachers WHERE id IN (?, ?, ?)',
            (teacher_rows[0]['id'], teacher_rows[1]['id'], teacher_rows[2]['id']),
        ).fetchall()
    }
    conn.close()

    assert final_status[teacher_rows[0]['id']] == 0
    assert final_status[teacher_rows[1]['id']] == 1
    assert final_status[teacher_rows[2]['id']] == 1


def test_followup_config_auto_removes_empty_group(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    student_rows = conn.execute(
        'SELECT id, name FROM students WHERE name IN (?, ?)',
        ('Student 1', 'Student 2'),
    ).fetchall()
    assert len(student_rows) == 2

    group_name = 'History Club'
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO groups (name, subjects) VALUES (?, ?)',
        (group_name, json.dumps([])),
    )
    group_id = cursor.lastrowid
    for row in student_rows:
        cursor.execute(
            'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
            (group_id, row['id']),
        )
    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    data.add('group_id', str(group_id))
    data.add(f'group_name_{group_id}', group_name)
    data.setlist(
        f'group_members_{group_id}',
        [str(row['id']) for row in student_rows],
    )

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert all(category != 'error' for category, _ in flashes)
    auto_delete_notice = [
        message
        for category, message in flashes
        if category == 'info'
        and 'Auto-removed' in message
        and group_name in message
    ]
    assert auto_delete_notice, f'Expected auto-removal notice, saw: {flashes}'

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    assert (
        conn.execute('SELECT 1 FROM groups WHERE id=?', (group_id,)).fetchone()
        is None
    )
    assert (
        conn.execute('SELECT 1 FROM group_members WHERE group_id=?', (group_id,)).fetchone()
        is None
    )
    assert (
        conn.execute('SELECT 1 FROM group_locations WHERE group_id=?', (group_id,)).fetchone()
        is None
    )
    conn.close()


def test_warn_when_creating_group_with_needs_lessons_disabled_teacher(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert subject_row is not None

    teacher_row = conn.execute(
        'SELECT * FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    member_rows = conn.execute(
        'SELECT id, name FROM students WHERE name IN (?, ?)',
        ('Student 2', 'Student 4'),
    ).fetchall()
    member_ids = [row['id'] for row in member_rows]
    assert member_ids, 'Expected at least one student requiring Science'

    conn.close()

    disable_data = _teacher_edit_form(config_row, teacher_row)
    disable_data.pop(f'teacher_need_lessons_{teacher_row["id"]}', None)

    with app.app.test_request_context('/config', method='POST', data=disable_data):
        disable_response = app.config()
        disable_flashes = get_flashed_messages(with_categories=True)

    assert disable_response.status_code == 302
    student_warning = (
        'warning',
        f'No teacher scheduled for {subject_row["name"]} for student Student 2; the solver will skip this subject.',
    )
    assert student_warning in disable_flashes

    updated_config = _config_row(app.DB_PATH)

    create_data = _valid_config_form(updated_config)
    group_name = 'Science Warning Group'
    create_data.add('new_group_name', group_name)
    create_data.setlist('new_group_subjects', [str(subject_row['id'])])
    create_data.setlist('new_group_members', [str(sid) for sid in member_ids])

    with app.app.test_request_context('/config', method='POST', data=create_data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected_group_warning = (
        'warning',
        f'No teacher scheduled for {subject_row["name"]} in group {group_name}; the solver will skip this subject.',
    )
    assert expected_group_warning in flashes
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    persisted_group = conn.execute(
        'SELECT name FROM groups WHERE name=?',
        (group_name,),
    ).fetchone()
    conn.close()

    assert persisted_group is not None


def test_group_validation_warns_when_teacher_blocked_for_new_group(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert subject_row is not None

    teacher_row = conn.execute(
        'SELECT id FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    member_rows = conn.execute(
        'SELECT id FROM students WHERE name IN (?, ?)',
        ('Student 2', 'Student 4'),
    ).fetchall()
    member_ids = [row['id'] for row in member_rows]
    assert member_ids, 'Expected at least one student requiring Science'

    groups_before = conn.execute('SELECT COUNT(*) FROM groups').fetchone()[0]

    for sid in member_ids:
        conn.execute(
            'INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
            (sid, teacher_row['id']),
        )

    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    group_name = 'Science Blocked Group'
    data.add('new_group_name', group_name)
    data.setlist('new_group_subjects', [str(subject_row['id'])])
    data.setlist('new_group_members', [str(sid) for sid in member_ids])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    student_warning = (
        'warning',
        f'No teacher available for {subject_row["name"]} for student Student 2; the solver will skip this subject.',
    )
    assert student_warning in flashes
    group_warning = (
        'warning',
        f'No teacher available for {subject_row["name"]} in group {group_name}; the solver will skip this subject.',
    )
    assert group_warning in flashes
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    groups_after = conn.execute('SELECT COUNT(*) FROM groups').fetchone()[0]
    persisted_group = conn.execute(
        'SELECT name FROM groups WHERE name=?',
        (group_name,),
    ).fetchone()
    conn.close()

    assert groups_after == groups_before + 1
    assert persisted_group is not None


def test_group_validation_warns_when_teacher_blocked_for_existing_group(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    subject_row = conn.execute(
        'SELECT id, name FROM subjects WHERE name=?',
        ('Science',),
    ).fetchone()
    assert subject_row is not None

    teacher_row = conn.execute(
        'SELECT id FROM teachers WHERE name=?',
        ('Teacher B',),
    ).fetchone()
    assert teacher_row is not None

    member_rows = conn.execute(
        'SELECT id, name FROM students WHERE name IN (?, ?)',
        ('Student 2', 'Student 4'),
    ).fetchall()
    member_ids = [row['id'] for row in member_rows]
    assert member_ids, 'Expected at least one student requiring Science'

    group_name = 'Science Blocked Existing'
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO groups (name, subjects) VALUES (?, ?)',
        (group_name, json.dumps([subject_row['id']])),
    )
    group_id = cursor.lastrowid
    for sid in member_ids:
        cursor.execute(
            'INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
            (group_id, sid),
        )
    conn.commit()

    for sid in member_ids:
        conn.execute(
            'INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
            (sid, teacher_row['id']),
        )

    conn.commit()
    conn.close()

    data = _valid_config_form(config_row)
    new_name = 'Science Blocked Existing Updated'
    data.add('group_id', str(group_id))
    data.add(f'group_name_{group_id}', new_name)
    data.setlist(f'group_subjects_{group_id}', [str(subject_row['id'])])
    data.setlist(f'group_members_{group_id}', [str(sid) for sid in member_ids])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    for member in member_rows:
        expected_student_warning = (
            'warning',
            f'No teacher available for {subject_row["name"]} for student {member["name"]}; the solver will skip this subject.',
        )
        assert expected_student_warning in flashes
    group_warning = (
        'warning',
        f'No teacher available for {subject_row["name"]} in group {new_name}; the solver will skip this subject.',
    )
    assert group_warning in flashes
    assert all(category != 'error' for category, _ in flashes)

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    persisted_group = conn.execute(
        'SELECT name FROM groups WHERE id=?',
        (group_id,),
    ).fetchone()
    conn.close()

    assert persisted_group is not None
    assert persisted_group['name'] == new_name


def test_block_teacher_after_deleting_fixed_assignment(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)

    teacher_row = conn.execute(
        "SELECT id FROM teachers WHERE id=1",
    ).fetchone()
    assert teacher_row is not None

    student_row = conn.execute(
        "SELECT * FROM students WHERE id=1",
    ).fetchone()
    assert student_row is not None

    student_subjects = json.loads(student_row["subjects"])
    assert student_subjects, 'Student should require at least one subject'

    conn.execute(
        "INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) VALUES (?, ?, ?, ?, ?)",
        ("Backup Teacher", json.dumps(student_subjects), None, None, 1),
    )

    conn.execute(
        "INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject_id, slot)"
        " VALUES (?, ?, NULL, ?, 0)",
        (teacher_row["id"], student_row["id"], student_subjects[0]),
    )
    conn.commit()

    assignment_row = conn.execute(
        "SELECT id FROM fixed_assignments WHERE teacher_id=? AND student_id=?",
        (teacher_row["id"], student_row["id"]),
    ).fetchone()
    assert assignment_row is not None

    data = _student_edit_form(config_row, student_row)
    sid = student_row["id"]
    if student_row["min_lessons"] is not None:
        data.add(f"student_min_{sid}", str(student_row["min_lessons"]))
    if student_row["max_lessons"] is not None:
        data.add(f"student_max_{sid}", str(student_row["max_lessons"]))
    if student_row["allow_repeats"]:
        data.add(f"student_allow_repeats_{sid}", "1")
    if student_row["max_repeats"] is not None:
        data.add(f"student_max_repeats_{sid}", str(student_row["max_repeats"]))
    if student_row["allow_consecutive"]:
        data.add(f"student_allow_consecutive_{sid}", "1")
    if student_row["prefer_consecutive"]:
        data.add(f"student_prefer_consecutive_{sid}", "1")
    if student_row["allow_multi_teacher"]:
        data.add(f"student_multi_teacher_{sid}", "1")
    repeat_subjects = student_row["repeat_subjects"]
    if repeat_subjects:
        for subj_id in json.loads(repeat_subjects):
            data.add(f"student_repeat_subjects_{sid}", str(subj_id))

    data.add('allow_repeats', '1')
    data.add(f"student_block_{sid}", str(teacher_row["id"]))
    data.add("assign_id", str(assignment_row["id"]))
    data.add("assign_delete", str(assignment_row["id"]))

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Cannot block selected teacher for student') not in flashes

    remaining = conn.execute(
        "SELECT COUNT(*) FROM fixed_assignments WHERE id=?",
        (assignment_row["id"],),
    ).fetchone()[0]
    block_count = conn.execute(
        "SELECT COUNT(*) FROM student_teacher_block WHERE student_id=? AND teacher_id=?",
        (sid, teacher_row["id"]),
    ).fetchone()[0]
    conn.close()

    assert remaining == 0
    assert block_count == 1


def test_reject_student_individual_min_exceeding_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    student = conn.execute(
        'SELECT id, name, subjects, active, min_lessons, max_lessons FROM students ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _student_edit_form(config_row, student)
    data.setlist(f'student_min_{student["id"]}', [str(slots + 3)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Student minimum lessons cannot exceed slots per day for ' + student['name'] + '.'
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM students WHERE id=?',
        (student['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == student['min_lessons']
    assert updated['max_lessons'] == student['max_lessons']


def test_reject_student_individual_max_exceeding_slots(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    student = conn.execute(
        'SELECT id, name, subjects, active, min_lessons, max_lessons FROM students ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _student_edit_form(config_row, student)
    data.setlist(f'student_max_{student["id"]}', [str(slots + 5)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Student maximum lessons cannot exceed slots per day for ' + student['name'] + '.'
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM students WHERE id=?',
        (student['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == student['min_lessons']
    assert updated['max_lessons'] == student['max_lessons']


def test_reject_student_individual_min_greater_than_max(tmp_path):
    import app

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    slots = config_row['slots_per_day']

    student = conn.execute(
        'SELECT id, name, subjects, active, min_lessons, max_lessons FROM students ORDER BY id LIMIT 1'
    ).fetchone()
    conn.close()

    data = _student_edit_form(config_row, student)
    data.setlist(f'student_min_{student["id"]}', [str(slots)])
    data.setlist(f'student_max_{student["id"]}', [str(max(slots - 1, 0))])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    expected = 'Student min lessons greater than max for ' + student['name']
    assert ('error', expected) in flashes

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = conn.execute(
        'SELECT min_lessons, max_lessons FROM students WHERE id=?',
        (student['id'],),
    ).fetchone()
    conn.close()

    assert updated['min_lessons'] == student['min_lessons']
    assert updated['max_lessons'] == student['max_lessons']


def test_teacher_without_lessons_flag_is_optional(tmp_path, monkeypatch):
    import app
    from ortools.sat.python import cp_model

    conn = setup_db(tmp_path)
    config_row = _config_row(app.DB_PATH)
    teacher_row = conn.execute('SELECT * FROM teachers ORDER BY id LIMIT 1').fetchone()
    tid = teacher_row['id']
    slots = config_row['slots_per_day']

    conn.execute(
        'INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) VALUES (?, ?, ?, ?, ?)',
        ('Backup Teacher', teacher_row['subjects'], None, None, 1),
    )
    conn.commit()

    data = _teacher_edit_form(config_row, teacher_row)
    data.add('allow_repeats', '1')
    data.setlist('teacher_min_lessons', ['2'])
    data.setlist(f'teacher_min_{tid}', ['2'])
    data.pop(f'teacher_need_lessons_{tid}', None)
    data.setlist('new_unavail_teacher', [str(tid)])
    data.setlist('new_unavail_slot', [str(i) for i in range(1, slots + 1)])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert not any(category == 'error' for category, _ in flashes)

    conn.close()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    stored = conn.execute('SELECT needs_lessons, min_lessons FROM teachers WHERE id=?', (tid,)).fetchone()
    conn.close()
    assert stored['needs_lessons'] == 0
    assert stored['min_lessons'] == 2

    captured = {}

    def fake_build_model(full_students, teachers, *args, **kwargs):
        captured['teachers'] = list(teachers)
        return object(), {}, {}, None

    def fake_solve_and_print(*args, **kwargs):
        return cp_model.OPTIMAL, [], None, []

    monkeypatch.setattr(app, 'build_model', fake_build_model)
    monkeypatch.setattr(app, 'solve_and_print', fake_solve_and_print)

    with app.app.test_request_context('/generate'):
        app.generate_schedule(target_date='2024-01-02')

    assert captured['teachers']
    assert all(app._get_row_value(row, 'id') != tid for row in captured['teachers'])
