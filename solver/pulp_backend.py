"""Placeholder implementation for a future PuLP-based solver backend."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def build_model(
    students: Iterable[Any],
    teachers: Iterable[Any],
    slots: int,
    min_lessons: int,
    max_lessons: int,
    **_: Dict[str, Any],
):
    """Build a PuLP model for the scheduling problem (not yet implemented).

    The PuLP backend is still experimental, so model construction currently
    raises :class:`NotImplementedError`. The signature mirrors the OR-Tools
    backend to make it easy to plug in once the implementation is ready.
    """

    raise NotImplementedError("PuLP backend model construction is not implemented yet.")


def solve(
    model: Any,
    vars_: Dict[Any, Any],
    loc_vars: Dict[Any, Any],
    assumption_registry: Optional[Any] = None,
    **_: Any,
):
    """Solve a PuLP model for the scheduling problem (not yet implemented)."""

    raise NotImplementedError("PuLP backend solving is not implemented yet.")


__all__ = ["build_model", "solve"]

