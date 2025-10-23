"""Public abstractions for interacting with timetable solvers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .ortools_backend import AssumptionRegistry as _OrToolsAssumptionRegistry
else:
    _OrToolsAssumptionRegistry = None  # type: ignore


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


@dataclass
class AssumptionInfo:
    """Backend-agnostic description of an assumption group.

    The solver backends populate these records to surface the logical groups of
    constraints that participated in an infeasibility.  The ``kind`` field
    provides a stable identifier used by :mod:`app.py` to summarize conflicts,
    while ``label`` and ``context`` contain human-readable metadata tailored to
    the specific constraint.
    """

    kind: str
    label: str
    context: Dict[str, Any]


_BACKEND_REGISTRY: Dict[str, str] = {}
_DEFAULT_BACKEND = "ortools"


def register_backend(identifier: str, module_path: str) -> None:
    """Register a solver backend import path under ``identifier``."""

    _BACKEND_REGISTRY[identifier.lower()] = module_path


def available_backends() -> List[str]:
    """Return the list of registered backend identifiers."""

    return sorted(_BACKEND_REGISTRY)


def _resolve_backend_name(identifier: Optional[str]) -> str:
    key = (identifier or _DEFAULT_BACKEND).lower()
    if key not in _BACKEND_REGISTRY:
        available = ", ".join(available_backends()) or "none"
        name = identifier if identifier is not None else _DEFAULT_BACKEND
        raise ValueError(f"Unknown solver backend '{name}'. Available options: {available}.")
    return key


def get_backend(identifier: Optional[str] = None) -> ModuleType:
    """Return the module implementing the requested solver backend."""

    key = _resolve_backend_name(identifier)
    return import_module(_BACKEND_REGISTRY[key])


def solve_model(
    model,
    vars_,
    loc_vars,
    assumption_registry: Optional["AssumptionRegistry"] = None,
    *,
    backend: Optional[str] = None,
    time_limit: Optional[float] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> SolverResult:
    """Solve an already-built model and return a :class:`SolverResult`."""

    backend_module = get_backend(backend)
    solver = getattr(backend_module, "solve", None)
    if solver is None:
        solver = getattr(backend_module, "solve_cp_sat_model", None)
    if solver is None:
        available = backend or _DEFAULT_BACKEND
        raise ValueError(
            f"Backend '{available}' does not expose a solve() function."
        )

    return solver(
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
    backend: Optional[str] = None,
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
        backend=backend,
    )
    return solve_model(
        model,
        vars_,
        loc_vars,
        assumption_registry=assumption_registry,
        backend=backend,
        time_limit=time_limit,
        progress_callback=progress_callback,
    )


def build_model(
    students,
    teachers,
    slots,
    min_lessons,
    max_lessons,
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
    *,
    backend: Optional[str] = None,
):
    """Build a solver-specific model for the scheduling problem."""

    backend_module = get_backend(backend)
    builder = getattr(backend_module, "build_model", None)
    if builder is None:
        name = backend if backend is not None else _DEFAULT_BACKEND
        raise ValueError(f"Backend '{name}' does not expose a build_model() function.")

    return builder(
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


def get_assumption_registry(
    model,
    *,
    enabled: bool = True,
    backend: Optional[str] = None,
) -> "AssumptionRegistry":
    """Construct a new :class:`AssumptionRegistry` bound to ``model``."""

    backend_module = get_backend(backend)
    registry_cls = getattr(backend_module, "AssumptionRegistry", None)
    if registry_cls is None:
        name = backend if backend is not None else _DEFAULT_BACKEND
        raise ValueError(
            f"Backend '{name}' does not provide assumption registry support."
        )
    return registry_cls(model, enabled=enabled)


register_backend("ortools", "solver.ortools_backend")
register_backend("pulp", "solver.pulp_backend")

_default_backend_module = get_backend()
AssumptionRegistry = getattr(
    _default_backend_module,
    "AssumptionRegistry",
    _OrToolsAssumptionRegistry,
)  # type: ignore[assignment]


__all__ = [
    "Assignment",
    "SolverResult",
    "SolverStatus",
    "available_backends",
    "register_backend",
    "get_backend",
    "solve_schedule",
    "solve_model",
    "build_model",
    "get_assumption_registry",
    "AssumptionInfo",
    "AssumptionRegistry",
]
