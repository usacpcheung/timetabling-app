import json

import pytest

from solver import api
from solver.api import SolverStatus


def _make_student(student_id, subjects, **extra):
    row = {"id": student_id, "subjects": json.dumps(subjects)}
    row.update(extra)
    return row


def _make_teacher(teacher_id, subjects, **extra):
    row = {
        "id": teacher_id,
        "subjects": json.dumps(subjects),
        "min_lessons": 0,
        "max_lessons": None,
    }
    row.update(extra)
    return row


def _solve_with_backend(config, backend):
    return api.solve_schedule(backend=backend, **config)


def _simple_feasible_config():
    students = [
        _make_student(1, ["Math", "Science"], name="Alice"),
        _make_student(2, ["Math"], name="Bob"),
    ]
    teachers = [
        _make_teacher(1, ["Math"], name="Ms. Smith"),
        _make_teacher(2, ["Science"], name="Mr. Lee"),
    ]
    return {
        "students": students,
        "teachers": teachers,
        "slots": 3,
        "min_lessons": 0,
        "max_lessons": 3,
        "allow_repeats": False,
        "unavailable": [],
        "fixed": [],
        "student_limits": {1: (1, 3), 2: (1, 2)},
        "locations": [],
    }


def _infeasible_unavailability_config():
    students = [_make_student(1, ["Math"], name="Charlie")]
    teachers = [_make_teacher(1, ["Math"], name="Ms. Davis")]
    unavailable = [{"teacher_id": 1, "slot": 0}]
    return {
        "students": students,
        "teachers": teachers,
        "slots": 1,
        "min_lessons": 1,
        "max_lessons": 1,
        "allow_repeats": False,
        "unavailable": unavailable,
        "fixed": [],
        "student_limits": {1: (1, 1)},
        "locations": [],
    }


@pytest.mark.parametrize(
    "config_factory",
    [
        _simple_feasible_config,
        _infeasible_unavailability_config,
    ],
)
def test_pulp_matches_ortools_status(config_factory):
    config = config_factory()
    ortools_result = _solve_with_backend(config, backend="ortools")
    pulp_result = _solve_with_backend(config, backend="pulp")

    assert pulp_result.status == ortools_result.status

    if ortools_result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
        assert len(pulp_result.assignments) == len(ortools_result.assignments)

        def summarize(assignments):
            summary = {}
            for assignment in assignments:
                key = (assignment.student_id, assignment.subject_id)
                summary[key] = summary.get(key, 0) + 1
            return summary

        assert summarize(pulp_result.assignments) == summarize(
            ortools_result.assignments
        )
    else:
        assert not pulp_result.assignments

