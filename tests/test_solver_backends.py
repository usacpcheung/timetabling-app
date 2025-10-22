"""Tests for the backend selection helpers exposed by :mod:`solver.api`."""

from __future__ import annotations

import pytest

from solver import api, ortools_backend, pulp_backend


def test_default_backend_is_ortools():
    """The default backend should resolve to the OR-Tools implementation."""

    backend = api.get_backend()
    assert backend is ortools_backend


def test_pulp_backend_can_be_resolved():
    """The experimental PuLP backend should be registered and importable."""

    backend = api.get_backend("pulp")
    assert backend is pulp_backend


def test_unknown_backend_raises_clear_error():
    """Requesting an unsupported backend should raise a descriptive error."""

    with pytest.raises(ValueError) as excinfo:
        api.get_backend("unknown")
    message = str(excinfo.value)
    assert "unknown" in message
    assert "ortools" in message
    assert "pulp" in message


def test_solve_model_uses_requested_backend(monkeypatch):
    """``solve_model`` should dispatch to the selected backend implementation."""

    sentinel = object()

    def fake_solve(model, vars_, loc_vars, assumption_registry=None, **kwargs):  # type: ignore[override]
        assert model == "model"
        assert vars_ == {}
        assert loc_vars == {}
        assert assumption_registry is None
        assert "time_limit" in kwargs
        assert "progress_callback" in kwargs
        return sentinel

    monkeypatch.setattr(pulp_backend, "solve", fake_solve)

    result = api.solve_model("model", {}, {}, backend="pulp")
    assert result is sentinel


def test_available_backends_includes_registered_values():
    """The helper exposing available backends should list known identifiers."""

    choices = api.available_backends()
    assert "ortools" in choices
    assert "pulp" in choices
