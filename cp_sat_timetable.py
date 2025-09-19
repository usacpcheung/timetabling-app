"""Detailed helper functions for building and solving the timetable model.

This module contains a thin wrapper around OR-Tools' CP-SAT solver. The ``build_model`` function creates all variables and constraints for the scheduling problem, and ``solve_and_print`` executes the solver and extracts the results. Each decision variable is a boolean indicating whether a particular lesson occurs. Keeping this optimization code separate from the Flask application makes the model easier to understand in isolation.
"""

from ortools.sat.python import cp_model
import json


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
                locations=None, location_restrict=None):
    """Build CP-SAT model for the scheduling problem.

    When ``add_assumptions`` is ``True``, Boolean indicators are created for the
    main constraint groups (teacher availability and blocking rules, teacher
    lesson limits, student lesson limits and repeat restrictions). These
    indicators are added as
    assumptions on the model so that unsatisfied cores can be extracted to
    diagnose infeasibility.

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

    Returns:
        model (cp_model.CpModel): The constructed model.
        vars_ (dict): Mapping (student_id, teacher_id, subject, slot) -> BoolVar.
        loc_vars (dict): Mapping (student_id, teacher_id, subject, slot,
            location_id) -> BoolVar for location assignments.
        assumptions (dict or None): When ``add_assumptions`` is True, this
            contains per-entity assumption literals under keys such as
            ``'teacher_availability'`` and an ordered ``'labels'`` list used to
            decode unsat cores.
    """
    # Create the CP-SAT model object that will hold all variables and constraints
    # for OR-Tools to solve.
    model = cp_model.CpModel()

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

    register_literal = None
    assumptions = None
    if add_assumptions:
        assumption_store = {
            'teacher_availability': {},
            'teacher_limits': {},
            'student_limits': {},
            'repeat_restrictions': {},
        }
        assumption_labels = []

        def register_literal(category, key, label):
            """Return (and create if needed) the assumption literal for ``key``."""

            cat = assumption_store[category]
            if key not in cat:
                literal = model.NewBoolVar(
                    f"assume_{category}_{len(assumption_labels)}"
                )
                cat[key] = literal
                model.AddAssumption(literal)
                assumption_labels.append(label)
            return cat[key]

        assumptions = {
            'teacher_availability': assumption_store['teacher_availability'],
            'teacher_limits': assumption_store['teacher_limits'],
            'student_limits': assumption_store['student_limits'],
            'repeat_restrictions': assumption_store['repeat_restrictions'],
            'labels': assumption_labels,
        }

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
                    if (not add_assumptions and key not in fixed_set and
                            ((teacher['id'], slot) in unavailable_set or
                             teacher['id'] in forbidden)):
                        continue
                    vars_[key] = model.NewBoolVar(
                        f"x_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}")
                    weight = subject_weights.get((student['id'], subject), 1)
                    if student['id'] in group_ids:
                        weight *= group_weight
                    var_weights[vars_[key]] = weight
                    if key in fixed_set:
                        model.Add(vars_[key] == 1)
                    elif add_assumptions and ((teacher['id'], slot) in unavailable_set or
                                             teacher['id'] in forbidden):
                        if (teacher['id'], slot) in unavailable_set:
                            literal = register_literal(
                                'teacher_availability',
                                ('unavailable', teacher['id'], slot),
                                f"teacher_availability:teacher_id={teacher['id']},slot={slot}",
                            )
                        else:
                            literal = register_literal(
                                'teacher_availability',
                                ('blocked', student['id'], teacher['id'], slot),
                                (
                                    f"teacher_availability:teacher_id={teacher['id']},"
                                    f"slot={slot},blocked_for_student={student['id']}"
                                ),
                            )
                        model.Add(vars_[key] == 0).OnlyEnforceIf(literal)

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
                model.Add(var == 0)

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
                model.Add(sum(possible) <= 1)

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
                    if add_assumptions:
                        literal = register_literal(
                            'student_limits',
                            ('unavailable_slot', sid, slot),
                            (
                                f"student_limits:student_id={sid},slot={slot},"
                                "reason=student_unavailable"
                            ),
                        )
                        ct.OnlyEnforceIf(literal)
                else:
                    model.Add(sum(possible) <= 1)

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
        repeat_literal = None
        if add_assumptions:
            repeat_literal = register_literal(
                'repeat_restrictions',
                ('repeat_limit', sid, tid, subj),
                (
                    "repeat_restrictions:"
                    f"student_id={sid},teacher_id={tid},subject={subj}"
                ),
            )
        ct = model.Add(sum(vars_list) <= repeat_limit)
        if repeat_literal is not None:
            ct.OnlyEnforceIf(repeat_literal)
        if not allow_consec_s and repeat_limit > 1:
            for s in range(slots - 1):
                if s in slot_map and s + 1 in slot_map:
                    ct2 = model.Add(slot_map[s] + slot_map[s + 1] <= 1)
                    if repeat_literal is not None:
                        ct2.OnlyEnforceIf(repeat_literal)
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
            if add_assumptions:
                literal = register_literal(
                    'repeat_restrictions',
                    ('multi_teacher', sid, subj),
                    (
                        "repeat_restrictions:"
                        f"student_id={sid},subject={subj},type=multi_teacher"
                    ),
                )
                ct.OnlyEnforceIf(literal)

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
        literal = None
        if add_assumptions:
            literal = register_literal(
                'teacher_limits',
                teacher['id'],
                f"teacher_limits:teacher_id={teacher['id']}",
            )
        ct = model.Add(load_var >= tmin)
        if literal is not None:
            ct.OnlyEnforceIf(literal)
        if tmax is not None:
            ct2 = model.Add(load_var <= tmax)
            if literal is not None:
                ct2.OnlyEnforceIf(literal)

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
                    literal = None
                    if add_assumptions:
                        literal = register_literal(
                            'student_limits',
                            ('subject_requirement', sid, subject),
                            (
                                "student_limits:"
                                f"student_id={sid},subject={subject}"
                            ),
                        )
                    ct = model.Add(sum(subject_vars) >= 1)
                    if literal is not None:
                        ct.OnlyEnforceIf(literal)
                total_set.update(subject_vars)
        # Group lessons should only count once toward the student's total lesson
        # limits even when they satisfy multiple subject requirements.
        for (_, g_var) in member_to_group_vars.get(sid, []):
            total_set.add(g_var)
        total = list(total_set)
        if total:
            min_l, max_l = student_limits.get(sid, (min_lessons, max_lessons))
            literal_total = None
            if add_assumptions:
                literal_total = register_literal(
                    'student_limits',
                    ('total', sid),
                    f"student_limits:student_id={sid},type=total",
                )
            ct_min = model.Add(sum(total) >= min_l)
            ct_max = model.Add(sum(total) <= max_l)
            if literal_total is not None:
                ct_min.OnlyEnforceIf(literal_total)
                ct_max.OnlyEnforceIf(literal_total)

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
    # assumption indicators.
    return model, vars_, loc_vars, assumptions


