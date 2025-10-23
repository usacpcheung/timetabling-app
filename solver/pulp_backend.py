"""Mixed-integer linear programming backend implemented with PuLP/HiGHS."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import pulp

from .api import AssumptionInfo, Assignment, SolverResult, SolverStatus


ASSUMPTION_BONUS_BASE = 1000.0


@dataclass
class _AssumptionRecord:
    """Internal representation of an assumption indicator and its metadata."""

    info: AssumptionInfo
    indicator: pulp.LpVariable


class AssumptionRegistry:
    """Collect assumption indicators and metadata for diagnostics."""

    def __init__(self, _model: pulp.LpProblem, enabled: bool = True):
        self.enabled = enabled
        self._records: List[_AssumptionRecord] = []

    def new_literal(
        self,
        kind: str,
        label: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> Optional[pulp.LpVariable]:
        if not self.enabled:
            return None
        idx = len(self._records)
        var_name = name or f"assumption_{kind}_{idx}"
        indicator = pulp.LpVariable(
            var_name,
            lowBound=0,
            upBound=1,
            cat=pulp.LpBinary,
        )
        info = AssumptionInfo(
            kind=kind,
            label=label or var_name,
            context=context or {},
        )
        self._records.append(_AssumptionRecord(info=info, indicator=indicator))
        return indicator

    def register_literal(
        self,
        literal: pulp.LpVariable,
        kind: str,
        label: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[pulp.LpVariable]:
        if not self.enabled:
            return None
        info = AssumptionInfo(
            kind=kind,
            label=label or literal.name,
            context=context or {},
        )
        self._records.append(_AssumptionRecord(info=info, indicator=literal))
        return literal

    def info_for_index(self, index: int) -> Optional[AssumptionInfo]:
        if not self.enabled:
            return None
        if 0 <= index < len(self._records):
            return self._records[index].info
        return None

    def indicator_for_index(self, index: int) -> pulp.LpVariable:
        return self._records[index].indicator

    def indicator_vars(self) -> List[pulp.LpVariable]:
        return [record.indicator for record in self._records]

    def records(self) -> List[_AssumptionRecord]:
        return list(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def all_infos(self) -> List[AssumptionInfo]:
        return [record.info for record in self._records]


def _indicator_value(var: pulp.LpVariable) -> float:
    value = pulp.value(var)
    if value is None:
        return 0.0
    return float(value)


def _apply_assumption_constraint(
    problem: pulp.LpProblem,
    indicator: Optional[pulp.LpVariable],
    lhs: pulp.LpAffineExpression,
    sense: str,
    rhs: float,
    big_m: float,
) -> None:
    """Add ``lhs sense rhs`` to ``problem`` optionally guarded by ``indicator``."""

    if indicator is None:
        if sense == "==":
            problem += lhs == rhs
        elif sense == "<=":
            problem += lhs <= rhs
        elif sense == ">=":
            problem += lhs >= rhs
        else:  # pragma: no cover - defensive programming
            raise ValueError(f"Unknown constraint sense '{sense}'")
        return

    slack = 1 - indicator
    big_m = max(float(big_m), 0.0)
    if sense == "==":
        problem += lhs - rhs <= big_m * slack
        problem += rhs - lhs <= big_m * slack
    elif sense == "<=":
        problem += lhs <= rhs + big_m * slack
    elif sense == ">=":
        problem += lhs >= rhs - big_m * slack
    else:  # pragma: no cover - defensive programming
        raise ValueError(f"Unknown constraint sense '{sense}'")


def _make_solver(time_limit: Optional[float]) -> pulp.apis.core.LpSolver:
    solver_cmd = pulp.apis.HiGHS_CMD(msg=False, timeLimit=time_limit)
    if solver_cmd.available():
        return solver_cmd
    solver = pulp.apis.HiGHS(msg=False, timeLimit=time_limit)
    if not solver.available():
        raise RuntimeError("HiGHS solver is not available")
    return solver


@contextmanager
def _force_indicator_bounds(
    registry: AssumptionRegistry,
    indices: Sequence[int],
    value: float = 1.0,
) -> Iterator[None]:
    originals: List[Tuple[pulp.LpVariable, float, float]] = []
    for idx in indices:
        var = registry.indicator_for_index(idx)
        originals.append((var, var.lowBound, var.upBound))
        var.lowBound = value
        var.upBound = value
    try:
        yield
    finally:
        for var, low, up in originals:
            var.lowBound = low
            var.upBound = up


def _solve_with_forced(
    model: pulp.LpProblem,
    registry: AssumptionRegistry,
    forced: Sequence[int],
    time_limit: Optional[float],
) -> Tuple[str, Set[int]]:
    solver = _make_solver(time_limit)
    with _force_indicator_bounds(registry, forced, 1.0):
        model.solve(solver)
    status_str = pulp.LpStatus.get(model.status, "Undefined")
    zeros: Set[int] = set()
    for idx, record in enumerate(registry.records()):
        if _indicator_value(record.indicator) < 0.5:
            zeros.add(idx)
    return status_str, zeros


def _extract_unsat_core(
    model: pulp.LpProblem,
    registry: AssumptionRegistry,
    initial_zeros: Sequence[int],
    time_limit: Optional[float],
) -> List[AssumptionInfo]:
    forced: Set[int] = set(initial_zeros)
    if not forced:
        status_str, zeros = _solve_with_forced(model, registry, [], time_limit)
        if status_str in ("Infeasible", "Unbounded"):
            return registry.all_infos()
        forced.update(zeros)

    progress_made = True
    while forced and progress_made:
        status_str, zeros = _solve_with_forced(model, registry, sorted(forced), time_limit)
        if status_str in ("Infeasible", "Unbounded"):
            break
        new_zeros = zeros - forced
        progress_made = bool(new_zeros)
        forced.update(new_zeros)

    if not forced:
        return []

    core: Set[int] = set(sorted(forced))
    for idx in list(core):
        trial = sorted(core - {idx})
        status_str, _ = _solve_with_forced(model, registry, trial, time_limit)
        if status_str not in ("Optimal", "Feasible", "Integer Feasible"):
            # Remaining assumptions already conflict without this one.
            core.discard(idx)

    return [registry.info_for_index(i) for i in sorted(core) if registry.info_for_index(i) is not None]


def _get_optional(record: Optional[Dict[str, Any]], key: str) -> Any:
    if record is None:
        return None
    if isinstance(record, dict):
        return record.get(key)
    try:
        return record[key]
    except Exception:
        return None


def build_model(
    students: Iterable[Dict[str, Any]],
    teachers: Iterable[Dict[str, Any]],
    slots: int,
    min_lessons: int,
    max_lessons: int,
    allow_repeats: bool = False,
    max_repeats: int = 1,
    prefer_consecutive: bool = False,
    allow_consecutive: bool = True,
    consecutive_weight: float = 1,
    unavailable: Optional[Iterable[Dict[str, Any]]] = None,
    fixed: Optional[Iterable[Dict[str, Any]]] = None,
    teacher_min_lessons: int = 0,
    teacher_max_lessons: Optional[int] = None,
    add_assumptions: bool = False,
    group_members: Optional[Dict[Any, List[Any]]] = None,
    require_all_subjects: bool = True,
    subject_weights: Optional[Dict[Tuple[Any, Any], float]] = None,
    group_weight: float = 1.0,
    allow_multi_teacher: bool = True,
    balance_teacher_load: bool = False,
    balance_weight: float = 1,
    blocked: Optional[Dict[Any, Iterable[Any]]] = None,
    student_limits: Optional[Dict[Any, Tuple[int, int]]] = None,
    student_repeat: Optional[Dict[Any, Dict[str, Any]]] = None,
    student_unavailable: Optional[Dict[Any, Iterable[int]]] = None,
    student_multi_teacher: Optional[Dict[Any, bool]] = None,
    locations: Optional[Iterable[Any]] = None,
    location_restrict: Optional[Dict[Any, Iterable[Any]]] = None,
    subject_lookup: Optional[Dict[Any, Any]] = None,
    slot_labels: Optional[Dict[Any, Any]] = None,
):
    """Build a PuLP model mirroring the OR-Tools CP-SAT formulation."""

    problem = pulp.LpProblem("timetable", pulp.LpMaximize)

    group_members = group_members or {}
    group_ids = set(group_members.keys())
    subject_weights = subject_weights or {}
    blocked = blocked or {}
    student_limits = student_limits or {}
    student_repeat = student_repeat or {}
    student_unavailable = {k: set(v) for k, v in (student_unavailable or {}).items()}
    student_multi_teacher = student_multi_teacher or {}
    locations = list(locations) if locations else []
    location_restrict = location_restrict or {}
    subject_lookup = subject_lookup or {}
    slot_labels = slot_labels or {}

    unavailable = unavailable or []
    fixed = fixed or []
    unavailable_set = {(u["teacher_id"], u["slot"]) for u in unavailable}
    fixed_set = {
        (
            entry["student_id"],
            entry["teacher_id"],
            entry.get("subject_id", entry.get("subject")),
            entry["slot"],
        )
        for entry in fixed
    }

    registry = AssumptionRegistry(problem, enabled=add_assumptions)

    teacher_lookup = {t["id"]: t for t in teachers}
    student_lookup = {s["id"]: s for s in students}

    group_subjects: Dict[Any, set] = {}
    member_group_subjects: Dict[Any, set] = {}
    if group_members:
        for student in students:
            sid = student["id"]
            if sid in group_ids:
                group_subjects[sid] = set(json.loads(student["subjects"]))
        for gid, members in group_members.items():
            subjects = group_subjects.get(gid, set())
            for member in members:
                member_group_subjects.setdefault(member, set()).update(subjects)

    vars_: Dict[Tuple[Any, Any, Any, int], pulp.LpVariable] = {}
    loc_vars: Dict[Tuple[Any, Any, Any, int, Any], pulp.LpVariable] = {}
    var_weights: Dict[pulp.LpVariable, float] = {}

    for student in students:
        sid = student["id"]
        student_subjects = set(json.loads(student["subjects"]))
        forbidden_teachers = set(blocked.get(sid, []))
        student_blocked_slots = student_unavailable.get(sid, set())
        for teacher in teachers:
            tid = teacher["id"]
            teacher_subjects = set(json.loads(teacher["subjects"]))
            common_subjects = student_subjects & teacher_subjects
            for subject in common_subjects:
                if sid not in group_ids and subject in member_group_subjects.get(sid, set()):
                    continue
                for slot in range(slots):
                    if slot in student_blocked_slots:
                        continue
                    key = (sid, tid, subject, slot)
                    is_unavailable = (tid, slot) in unavailable_set
                    is_blocked = tid in forbidden_teachers
                    if (not add_assumptions and key not in fixed_set and (is_unavailable or is_blocked)):
                        continue
                    var = pulp.LpVariable(
                        f"x_s{sid}_t{tid}_sub{subject}_sl{slot}",
                        lowBound=0,
                        upBound=1,
                        cat=pulp.LpBinary,
                    )
                    vars_[key] = var
                    weight = float(subject_weights.get((sid, subject), 1))
                    if sid in group_ids:
                        weight *= group_weight
                    var_weights[var] = weight
                    if key in fixed_set:
                        indicator = registry.new_literal(
                            "fixed_assignment",
                            label=f"fixed_s{sid}_t{tid}_sub{subject}_sl{slot}",
                            context={
                                "student_id": sid,
                                "student_name": _get_optional(student, "name"),
                                "teacher_id": tid,
                                "teacher_name": _get_optional(teacher, "name"),
                                "subject": subject,
                                "subject_name": subject_lookup.get(subject),
                                "slot": slot,
                                "slot_label": slot_labels.get(slot),
                            },
                        )
                        _apply_assumption_constraint(
                            problem,
                            indicator,
                            var,
                            "==",
                            1,
                            big_m=1,
                        )
                    elif is_unavailable or is_blocked:
                        if add_assumptions:
                            reasons: List[str] = []
                            if is_unavailable:
                                reasons.append("teacher_unavailable")
                            if is_blocked:
                                reasons.append("teacher_blocked")
                            indicator = registry.new_literal(
                                "teacher_availability",
                                label=f"block_s{sid}_t{tid}_sl{slot}",
                                context={
                                    "student_id": sid,
                                    "student_name": _get_optional(student, "name"),
                                    "teacher_id": tid,
                                    "teacher_name": _get_optional(teacher, "name"),
                                    "subject": subject,
                                    "subject_name": subject_lookup.get(subject),
                                    "slot": slot,
                                    "slot_label": slot_labels.get(slot),
                                    "reasons": reasons,
                                },
                            )
                            _apply_assumption_constraint(
                                problem,
                                indicator,
                                var,
                                "==",
                                0,
                                big_m=1,
                            )
                        else:
                            problem += var == 0

    if locations:
        for (sid, tid, subject, slot), lesson_var in list(vars_.items()):
            allowed_locations = list(location_restrict.get(sid, locations))
            if allowed_locations:
                loc_vars_for_key: List[pulp.LpVariable] = []
                for loc in allowed_locations:
                    loc_var = pulp.LpVariable(
                        f"x_s{sid}_t{tid}_sub{subject}_sl{slot}_loc{loc}",
                        lowBound=0,
                        upBound=1,
                        cat=pulp.LpBinary,
                    )
                    loc_vars[(sid, tid, subject, slot, loc)] = loc_var
                    problem += loc_var <= lesson_var
                    loc_vars_for_key.append(loc_var)
                if loc_vars_for_key:
                    problem += pulp.lpSum(loc_vars_for_key) == lesson_var
            else:
                indicator = registry.new_literal(
                    "location_restriction",
                    label=f"no_location_s{sid}_t{tid}_sub{subject}_sl{slot}",
                    context={
                        "student_id": sid,
                        "student_name": _get_optional(student_lookup.get(sid), "name"),
                        "teacher_id": tid,
                        "teacher_name": _get_optional(teacher_lookup.get(tid), "name"),
                        "subject": subject,
                        "subject_name": subject_lookup.get(subject),
                        "slot": slot,
                        "slot_label": slot_labels.get(slot),
                        "allowed_locations": [],
                    },
                )
                _apply_assumption_constraint(
                    problem,
                    indicator,
                    lesson_var,
                    "==",
                    0,
                    big_m=1,
                )

        for loc in locations:
            for slot in range(slots):
                loc_candidates = [
                    loc_var
                    for (sid, tid, subject, sl, loc_id), loc_var in loc_vars.items()
                    if loc_id == loc and sl == slot
                ]
                if loc_candidates:
                    problem += pulp.lpSum(loc_candidates) <= 1

    member_to_group_vars: Dict[Any, List[Tuple[Tuple[Any, Any, Any, int], pulp.LpVariable]]] = {}
    if group_members:
        for (sid, tid, subject, slot), var in vars_.items():
            if sid in group_members:
                for member in group_members[sid]:
                    member_to_group_vars.setdefault(member, []).append(((sid, tid, subject, slot), var))
                    member_key = (member, tid, subject, slot)
                    if member_key in vars_:
                        problem += vars_[member_key] + var <= 1

    for teacher in teachers:
        tid = teacher["id"]
        for slot in range(slots):
            candidates = [
                var
                for (sid, t_id, subject, sl), var in vars_.items()
                if t_id == tid and sl == slot
            ]
            if candidates:
                indicator = registry.new_literal(
                    "teacher_availability",
                    label=f"teacher_slot_t{tid}_sl{slot}",
                    context={
                        "teacher_id": tid,
                        "teacher_name": _get_optional(teacher, "name"),
                        "slot": slot,
                        "slot_label": slot_labels.get(slot),
                        "candidate_lessons": len(candidates),
                    },
                )
                _apply_assumption_constraint(
                    problem,
                    indicator,
                    pulp.lpSum(candidates),
                    "<=",
                    1,
                    big_m=len(candidates) or 1,
                )

    for student in students:
        sid = student["id"]
        if sid in group_ids:
            continue
        blocked_slots = student_unavailable.get(sid, set())
        for slot in range(slots):
            candidates = [
                var
                for (s_id, t_id, subject, sl), var in vars_.items()
                if s_id == sid and sl == slot
            ]
            for (group_key, group_var) in member_to_group_vars.get(sid, []):
                if group_key[3] == slot:
                    candidates.append(group_var)
            if not candidates:
                continue
            if slot in blocked_slots:
                indicator = registry.new_literal(
                    "student_limits",
                    label=f"student_block_s{sid}_sl{slot}",
                    context={
                        "student_id": sid,
                        "student_name": _get_optional(student, "name"),
                        "slot": slot,
                        "candidate_lessons": len(candidates),
                        "reason": "student_unavailable",
                    },
                )
                _apply_assumption_constraint(
                    problem,
                    indicator,
                    pulp.lpSum(candidates),
                    "==",
                    0,
                    big_m=len(candidates) or 1,
                )
            else:
                indicator = registry.new_literal(
                    "student_limits",
                    label=f"student_slot_s{sid}_sl{slot}",
                    context={
                        "student_id": sid,
                        "student_name": _get_optional(student, "name"),
                        "slot": slot,
                        "candidate_lessons": len(candidates),
                    },
                )
                _apply_assumption_constraint(
                    problem,
                    indicator,
                    pulp.lpSum(candidates),
                    "<=",
                    1,
                    big_m=len(candidates) or 1,
                )

    triple_map: Dict[Tuple[Any, Any, Any], Dict[int, pulp.LpVariable]] = {}
    for (sid, tid, subject, slot), var in vars_.items():
        triple_map.setdefault((sid, tid, subject), {})[slot] = var

    adjacency_vars: List[pulp.LpVariable] = []
    for (sid, tid, subject), slot_map in triple_map.items():
        repeat_cfg = student_repeat.get(sid, {})
        allow_rep = repeat_cfg.get("allow_repeats", allow_repeats)
        max_rep = repeat_cfg.get("max_repeats", max_repeats)
        allow_consecutive_s = repeat_cfg.get("allow_consecutive", allow_consecutive)
        prefer_consecutive_s = repeat_cfg.get("prefer_consecutive", prefer_consecutive)
        repeat_subjects = repeat_cfg.get("repeat_subjects")
        repeat_limit = max_rep if allow_rep else 1
        if repeat_subjects is not None and subject not in repeat_subjects:
            repeat_limit = 1
        vars_for_combo = list(slot_map.values())
        student_info = student_lookup.get(sid)
        teacher_info = teacher_lookup.get(tid)
        indicator_total = registry.new_literal(
            "repeat_restrictions",
            label=f"repeat_total_s{sid}_t{tid}_sub{subject}",
            context={
                "student_id": sid,
                "student_name": _get_optional(student_info, "name"),
                "teacher_id": tid,
                "teacher_name": _get_optional(teacher_info, "name"),
                "subject": subject,
                "subject_name": subject_lookup.get(subject),
                "repeat_limit": repeat_limit,
            },
        )
        _apply_assumption_constraint(
            problem,
            indicator_total,
            pulp.lpSum(vars_for_combo),
            "<=",
            repeat_limit,
            big_m=len(vars_for_combo) or 1,
        )
        if not allow_consecutive_s and repeat_limit > 1:
            for slot in range(slots - 1):
                if slot in slot_map and slot + 1 in slot_map:
                    indicator_gap = registry.new_literal(
                        "repeat_restrictions",
                        label=f"repeat_gap_s{sid}_t{tid}_sub{subject}_sl{slot}",
                        context={
                            "student_id": sid,
                            "student_name": _get_optional(student_info, "name"),
                            "teacher_id": tid,
                            "teacher_name": _get_optional(teacher_info, "name"),
                            "subject": subject,
                            "subject_name": subject_lookup.get(subject),
                            "slot": slot,
                            "reason": "no_consecutive_repeats",
                        },
                    )
                    _apply_assumption_constraint(
                        problem,
                        indicator_gap,
                        slot_map[slot] + slot_map[slot + 1],
                        "<=",
                        1,
                        big_m=2,
                    )
        if prefer_consecutive_s and allow_consecutive_s and repeat_limit > 1:
            for slot in range(slots - 1):
                if slot in slot_map and slot + 1 in slot_map:
                    v1 = slot_map[slot]
                    v2 = slot_map[slot + 1]
                    adj = pulp.LpVariable(
                        f"adj_s{sid}_t{tid}_sub{subject}_sl{slot}",
                        lowBound=0,
                        upBound=1,
                        cat=pulp.LpBinary,
                    )
                    problem += adj <= v1
                    problem += adj <= v2
                    problem += adj >= v1 + v2 - 1
                    adjacency_vars.append(adj)

    if (not allow_multi_teacher) or student_multi_teacher:
        grouped: Dict[Tuple[Any, Any], Dict[Any, List[pulp.LpVariable]]] = {}
        for (sid, tid, subject, slot), var in vars_.items():
            allow_flag = student_multi_teacher.get(sid, allow_multi_teacher) if student_multi_teacher else allow_multi_teacher
            if allow_flag:
                continue
            grouped.setdefault((sid, subject), {}).setdefault(tid, []).append(var)
        for (sid, subject), by_teacher in grouped.items():
            if len(by_teacher) <= 1:
                continue
            y_vars: List[pulp.LpVariable] = []
            for tid, vars_list in by_teacher.items():
                y = pulp.LpVariable(
                    f"y_s{sid}_sub{subject}_t{tid}",
                    lowBound=0,
                    upBound=1,
                    cat=pulp.LpBinary,
                )
                for v in vars_list:
                    problem += v <= y
                problem += y <= pulp.lpSum(vars_list)
                y_vars.append(y)
            indicator_multi = registry.new_literal(
                "repeat_restrictions",
                label=f"multi_teacher_s{sid}_sub{subject}",
                context={
                    "student_id": sid,
                    "student_name": _get_optional(student_lookup.get(sid), "name"),
                    "subject": subject,
                    "subject_name": subject_lookup.get(subject),
                    "teacher_ids": list(by_teacher.keys()),
                },
            )
            _apply_assumption_constraint(
                problem,
                indicator_multi,
                pulp.lpSum(y_vars),
                "<=",
                1,
                big_m=len(y_vars) or 1,
            )

    teacher_load_vars: List[pulp.LpVariable] = []
    for teacher in teachers:
        tid = teacher["id"]
        vars_for_teacher = [
            var for (sid, t_id, subject, slot), var in vars_.items() if t_id == tid
        ]
        load = pulp.LpVariable(
            f"load_t{tid}",
            lowBound=0,
            upBound=slots,
            cat=pulp.LpInteger,
        )
        if vars_for_teacher:
            problem += load == pulp.lpSum(vars_for_teacher)
        else:
            problem += load == 0
        teacher_load_vars.append(load)
        min_required = teacher.get("min_lessons")
        max_allowed = teacher.get("max_lessons")
        min_required = teacher_min_lessons if min_required is None else min_required
        max_allowed = teacher_max_lessons if max_allowed is None else max_allowed
        indicator_min = registry.new_literal(
            "teacher_limits",
            label=f"teacher_min_t{tid}",
            context={
                "teacher_id": tid,
                "teacher_name": _get_optional(teacher, "name"),
                "min_lessons": min_required,
            },
        )
        _apply_assumption_constraint(
            problem,
            indicator_min,
            load,
            ">=",
            float(min_required),
            big_m=max(slots, int(min_required) if min_required is not None else 0),
        )
        if max_allowed is not None:
            indicator_max = registry.new_literal(
                "teacher_limits",
                label=f"teacher_max_t{tid}",
                context={
                    "teacher_id": tid,
                    "teacher_name": _get_optional(teacher, "name"),
                    "max_lessons": max_allowed,
                },
            )
            _apply_assumption_constraint(
                problem,
                indicator_max,
                load,
                "<=",
                float(max_allowed),
                big_m=max(slots, int(max_allowed)),
            )

    load_diff: Optional[pulp.LpVariable] = None
    if balance_teacher_load and teacher_load_vars:
        max_load = pulp.LpVariable(
            "max_load",
            lowBound=0,
            upBound=slots,
            cat=pulp.LpInteger,
        )
        min_load = pulp.LpVariable(
            "min_load",
            lowBound=0,
            upBound=slots,
            cat=pulp.LpInteger,
        )
        for load in teacher_load_vars:
            problem += max_load >= load
            problem += min_load <= load
        load_diff = pulp.LpVariable(
            "load_diff",
            lowBound=0,
            upBound=slots,
            cat=pulp.LpInteger,
        )
        problem += load_diff == max_load - min_load

    for student in students:
        sid = student["id"]
        if sid in group_ids:
            continue
        total_vars: List[pulp.LpVariable] = []
        subjects = json.loads(student["subjects"])
        for subject in subjects:
            subject_candidates = [
                var
                for (s_id, t_id, subj, slot), var in vars_.items()
                if s_id == sid and subj == subject
            ]
            for (group_key, group_var) in member_to_group_vars.get(sid, []):
                if group_key[2] == subject:
                    subject_candidates.append(group_var)
            if subject_candidates:
                if require_all_subjects:
                    indicator_required = registry.new_literal(
                        "student_limits",
                        label=f"student_subject_s{sid}_sub{subject}",
                        context={
                            "student_id": sid,
                            "student_name": _get_optional(student_lookup.get(sid), "name"),
                            "subject": subject,
                            "subject_name": subject_lookup.get(subject),
                            "required": True,
                            "candidate_lessons": len(subject_candidates),
                        },
                    )
                    _apply_assumption_constraint(
                        problem,
                        indicator_required,
                        pulp.lpSum(subject_candidates),
                        ">=",
                        1,
                        big_m=len(subject_candidates) or 1,
                    )
                total_vars.extend(subject_candidates)
        for (_, group_var) in member_to_group_vars.get(sid, []):
            if group_var not in total_vars:
                total_vars.append(group_var)
        if total_vars:
            min_lesson, max_lesson = student_limits.get(sid, (min_lessons, max_lessons))
            indicator_min = registry.new_literal(
                "student_limits",
                label=f"student_min_s{sid}",
                context={
                    "student_id": sid,
                    "student_name": _get_optional(student_lookup.get(sid), "name"),
                    "min_lessons": min_lesson,
                    "max_lessons": max_lesson,
                    "lesson_options": len(total_vars),
                },
            )
            _apply_assumption_constraint(
                problem,
                indicator_min,
                pulp.lpSum(total_vars),
                ">=",
                float(min_lesson),
                big_m=len(total_vars) or 1,
            )
            if max_lesson is not None:
                indicator_max = registry.new_literal(
                    "student_limits",
                    label=f"student_max_s{sid}",
                    context={
                        "student_id": sid,
                        "student_name": _get_optional(student_lookup.get(sid), "name"),
                        "min_lessons": min_lesson,
                        "max_lessons": max_lesson,
                        "lesson_options": len(total_vars),
                    },
                )
                _apply_assumption_constraint(
                    problem,
                    indicator_max,
                    pulp.lpSum(total_vars),
                    "<=",
                    float(max_lesson),
                    big_m=len(total_vars) or 1,
                )

    objective_terms = [var * var_weights[var] for var in vars_.values()]
    if adjacency_vars:
        objective_terms.append(pulp.lpSum(adjacency_vars) * float(consecutive_weight))
    if balance_teacher_load and load_diff is not None:
        objective_terms.append(-float(balance_weight) * load_diff)
    assumption_bonus_vars = registry.indicator_vars() if registry.enabled else []
    if assumption_bonus_vars:
        base_weight = sum(abs(weight) for weight in var_weights.values())
        if adjacency_vars:
            base_weight += abs(float(consecutive_weight)) * len(adjacency_vars)
        if balance_teacher_load and load_diff is not None:
            base_weight += abs(float(balance_weight)) * slots
        bonus_weight = max(ASSUMPTION_BONUS_BASE, base_weight + 1.0)
        objective_terms.append(bonus_weight * pulp.lpSum(assumption_bonus_vars))
    if objective_terms:
        problem += pulp.lpSum(objective_terms)
    else:
        problem += 0

    return problem, vars_, loc_vars, registry


_STATUS_MAP = {
    "Optimal": SolverStatus.OPTIMAL,
    "Feasible": SolverStatus.FEASIBLE,
    "Integer Feasible": SolverStatus.FEASIBLE,
    "Infeasible": SolverStatus.INFEASIBLE,
    "Unbounded": SolverStatus.MODEL_INVALID,
    "Undefined": SolverStatus.UNKNOWN,
    "Not Solved": SolverStatus.UNKNOWN,
}


def solve(
    model: pulp.LpProblem,
    vars_: Dict[Tuple[Any, Any, Any, int], pulp.LpVariable],
    loc_vars: Dict[Tuple[Any, Any, Any, int, Any], pulp.LpVariable],
    assumption_registry: Optional[AssumptionRegistry] = None,
    *,
    time_limit: Optional[float] = None,
    progress_callback: Optional[Any] = None,
) -> SolverResult:
    """Solve the PuLP model using HiGHS and return a :class:`SolverResult`."""

    solver = _make_solver(time_limit)
    model.solve(solver)
    status_str = pulp.LpStatus.get(model.status, "Undefined")
    status = _STATUS_MAP.get(status_str, SolverStatus.UNKNOWN)

    core_infos: List[AssumptionInfo] = []
    if assumption_registry and getattr(assumption_registry, "enabled", False):
        records = assumption_registry.records()
        zero_indices = [
            idx
            for idx, record in enumerate(records)
            if _indicator_value(record.indicator) < 0.5
        ]
        if status == SolverStatus.INFEASIBLE or zero_indices:
            core_infos = _extract_unsat_core(
                model,
                assumption_registry,
                zero_indices,
                time_limit,
            )
            if core_infos:
                status = SolverStatus.INFEASIBLE
                status_str = "Infeasible"

    assignments: List[Assignment] = []
    progress: List[str] = []
    if status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE) and not core_infos:
        for (sid, tid, subject, slot), var in vars_.items():
            value = pulp.value(var)
            if value is not None and value > 0.5:
                location_id = None
                for (s, t, subj, sl, loc), loc_var in loc_vars.items():
                    if s == sid and t == tid and subj == subject and sl == slot:
                        loc_value = pulp.value(loc_var)
                        if loc_value is not None and loc_value > 0.5:
                            location_id = loc
                            break
                assignments.append(Assignment(sid, tid, subject, slot, location_id))
        objective_value = pulp.value(model.objective)
        if objective_value is None:
            objective_value = 0.0
        message = f"HiGHS solution: status={status_str}, objective={objective_value:.2f}"
        progress.append(message)
        if progress_callback is not None:
            progress_callback(message)

    result = SolverResult(
        status=status,
        assignments=assignments,
        core=core_infos,
        progress=progress,
        raw_status=status_str,
    )
    return result


__all__ = [
    "AssumptionInfo",
    "AssumptionRegistry",
    "build_model",
    "solve",
]

