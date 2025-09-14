import os
import sys
import json

# Ensure the application package can be imported when tests are executed
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cp_sat_timetable import build_model, solve_and_print


def test_fixed_assignment_handles_subject_id():
    """build_model should accept fixed assignments using subject_id."""
    students = [{'id': 1, 'subjects': json.dumps([1])}]
    teachers = [{'id': 1, 'subjects': json.dumps([1]), 'min_lessons': None, 'max_lessons': None}]
    fixed = [{'student_id': 1, 'teacher_id': 1, 'subject_id': 1, 'slot': 0}]

    model, vars_, loc_vars, _ = build_model(
        students, teachers, slots=1, min_lessons=0, max_lessons=1, fixed=fixed
    )
    status, assignments, _, progress = solve_and_print(model, vars_, loc_vars)

    # The fixed assignment should appear in the solver output
    assert (1, 1, 1, 0, None) in assignments
    assert isinstance(progress, list)