def solve_and_print(model, vars_, loc_vars, assumptions=None, time_limit=None, progress_callback=None):
    """Run the OR-Tools solver and collect the results.

    Args:
        model: The ``CpModel`` instance returned by :func:`build_model`.
        vars_: Dictionary mapping tuple keys to the ``BoolVar`` decision
            variables.  The solver will decide which of these become ``True``.
        loc_vars: Mapping including location assignment variables.
        assumptions: Optional dictionary of assumption indicators.  When the
            model is infeasible these help identify which group of constraints
            caused the problem.
        time_limit: Optional maximum solving time in seconds.
        progress_callback: Optional callable invoked with a progress message
            each time the solver finds a better solution.

    Returns:
        ``status``: Solver status value from OR-Tools.
        ``assignments``: List of tuples ``(student_id, teacher_id, subject,
        slot, location_id)`` representing the selected lessons and their
        locations.
        ``core``: If infeasible and assumptions were used, descriptive labels
        identifying the specific teacher/student constraints that caused the
        conflict.
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

    core = []
    if status == cp_model.INFEASIBLE and assumptions:
        indices = solver.SufficientAssumptionsForInfeasibility()
        labels = assumptions.get('labels', []) if isinstance(assumptions, dict) else []
        for idx in indices:
            if 0 <= idx < len(labels):
                core.append(labels[idx])
            else:
                core.append(f"assumption_index={idx}")

    # ``core`` gives a minimal set of unsatisfied assumption groups when no
    # feasible schedule exists.  ``assignments`` is empty in that case.
    return status, assignments, core, progress
