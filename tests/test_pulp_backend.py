import pytest

pulp = pytest.importorskip("pulp")

from solver import pulp_backend


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
    core = pulp_backend._extract_unsat_core(model, registry, [], 1.0)

    assert core == []
    assert len(calls) == 1
    forced_args, limit_arg = calls[0]
    assert forced_args == ()
    assert limit_arg is None or 0 < limit_arg <= 1.0
