"""Detailed helper functions for building and solving the timetable model.

This module contains a thin wrapper around OR-Tools' CP-SAT solver. The ``build_model`` function creates all variables and constraints for the scheduling problem, and ``solve_and_print`` executes the solver and extracts the results. Each decision variable is a boolean indicating whether a particular lesson occurs. Keeping this optimization code separate from the Flask application makes the model easier to understand in isolation.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ortools.sat.python import cp_model
import json


@dataclass
class AssumptionInfo:
    """Record describing an assumption literal added to the model."""

    literal: cp_model.IntVar
    kind: str
    label: str
    context: Dict[str, Any]


class AssumptionRegistry:
    """Utility to create and track assumption literals for diagnostics."""

    def __init__(self, model: cp_model.CpModel, enabled: bool = True):
        self._model = model
        self.enabled = enabled
        self._infos: List[AssumptionInfo] = []

    def new_literal(
        self,
        kind: str,
        label: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
    ) -> Optional[cp_model.IntVar]:
        """Create, register and return a fresh assumption literal."""

        if not self.enabled:
            return None
        idx = len(self._infos)
        lit_name = name or f"assumption_{kind}_{idx}"
        literal = self._model.NewBoolVar(lit_name)
        info = AssumptionInfo(
            literal=literal,
            kind=kind,
            label=label or lit_name,
            context=context or {},
        )
        self._infos.append(info)
        self._model.AddAssumption(literal)
        return literal

    def register_literal(
        self,
        literal: cp_model.IntVar,
        kind: str,
        label: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[cp_model.IntVar]:
        """Register an existing literal as an assumption and return it."""

        if not self.enabled:
            return None
        info = AssumptionInfo(
            literal=literal,
            kind=kind,
            label=label or literal.Name(),
            context=context or {},
        )
        self._infos.append(info)
        self._model.AddAssumption(literal)
        return literal

    def info_for_index(self, index: int) -> Optional[AssumptionInfo]:
        if not self.enabled:
            return None
        if 0 <= index < len(self._infos):
            return self._infos[index]
        return None

    def __len__(self) -> int:
        return len(self._infos)

    def all_infos(self) -> List[AssumptionInfo]:
        return list(self._infos)


def build_model(students, teachers, slots, min_lessons, max_lessons,
                allow_repeats=False, max_repeats=1,
                prefer_consecutive=False, allow_consecutive=True,
                consecutive_weight=1, unavailable=None, fixed=None,
                teacher_min_lessons=0, teacher_max_lessons=None,
                add_assumptions=False, group_members=None,
                require_all_subjects=True, subject_weights=None,
                group_weight=1.0, allow_multi_teacher=True,
                balance_teacher_load=False, balance_weight=1,
                blocked=None, student_limits=None,
                student_repeat=None, student_unavailable=None,
                student_multi_teacher=None,
                locations=None, location_restrict=None,
                subject_lookup=None, slot_labels=None):
    """Build CP-SAT model for the scheduling problem.

    When ``add_assumptions`` is ``True``, Boolean indicators are created for the
    main constraint groups (teacher availability and blocking rules, teacher
    lesson limits, student lesson limits and repeat restrictions). Each
    constraint receives its own assumption literal through :class:`AssumptionRegistry`
    so that unsatisfied cores can be mapped back to descriptive records when
    diagnosing infeasibility.

    Args:
        students: iterable of sqlite rows or mappings with ``id`` and ``subjects`` fields.
        teachers: iterable of sqlite rows or mappings with ``id`` and ``subjects`` fields.
        slots: number of discrete time slots in the day.
        min_lessons: minimum number of lessons each student should receive.
        max_lessons: maximum number of lessons each student can receive.
        allow_repeats: whether the same student/teacher/subject triple can occur
            in multiple slots.
        max_repeats: maximum allowed repeats when ``allow_repeats`` is True.
        prefer_consecutive: if True, repeated lessons are encouraged to appear in
            consecutive slots (only meaningful when ``allow_repeats`` is True).
        allow_consecutive: if False, repeated lessons cannot be scheduled in
            consecutive slots.
        consecutive_weight: weight applied when maximizing consecutive repeats.
        teacher_min_lessons: global minimum number of lessons per teacher.
        teacher_max_lessons: global maximum number of lessons per teacher.
        require_all_subjects: if True, each subject listed for a student must
            appear at least once in the schedule. When False the solver may
            omit some subjects if needed to satisfy other constraints.
        subject_weights: optional mapping ``(student_id, subject) -> weight``
            used to weight variables in the objective.
        group_weight: multiplier applied to the weight of variables whose
            ``student_id`` represents a group. This biases the solver toward
            scheduling group lessons. A value around ``2.0`` moderately favors
            groups without overwhelming other objectives.
        allow_multi_teacher: if False, the same student cannot take a subject
            with more than one teacher in the schedule.
        balance_teacher_load: when True, the objective penalizes large
            differences in lesson counts between teachers.
        balance_weight: weight of the load balancing penalty.
        blocked: optional mapping ``student_id -> set(teacher_id)`` specifying
            teachers that cannot teach the given student. When group ids are
            included in the mapping, those restrictions apply to the entire
            group.
        student_limits: optional mapping ``student_id -> (min, max)`` to override
            the global student lesson limits.
        student_repeat: optional mapping ``student_id -> dict`` specifying
            repeat preferences (``allow_repeats``, ``max_repeats``,
            ``allow_consecutive``, ``prefer_consecutive`` and
            ``repeat_subjects`` – a list of subjects eligible for repeats).
        student_unavailable: optional mapping ``student_id -> set(slots)`` of
            time slots where the student cannot attend lessons.
        student_multi_teacher: optional mapping ``student_id -> bool``
            overriding ``allow_multi_teacher`` for specific students.
        locations: optional list of location identifiers.
        location_restrict: mapping ``student_id -> set(location_id)`` limiting
            the locations that may be used for that student or group.
        subject_lookup: optional mapping ``subject_id -> display name`` used to
            enrich assumption contexts with subject labels.

    Returns:
        model (cp_model.CpModel): The constructed model.
        vars_ (dict): Mapping (student_id, teacher_id, subject, slot) -> BoolVar.
        loc_vars (dict): Mapping (student_id, teacher_id, subject, slot,
            location_id) -> BoolVar for location assignments.
        assumptions (AssumptionRegistry): Registry tracking assumption literals
            when ``add_assumptions`` is True. The registry will be empty when
            assumptions are disabled.
    """
    # Create the CP-SAT model object that will hold all variables and constraints
    # for OR-Tools to solve.
    model = cp_model.CpModel()

    def _get_optional(record, key):
        """Return ``record[key]`` when available, otherwise ``None``."""

        if record is None:
            return None
        if isinstance(record, dict):
            return record.get(key)
        try:
            return record[key]
        except Exception:
            return None

    # ``group_members`` allows us to treat a set of students as a single pseudo
    # student when scheduling group lessons.  These pseudo ids are assigned an
    # offset so they do not clash with real student ids.
    group_ids = set(group_members.keys()) if group_members else set()

    # ``vars_`` will hold all Boolean decision variables keyed by
    # ``(student_id, teacher_id, subject, slot)``.  ``subject_weights`` can bias
    # certain lessons in the objective and ``var_weights`` records the weight per
    # variable for easy access later.
    vars_ = {}
    loc_vars = {}
    subject_weights = subject_weights or {}
    var_weights = {}

    teacher_lookup = {t['id']: t for t in teachers}
    student_lookup = {s['id']: s for s in students}
    subject_lookup = subject_lookup or {}
    slot_labels = slot_labels or {}

    # Map each group id to the subjects it requires and map each member student
    # to the subjects that must be taken through their group.  This helps filter
    # out individual lesson variables when a subject is provided exclusively via
    # a group.
    group_subjects = {}
    member_group_subjects = {}
    if group_members:
        for s in students:
            sid = s['id']
            if sid in group_ids:
                group_subjects[sid] = set(json.loads(s['subjects']))
        for gid, members in group_members.items():
            gsubs = group_subjects.get(gid, set())
            for member in members:
                member_group_subjects.setdefault(member, set()).update(gsubs)
    unavailable = unavailable or []
    fixed = fixed or []
    unavailable_set = {(u['teacher_id'], u['slot']) for u in unavailable}
    fixed_set = {
        (
            f['student_id'],
            f['teacher_id'],
            f.get('subject_id', f.get('subject')),
            f['slot'],
        )
        for f in fixed
    }

    registry = AssumptionRegistry(model, enabled=add_assumptions)

    # Create variables for allowed (student, teacher, subject) triples. When a
    # real student is a member of a group for a particular subject, that subject
    # is scheduled exclusively through the group so individual variables are not
    # created.
    blocked = blocked or {}
    student_limits = student_limits or {}
    student_repeat = student_repeat or {}
    student_unavailable = student_unavailable or {}
    for student in students:
        student_subs = set(json.loads(student['subjects']))
        forbidden = set(blocked.get(student['id'], []))
        for teacher in teachers:
            teacher_subs = set(json.loads(teacher['subjects']))
            common = student_subs & teacher_subs
            for subject in common:
                if (student['id'] not in group_ids and
                        subject in member_group_subjects.get(student['id'], set())):
                    continue
                for slot in range(slots):
                    if slot in student_unavailable.get(student['id'], set()):
                        continue
                    key = (student['id'], teacher['id'], subject, slot)
                    is_unavailable = (teacher['id'], slot) in unavailable_set
                    is_blocked = teacher['id'] in forbidden
                    if (not add_assumptions and key not in fixed_set and
                            (is_unavailable or is_blocked)):
                        continue
                    vars_[key] = model.NewBoolVar(
                        f"x_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}")
                    weight = subject_weights.get((student['id'], subject), 1)
                    if student['id'] in group_ids:
                        weight *= group_weight
                    var_weights[vars_[key]] = weight
                    if key in fixed_set:
                        ct = model.Add(vars_[key] == 1)
                        lit = registry.new_literal(
                            'fixed_assignment',
                            label=f"fixed_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}",
                            context={
                                'student_id': student['id'],
                                'student_name': _get_optional(student, 'name'),
                                'teacher_id': teacher['id'],
                                'teacher_name': _get_optional(teacher, 'name'),
                                'subject': subject,
                                'subject_name': subject_lookup.get(subject),
                                'slot': slot,
                                'slot_label': slot_labels.get(slot),
                            },
                        )
                        if lit is not None:
                            ct.OnlyEnforceIf(lit)
                    elif is_unavailable or is_blocked:
                        if add_assumptions:
                            reasons = []
                            if is_unavailable:
                                reasons.append('teacher_unavailable')
                            if is_blocked:
                                reasons.append('teacher_blocked')
                            lit = registry.new_literal(
                                'teacher_availability',
                                label=f"block_s{student['id']}_t{teacher['id']}_sl{slot}",
                                context={
                                    'student_id': student['id'],
                                    'student_name': _get_optional(student, 'name'),
                                    'teacher_id': teacher['id'],
                                    'teacher_name': _get_optional(teacher, 'name'),
                                    'subject': subject,
                                    'subject_name': subject_lookup.get(subject),
                                    'slot': slot,
                                    'slot_label': slot_labels.get(slot),
                                    'reasons': reasons,
                                },
                            )
                            ct = model.Add(vars_[key] == 0)
                            if lit is not None:
                                ct.OnlyEnforceIf(lit)
                        else:
                            model.Add(vars_[key] == 0)

    all_locs = locations or []
    loc_restrict = location_restrict or {}
    # Only add location assignment variables/constraints when locations are configured.
    if all_locs:
        for (sid, tid, subj, sl), var in list(vars_.items()):
            allowed = loc_restrict.get(sid, all_locs)
            if allowed:
                lvars = []
                for loc in allowed:
                    lv = model.NewBoolVar(f"x_s{sid}_t{tid}_sub{subj}_sl{sl}_loc{loc}")
                    loc_vars[(sid, tid, subj, sl, loc)] = lv
                    model.Add(lv <= var)
                    lvars.append(lv)
                model.Add(sum(lvars) == var)
            else:
                # If locations are in use but none are allowed for this (student/group),
                # prevent this lesson from being scheduled.
                ct = model.Add(var == 0)
                lit = registry.new_literal(
                    'location_restriction',
                    label=f"no_location_s{sid}_t{tid}_sub{subj}_sl{sl}",
                    context={
                        'student_id': sid,
                        'student_name': _get_optional(student_lookup.get(sid), 'name'),
                        'teacher_id': tid,
                        'teacher_name': _get_optional(teacher_lookup.get(tid), 'name'),
                        'subject': subj,
                        'subject_name': subject_lookup.get(subj),
                        'slot': sl,
                        'slot_label': slot_labels.get(sl),
                        'allowed_locations': [],
                    },
                )
                if lit is not None:
                    ct.OnlyEnforceIf(lit)

        for loc in all_locs:
            for slot in range(slots):
                possible = [lv for (sid, tid, subj, sl, l), lv in loc_vars.items()
                            if l == loc and sl == slot]
                if possible:
                    model.Add(sum(possible) <= 1)

    # Constraint 1: teacher availability - a teacher cannot teach more than one lesson in the same time slot.  We scan
    # all variables for each teacher/slot pair and ensure at most one is "on".
    for teacher in teachers:
        for slot in range(slots):
            possible = [var for (sid, tid, subj, sl), var in vars_.items()
                        if tid == teacher['id'] and sl == slot]
            if possible:
                ct = model.Add(sum(possible) <= 1)
                lit = registry.new_literal(
                    'teacher_availability',
                    label=f"teacher_slot_t{teacher['id']}_sl{slot}",
                    context={
                        'teacher_id': teacher['id'],
                        'teacher_name': _get_optional(teacher, 'name'),
                        'slot': slot,
                        'slot_label': slot_labels.get(slot),
                        'candidate_lessons': len(possible),
                    },
                )
                if lit is not None:
                    ct.OnlyEnforceIf(lit)

    # Build maps relating group variables to member students
    member_to_group_vars = {}
    if group_members:
        for (sid, tid, subj, sl), var in vars_.items():
            if sid in group_members:
                for member in group_members[sid]:
                    member_to_group_vars.setdefault(member, []).append(((sid, tid, subj, sl), var))
                    # When the group variable is on, prevent member variables for the same
                    # teacher/subject/slot from activating so the teacher count is correct.
                    m_key = (member, tid, subj, sl)
                    if m_key in vars_:
                        model.Add(vars_[m_key] == 0).OnlyEnforceIf(var)

    # Constraint 2: student availability - a student cannot attend more than one lesson in a slot.  Any group lessons
    # the student belongs to are also included in the check so scheduling
    # conflicts are avoided.
    for student in students:
        sid = student['id']
        if sid in group_ids:
            continue
        blocked_slots = student_unavailable.get(sid, set())
        for slot in range(slots):
            possible = [var for (s, t, subj, sl), var in vars_.items()
                        if s == sid and sl == slot]
            for (g_key, g_var) in member_to_group_vars.get(sid, []):
                if g_key[3] == slot:  # slot matches
                    possible.append(g_var)
            if possible:
                if slot in blocked_slots:
                    ct = model.Add(sum(possible) == 0)
                    lit = registry.new_literal(
                        'student_limits',
                        label=f"student_block_s{sid}_sl{slot}",
                        context={
                            'student_id': sid,
                            'student_name': _get_optional(student, 'name'),
                            'slot': slot,
                            'candidate_lessons': len(possible),
                            'reason': 'student_unavailable',
                        },
                    )
                    if lit is not None:
                        ct.OnlyEnforceIf(lit)
                else:
                    ct = model.Add(sum(possible) <= 1)
                    lit = registry.new_literal(
                        'student_limits',
                        label=f"student_slot_s{sid}_sl{slot}",
                        context={
                            'student_id': sid,
                            'student_name': _get_optional(student, 'name'),
                            'slot': slot,
                            'candidate_lessons': len(possible),
                        },
                    )
                    if lit is not None:
                        ct.OnlyEnforceIf(lit)

    # Constraint 3: limit repeats of the same student/teacher/subject combination.  Group
    # lessons are treated the same way as individual lessons and therefore their
    # variables participate in these constraints as well.
    triple_map = {}
    for (sid, tid, subj, sl), var in vars_.items():
        triple_map.setdefault((sid, tid, subj), {})[sl] = var

    # ``adjacency_vars`` collect helper variables used when we want to encourage
    # consecutive repeat lessons.  ``repeat_limit`` is set to 1 when repeats are
    # disallowed.
    adjacency_vars = []
    for (sid, tid, subj), slot_map in triple_map.items():
        cfg = student_repeat.get(sid, {})
        allow_rep = cfg.get('allow_repeats', allow_repeats)
        max_rep = cfg.get('max_repeats', max_repeats)
        allow_consec_s = cfg.get('allow_consecutive', allow_consecutive)
        prefer_consec_s = cfg.get('prefer_consecutive', prefer_consecutive)
        repeat_subs = cfg.get('repeat_subjects')
        repeat_limit = max_rep if allow_rep else 1
        if repeat_subs is not None and subj not in repeat_subs:
            repeat_limit = 1
        vars_list = list(slot_map.values())
        student_info = student_lookup.get(sid)
        teacher_info = teacher_lookup.get(tid)
        ct = model.Add(sum(vars_list) <= repeat_limit)
        lit = registry.new_literal(
            'repeat_restrictions',
            label=f"repeat_total_s{sid}_t{tid}_sub{subj}",
            context={
                'student_id': sid,
                'student_name': _get_optional(student_info, 'name'),
                'teacher_id': tid,
                'teacher_name': _get_optional(teacher_info, 'name'),
                'subject': subj,
                'subject_name': subject_lookup.get(subj),
                'repeat_limit': repeat_limit,
            },
        )
        if lit is not None:
            ct.OnlyEnforceIf(lit)
        if not allow_consec_s and repeat_limit > 1:
            for s in range(slots - 1):
                if s in slot_map and s + 1 in slot_map:
                    ct2 = model.Add(slot_map[s] + slot_map[s + 1] <= 1)
                    lit2 = registry.new_literal(
                        'repeat_restrictions',
                        label=f"repeat_gap_s{sid}_t{tid}_sub{subj}_sl{s}",
                        context={
                            'student_id': sid,
                            'student_name': _get_optional(student_info, 'name'),
                            'teacher_id': tid,
                            'teacher_name': _get_optional(teacher_info, 'name'),
                            'subject': subj,
                            'subject_name': subject_lookup.get(subj),
                            'slot': s,
                            'reason': 'no_consecutive_repeats',
                        },
                    )
                    if lit2 is not None:
                        ct2.OnlyEnforceIf(lit2)
        if prefer_consec_s and allow_consec_s and repeat_limit > 1:
            for s in range(slots - 1):
                if s in slot_map and s + 1 in slot_map:
                    v1 = slot_map[s]
                    v2 = slot_map[s + 1]
                    adj = model.NewBoolVar(
                        f"adj_s{sid}_t{tid}_sub{subj}_sl{s}")
                    model.Add(adj <= v1)
                    model.Add(adj <= v2)
                    model.Add(adj >= v1 + v2 - 1)
                    adjacency_vars.append(adj)

    # If multi-teacher is disallowed for a student/subject, enforce that all
    # lessons for that subject use at most one teacher, while still allowing
    # repeats across different slots with that same teacher.
    if (not allow_multi_teacher) or student_multi_teacher:
        # Build mapping per (sid, subj) to variables grouped by teacher.
        by_student_subject_teacher = {}
        for (sid, tid, subj, sl), var in vars_.items():
            allow_mt = student_multi_teacher.get(sid, allow_multi_teacher) if student_multi_teacher else allow_multi_teacher
            if not allow_mt:
                by_student_subject_teacher.setdefault((sid, subj), {}).setdefault(tid, []).append(var)
        for (sid, subj), tmap in by_student_subject_teacher.items():
            if len(tmap) <= 1:
                continue
            y_vars = []
            for tid, vlist in tmap.items():
                y = model.NewBoolVar(f"y_s{sid}_sub{subj}_t{tid}")
                # If any lesson with this teacher is chosen, y must be 1.
                for v in vlist:
                    model.Add(v <= y)
                # Optional tightening: y <= sum(vlist)
                model.Add(y <= sum(vlist))
                y_vars.append(y)
            ct = model.Add(sum(y_vars) <= 1)
            lit = registry.new_literal(
                'repeat_restrictions',
                label=f"multi_teacher_s{sid}_sub{subj}",
                context={
                    'student_id': sid,
                    'student_name': _get_optional(student_lookup.get(sid), 'name'),
                    'subject': subj,
                    'subject_name': subject_lookup.get(subj),
                    'teacher_ids': list(tmap.keys()),
                },
            )
            if lit is not None:
                ct.OnlyEnforceIf(lit)

    # Limit total lessons per teacher and track each teacher's load
    teacher_load_vars = []
    for teacher in teachers:
        t_vars = [var for (sid, tid, subj, sl), var in vars_.items()
                  if tid == teacher['id']]
        load_var = model.NewIntVar(0, slots, f"load_t{teacher['id']}")
        if t_vars:
            model.Add(load_var == sum(t_vars))
        else:
            model.Add(load_var == 0)
        teacher_load_vars.append(load_var)
        tmin = teacher['min_lessons']
        tmax = teacher['max_lessons']
        tmin = teacher_min_lessons if tmin is None else tmin
        tmax = teacher_max_lessons if tmax is None else tmax
        ct = model.Add(load_var >= tmin)
        lit_min = registry.new_literal(
            'teacher_limits',
            label=f"teacher_min_t{teacher['id']}",
            context={
                'teacher_id': teacher['id'],
                'teacher_name': _get_optional(teacher, 'name'),
                'min_lessons': tmin,
            },
        )
        if lit_min is not None:
            ct.OnlyEnforceIf(lit_min)
        if tmax is not None:
            ct2 = model.Add(load_var <= tmax)
            lit_max = registry.new_literal(
                'teacher_limits',
                label=f"teacher_max_t{teacher['id']}",
                context={
                    'teacher_id': teacher['id'],
                    'teacher_name': _get_optional(teacher, 'name'),
                    'max_lessons': tmax,
                },
            )
            if lit_max is not None:
                ct2.OnlyEnforceIf(lit_max)

    # Optional objective terms to balance teacher workloads
    if balance_teacher_load and teacher_load_vars:
        max_load = model.NewIntVar(0, slots, 'max_load')
        min_load = model.NewIntVar(0, slots, 'min_load')
        model.AddMaxEquality(max_load, teacher_load_vars)
        model.AddMinEquality(min_load, teacher_load_vars)
        load_diff = model.NewIntVar(0, slots, 'load_diff')
        model.Add(load_diff == max_load - min_load)

    # Limit total lessons per student and optionally require every subject
    for student in students:
        sid = student['id']
        if sid in group_ids:
            continue
        total_set = set()
        subs = json.loads(student['subjects'])
        for subject in subs:
            subject_vars = [var for (s, t, subj, sl), var in vars_.items()
                            if s == sid and subj == subject]
            for (g_key, g_var) in member_to_group_vars.get(sid, []):
                if g_key[2] == subject:
                    subject_vars.append(g_var)
            if subject_vars:
                if require_all_subjects:
                    ct = model.Add(sum(subject_vars) >= 1)
                    lit = registry.new_literal(
                        'student_limits',
                        label=f"student_subject_s{sid}_sub{subject}",
                        context={
                            'student_id': sid,
                            'student_name': _get_optional(student_lookup.get(sid), 'name'),
                            'subject': subject,
                            'subject_name': subject_lookup.get(subject),
                            'required': True,
                            'candidate_lessons': len(subject_vars),
                        },
                    )
                    if lit is not None:
                        ct.OnlyEnforceIf(lit)
                total_set.update(subject_vars)
        # Group lessons should only count once toward the student's total lesson
        # limits even when they satisfy multiple subject requirements.
        for (_, g_var) in member_to_group_vars.get(sid, []):
            total_set.add(g_var)
        total = list(total_set)
        if total:
            min_l, max_l = student_limits.get(sid, (min_lessons, max_lessons))
            ct_min = model.Add(sum(total) >= min_l)
            lit_min = registry.new_literal(
                'student_limits',
                label=f"student_min_s{sid}",
                context={
                    'student_id': sid,
                    'student_name': _get_optional(student_lookup.get(sid), 'name'),
                    'min_lessons': min_l,
                    'max_lessons': max_l,
                    'lesson_options': len(total),
                },
            )
            if lit_min is not None:
                ct_min.OnlyEnforceIf(lit_min)
            ct_max = model.Add(sum(total) <= max_l)
            lit_max = registry.new_literal(
                'student_limits',
                label=f"student_max_s{sid}",
                context={
                    'student_id': sid,
                    'student_name': _get_optional(student_lookup.get(sid), 'name'),
                    'min_lessons': min_l,
                    'max_lessons': max_l,
                    'lesson_options': len(total),
                },
            )
            if lit_max is not None:
                ct_max.OnlyEnforceIf(lit_max)

    # Objective function: prioritize scheduling as many lessons as possible.  Additional
    # terms can encourage consecutive repeats or penalize uneven teacher loads
    # depending on the configuration options.
    # Ensure integer coefficients for CP-SAT by scaling/rounding weights.
    def _int_weight(w):
        try:
            return int(round(float(w) * 100))
        except Exception:
            return 100  # default equivalent to weight 1.0

    # Recompute integer weights for all vars to avoid float coefficients
    int_weights = {var: _int_weight(var_weights.get(var, 1)) for var in vars_.values()}
    weighted_sum = sum(var * int_weights[var] for var in vars_.values())
    objective = weighted_sum
    if adjacency_vars:
        objective += _int_weight(consecutive_weight) * sum(adjacency_vars)
    if balance_teacher_load and teacher_load_vars:
        objective -= _int_weight(balance_weight) * load_diff
    model.Maximize(objective)

    # Return the constructed model along with the decision variables and any
    # registered assumptions.
    return model, vars_, loc_vars, registry


def solve_and_print(model, vars_, loc_vars, assumption_registry=None, time_limit=None, progress_callback=None):
    """Run the OR-Tools solver and collect the results.

    Args:
        model: The ``CpModel`` instance returned by :func:`build_model`.
        vars_: Dictionary mapping tuple keys to the ``BoolVar`` decision
            variables.  The solver will decide which of these become ``True``.
        loc_vars: Mapping including location assignment variables.
        assumption_registry: Optional :class:`AssumptionRegistry` instance.  When
            provided, infeasibility cores can be mapped back to detailed
            assumption records.
        time_limit: Optional maximum solving time in seconds.
        progress_callback: Optional callable invoked with a progress message
            each time the solver finds a better solution.

    Returns:
        ``status``: Solver status value from OR-Tools.
        ``assignments``: List of tuples ``(student_id, teacher_id, subject,
        slot, location_id)`` representing the selected lessons and their
        locations.
        ``core``: If infeasible and assumptions were used, a list of
        :class:`AssumptionInfo` objects describing the unsatisfied constraints.
        ``progress``: List of textual progress messages describing each
        improved solution encountered during search.
    """

    # Instantiate the solver and let it process the model.
    solver = cp_model.CpSolver()
    if time_limit is not None:
        # ``max_time_in_seconds`` is the canonical wall time limit used by OR-Tools.
        solver.parameters.max_time_in_seconds = time_limit

    progress = []

    class _ProgressCollector(cp_model.CpSolverSolutionCallback):
        def __init__(self, limit):
            super().__init__()
            self._count = 0
            self._limit = limit

        def OnSolutionCallback(self):
            self._count += 1
            msg = f"Solution {self._count}: score {self.ObjectiveValue():.1f} (higher is better)"
            progress.append(msg)
            if progress_callback:
                progress_callback(msg)
            # ``WallTime`` is measured in seconds and allows us to stop the
            # search if the solver's internal limit fails for any reason.
            if self._limit is not None and self.WallTime() >= self._limit:
                self.StopSearch()

    callback = _ProgressCollector(time_limit)

    # Solve the model while tracking progress using the modern ``solve`` API.
    status = solver.solve(model, callback)

    assignments = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (sid, tid, subj, slot), var in vars_.items():
            if solver.BooleanValue(var):
                loc = None
                for (s, t, sub, sl, l), lv in loc_vars.items():
                    if s == sid and t == tid and sub == subj and sl == slot and solver.BooleanValue(lv):
                        loc = l
                        break
                assignments.append((sid, tid, subj, slot, loc))

    core: List[AssumptionInfo] = []
    if (status == cp_model.INFEASIBLE and assumption_registry and
            getattr(assumption_registry, 'enabled', False)):
        indices = solver.SufficientAssumptionsForInfeasibility()
        for idx in indices:
            info = assumption_registry.info_for_index(idx)
            if info is not None:
                core.append(info)

    # ``core`` gives a minimal set of unsatisfied assumption groups when no
    # feasible schedule exists.  ``assignments`` is empty in that case.
    return status, assignments, core, progress
