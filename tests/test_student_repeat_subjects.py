from solver.api import SolverStatus, build_model, solve_model
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
    model, vars_, loc_vars, assumption_registry = build_model(
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
    result = solve_model(model, vars_, loc_vars, assumption_registry)
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    subjects = [assignment.subject_id for assignment in result.assignments]
    assert subjects.count("English") <= 1, "English should not be repeated"

