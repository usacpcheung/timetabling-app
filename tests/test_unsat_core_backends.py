"""Regression tests covering unsat-core reporting for each solver backend."""

from __future__ import annotations

import importlib.util
import json
from typing import Dict, Iterable

import pytest

from app import summarize_unsat_core
from solver.api import SolverStatus, build_model, solve_model


ORTOOLS_AVAILABLE = importlib.util.find_spec("ortools") is not None
PULP_AVAILABLE = importlib.util.find_spec("pulp") is not None


def _make_row(identifier: int, subjects: Iterable[int], name: str | None = None) -> Dict[str, object]:
    row: Dict[str, object] = {"id": identifier, "subjects": json.dumps(list(subjects))}
    if name is not None:
        row["name"] = name
    return row


@pytest.mark.parametrize(
    "backend",
    [
        pytest.param(
            "ortools",
            marks=pytest.mark.skipif(
                not ORTOOLS_AVAILABLE,
                reason="OR-Tools backend is optional",
            ),
        ),
        pytest.param(
            "pulp",
            marks=pytest.mark.skipif(
                not PULP_AVAILABLE,
                reason="PuLP backend is optional",
            ),
        ),
    ],
)
def test_unsat_core_summary_matches_between_backends(backend: str) -> None:
    """Both backends should surface comparable unsat-core summaries."""

    students = [_make_row(1, ["Math"], name="Ada")]
    teachers = [
        {
            "id": 1,
            "subjects": json.dumps(["Math"]),
            "min_lessons": 0,
            "max_lessons": None,
            "name": "Grace",
        }
    ]
    model, vars_, loc_vars, registry = build_model(
        students,
        teachers,
        slots=1,
        min_lessons=1,
        max_lessons=1,
        unavailable=[{"teacher_id": 1, "slot": 0}],
        fixed=[],
        add_assumptions=True,
        student_limits={1: (1, 1)},
        locations=[],
        backend=backend,
    )

    result = solve_model(
        model,
        vars_,
        loc_vars,
        assumption_registry=registry,
        backend=backend,
    )

    assert result.status == SolverStatus.INFEASIBLE
    assert result.core, "Expected unsat-core entries for conflicting inputs"

    summaries = summarize_unsat_core(result.core)
    teacher_summary = next(
        (summary for summary in summaries if summary.get("kind") == "teacher_availability"),
        None,
    )
    assert teacher_summary is not None
    assert teacher_summary.get("slots") == [0]

    student_summary = next(
        (summary for summary in summaries if summary.get("kind") == "student_limits"),
        None,
    )
    assert student_summary is not None
    assert student_summary.get("student_id") == 1
    assert student_summary.get("min_lessons") == 1
