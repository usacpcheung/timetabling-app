"""Backwards compatibility layer for legacy solver imports."""

from __future__ import annotations

import warnings
from typing import Any, Callable, Optional

from solver.api import (
    Assignment,
    AssumptionInfo,
    AssumptionRegistry,
    SolverResult,
    SolverStatus,
    build_model,
    solve_model,
    solve_schedule,
)

__all__ = [
    "Assignment",
    "AssumptionInfo",
    "AssumptionRegistry",
    "SolverResult",
    "SolverStatus",
    "build_model",
    "solve_model",
    "solve_schedule",
    "solve_and_print",
]


def solve_and_print(
    model,
    vars_,
    loc_vars,
    assumption_registry: Optional[AssumptionRegistry] = None,
    time_limit: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
):
    """Legacy wrapper returning the historical tuple interface.

    The modern API lives in :mod:`solver.api`. New code should prefer
    :func:`solver.api.solve_model` or :func:`solver.api.solve_schedule` which
    return :class:`SolverResult` instances.
    """

    warnings.warn(
        "cp_sat_timetable.solve_and_print() is deprecated; use solver.api.solve_model() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    result = solve_model(
        model,
        vars_,
        loc_vars,
        assumption_registry=assumption_registry,
        time_limit=time_limit,
        progress_callback=progress_callback,
    )
    status, assignments, core, progress = result.as_legacy_tuple()
    return status, assignments, core, progress


def __getattr__(name: str) -> Any:
    if name == "solve_and_print":
        return solve_and_print
    raise AttributeError(name)
