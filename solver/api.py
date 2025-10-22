"""Public abstractions for interacting with timetable solvers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .ortools_backend import AssumptionInfo, AssumptionRegistry
else:
    AssumptionInfo = None  # type: ignore
    AssumptionRegistry = None  # type: ignore


class SolverStatus(str, Enum):
    """Enum representing the high-level result of a solver invocation."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"
    MODEL_INVALID = "MODEL_INVALID"


@dataclass(frozen=True)
class Assignment:
    """A single scheduled lesson returned by the solver."""

    student_id: int
    teacher_id: int
    subject_id: int
    slot: int
    location_id: Optional[int] = None

    def as_tuple(self) -> Tuple[int, int, int, int, Optional[int]]:
        """Return a tuple representation compatible with historical callers."""

        return (self.student_id, self.teacher_id, self.subject_id, self.slot, self.location_id)


@dataclass
class SolverResult:
    """Container encapsulating solver outputs and auxiliary metadata."""

    status: SolverStatus
    assignments: List[Assignment]
    core: List[Any]
    progress: List[str]
    raw_status: Any = None

    def as_legacy_tuple(self) -> Tuple[Any, List[Tuple[int, int, int, int, Optional[int]]], List[Any], List[str]]:
        """Return values matching the historical ``solve_and_print`` contract."""

        return (
            self.raw_status,
            [assignment.as_tuple() for assignment in self.assignments],
            self.core,
            self.progress,
        )


def solve_model(
    model,
    vars_,
    loc_vars,
    assumption_registry: Optional["AssumptionRegistry"] = None,
    *,
    time_limit: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> SolverResult:
    """Solve an already-built model and return a :class:`SolverResult`."""

    from . import ortools_backend

    return ortools_backend.solve_cp_sat_model(
        model,
        vars_,
        loc_vars,
        assumption_registry=assumption_registry,
        time_limit=time_limit,
        progress_callback=progress_callback,
    )


def solve_schedule(
    students,
    teachers,
    slots,
    min_lessons,
    max_lessons,
    *,
    allow_repeats: bool = False,
    max_repeats: int = 1,
    prefer_consecutive: bool = False,
    allow_consecutive: bool = True,
    consecutive_weight: float = 1,
    unavailable: Optional[Any] = None,
    fixed: Optional[Any] = None,
    teacher_min_lessons: int = 0,
    teacher_max_lessons: Optional[int] = None,
    add_assumptions: bool = False,
    group_members: Optional[Dict[Any, List[Any]]] = None,
    require_all_subjects: bool = True,
    subject_weights: Optional[Dict[Any, float]] = None,
    group_weight: float = 1.0,
    allow_multi_teacher: bool = True,
    balance_teacher_load: bool = False,
    balance_weight: float = 1,
    blocked: Optional[Dict[Any, Any]] = None,
    student_limits: Optional[Dict[Any, Any]] = None,
    student_repeat: Optional[Dict[Any, Any]] = None,
    student_unavailable: Optional[Dict[Any, Any]] = None,
    student_multi_teacher: Optional[Dict[Any, bool]] = None,
    locations: Optional[Iterable[Any]] = None,
    location_restrict: Optional[Dict[Any, Any]] = None,
    subject_lookup: Optional[Dict[Any, Any]] = None,
    slot_labels: Optional[Dict[Any, Any]] = None,
    time_limit: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> SolverResult:
    """High-level helper that builds and solves a timetable model."""

    model, vars_, loc_vars, assumption_registry = build_model(
        students,
        teachers,
        slots,
        min_lessons,
        max_lessons,
        allow_repeats=allow_repeats,
        max_repeats=max_repeats,
        prefer_consecutive=prefer_consecutive,
        allow_consecutive=allow_consecutive,
        consecutive_weight=consecutive_weight,
        unavailable=unavailable,
        fixed=fixed,
        teacher_min_lessons=teacher_min_lessons,
        teacher_max_lessons=teacher_max_lessons,
        add_assumptions=add_assumptions,
        group_members=group_members,
        require_all_subjects=require_all_subjects,
        subject_weights=subject_weights,
        group_weight=group_weight,
        allow_multi_teacher=allow_multi_teacher,
        balance_teacher_load=balance_teacher_load,
        balance_weight=balance_weight,
        blocked=blocked,
        student_limits=student_limits,
        student_repeat=student_repeat,
        student_unavailable=student_unavailable,
        student_multi_teacher=student_multi_teacher,
        locations=locations,
        location_restrict=location_restrict,
        subject_lookup=subject_lookup,
        slot_labels=slot_labels,
    )
    return solve_model(
        model,
        vars_,
        loc_vars,
        assumption_registry=assumption_registry,
        time_limit=time_limit,
        progress_callback=progress_callback,
    )


from . import ortools_backend as _backend

AssumptionInfo = _backend.AssumptionInfo  # type: ignore[assignment]
AssumptionRegistry = _backend.AssumptionRegistry  # type: ignore[assignment]
build_model = _backend.build_model


def get_assumption_registry(
    model,
    *,
    enabled: bool = True,
) -> "AssumptionRegistry":
    """Construct a new :class:`AssumptionRegistry` bound to ``model``."""

    return _backend.AssumptionRegistry(model, enabled=enabled)


__all__ = [
    "Assignment",
    "SolverResult",
    "SolverStatus",
    "solve_schedule",
    "solve_model",
    "build_model",
    "get_assumption_registry",
    "AssumptionInfo",
    "AssumptionRegistry",
]
