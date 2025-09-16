from ortools.sat.python import cp_model
from cp_sat_timetable import build_model, solve_and_print
import json


def make_row(id_, subjects):
    return {"id": id_, "subjects": json.dumps(subjects)}


def test_repeat_allowed_only_for_selected_subjects():
    students = [make_row(1, ["Math", "English"])]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math", "English"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 3
    student_limits = {1: (3, 3)}
    student_repeat = {
        1: {
            "allow_repeats": True,
            "max_repeats": 3,
            "repeat_subjects": ["Math"],
        }
    }
    model, vars_, loc_vars, assumptions = build_model(
        students,
        teachers,
        slots,
        min_lessons=3,
        max_lessons=3,
        allow_repeats=True,
        max_repeats=3,
        student_limits=student_limits,
        student_repeat=student_repeat,
        locations=[],
    )
    status, assignments, _, _ = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    subjects = [subj for (_, _, subj, _, _) in assignments]
    assert subjects.count("English") <= 1, "English should not be repeated"

