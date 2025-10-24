import json

import pytest

pulp = pytest.importorskip("pulp")

from solver import pulp_backend
from solver.api import SolverStatus


def test_unsat_core_respects_time_limit(monkeypatch):
    fake_time = [0.0]

    def perf_counter():
        return fake_time[0]

    monkeypatch.setattr(pulp_backend.time, "perf_counter", perf_counter)

    registry_problem = pulp.LpProblem("registry", pulp.LpMinimize)
    registry = pulp_backend.AssumptionRegistry(registry_problem, enabled=True)
    registry.new_literal("dummy")

    calls = []

    def fake_solve(model, registry_arg, forced, time_limit):
        calls.append((tuple(forced), time_limit))
        fake_time[0] = 2.0
        return "Optimal", {0}

    monkeypatch.setattr(pulp_backend, "_solve_with_forced", fake_solve)

    model = pulp.LpProblem("model", pulp.LpMinimize)
    core, timed_out = pulp_backend._extract_unsat_core(model, registry, [], 1.0)

    assert core == []
    assert timed_out is True
    assert len(calls) == 1
    forced_args, limit_arg = calls[0]
    assert forced_args == ()
    assert limit_arg is None or 0 < limit_arg <= 1.0


def test_unsat_timeout_marks_solution_infeasible():
    students = [
        {"id": 1, "name": "Alice", "subjects": json.dumps(["math"])},
    ]
    teachers = [
        {"id": 7, "name": "Bob", "subjects": json.dumps(["math"])},
    ]
    model, vars_, loc_vars, registry = pulp_backend.build_model(
        students,
        teachers,
        slots=1,
        min_lessons=1,
        max_lessons=1,
        add_assumptions=True,
        unavailable=[{"teacher_id": 7, "slot": 0}],
    )

    result = pulp_backend.solve(
        model,
        vars_,
        loc_vars,
        registry,
        time_limit=0,
    )

    assert result.status is SolverStatus.INFEASIBLE
    assert result.core


def test_time_limited_partial_solution_is_feasible(monkeypatch):
    pulp = pytest.importorskip("pulp")

    students = [
        {"id": 1, "name": "Alice", "subjects": json.dumps(["math"])},
    ]
    teachers = [
        {"id": 7, "name": "Bob", "subjects": json.dumps(["math"])},
    ]

    model, vars_, loc_vars, registry = pulp_backend.build_model(
        students,
        teachers,
        slots=1,
        min_lessons=1,
        max_lessons=1,
        add_assumptions=False,
    )

    chosen_key, chosen_var = next(iter(vars_.items()))

    def fake_make_solver(time_limit):
        class _DummySolver:
            pass

        return _DummySolver()

    def fake_solve(self, solver=None):
        not_solved = getattr(pulp, "LpStatusNotSolved", 0)
        for var in vars_.values():
            var.varValue = 0.0
        chosen_var.varValue = 1.0
        for (s, t, subj, slot, loc), loc_var in loc_vars.items():
            if (s, t, subj, slot) == chosen_key:
                loc_var.varValue = 1.0
            else:
                loc_var.varValue = 0.0
        self.status = not_solved
        return None

    monkeypatch.setattr(pulp_backend, "_make_solver", fake_make_solver)
    monkeypatch.setattr(pulp.LpProblem, "solve", fake_solve, raising=False)

    result = pulp_backend.solve(
        model,
        vars_,
        loc_vars,
        registry,
        time_limit=1e-6,
    )

    assert result.status is SolverStatus.FEASIBLE
    assert result.assignments
    assert any("time limit" in message.lower() for message in result.progress)
    assert "time limit" in result.raw_status.lower()
