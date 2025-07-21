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
                blocked=None):
    """Build CP-SAT model for the scheduling problem.

    When ``add_assumptions`` is ``True``, Boolean indicators are created for the
    main constraint groups (teacher availability, teacher lesson limits,
    student lesson limits and repeat restrictions). These indicators are added as
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
        blocked: optional mapping ``student_id -> set(teacher_id)`` specifying
            teachers that cannot teach the given student. When group ids are
            included in the mapping, those restrictions apply to the entire
            group.

    Returns:
        model (cp_model.CpModel): The constructed model.
        vars_ (dict): Mapping (student_id, teacher_id, subject, slot) -> BoolVar.
        assumptions (dict or None): Mapping of constraint group name to the
            assumption indicator variable when ``add_assumptions`` is True.
        group_members (dict): Optional mapping of pseudo student id to a list of
            real student ids. When provided, group lessons will be tied to all
            member students so they attend together. IDs present in this mapping
            are treated as groups and are not subject to per-student lesson
            minimum and maximum limits. Groups obey repeat and consecutive
            lesson rules in the same way as individual students.
    """
    model = cp_model.CpModel()
    group_ids = set(group_members.keys()) if group_members else set()
    vars_ = {}
    subject_weights = subject_weights or {}
    var_weights = {}
    # Map each group id to the subjects it requires and map each member
    # student to the subjects that must be taken through their group.
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
    fixed_set = {(f['student_id'], f['teacher_id'], f['subject'], f['slot'])
                 for f in fixed}

    assumptions = None
    if add_assumptions:
        assumptions = {
            'teacher_availability': model.NewBoolVar('assume_teacher_availability'),
            'teacher_limits': model.NewBoolVar('assume_teacher_limits'),
            'student_limits': model.NewBoolVar('assume_student_limits'),
            'repeat_restrictions': model.NewBoolVar('assume_repeat_restrictions'),
        }
        for var in assumptions.values():
            model.AddAssumption(var)

    # Create variables for allowed (student, teacher, subject) triples. When a
    # real student is a member of a group for a particular subject, that subject
    # is scheduled exclusively through the group so individual variables are not
    # created.
    blocked = blocked or {}
    for student in students:
        student_subs = set(json.loads(student['subjects']))
        forbidden = set(blocked.get(student['id'], []))
        for teacher in teachers:
            if teacher['id'] in forbidden:
                continue
            teacher_subs = set(json.loads(teacher['subjects']))
            common = student_subs & teacher_subs
            for subject in common:
                if (student['id'] not in group_ids and
                        subject in member_group_subjects.get(student['id'], set())):
                    continue
                for slot in range(slots):
                    key = (student['id'], teacher['id'], subject, slot)
                    if not add_assumptions and key not in fixed_set and (teacher['id'], slot) in unavailable_set:
                        continue
                    vars_[key] = model.NewBoolVar(
                        f"x_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}")
                    weight = subject_weights.get((student['id'], subject), 1)
                    if student['id'] in group_ids:
                        weight *= group_weight
                    var_weights[vars_[key]] = weight
                    if key in fixed_set:
                        model.Add(vars_[key] == 1)
                    elif add_assumptions and (teacher['id'], slot) in unavailable_set:
                        model.Add(vars_[key] == 0).OnlyEnforceIf(assumptions['teacher_availability'])

    # Teacher cannot teach more than one lesson in a slot
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

    # Student cannot attend more than one lesson in a slot. Include group lessons
    # for that student in the check so clashes are prevented.
    for student in students:
        sid = student['id']
        if sid in group_ids:
            continue
        for slot in range(slots):
            possible = [var for (s, t, subj, sl), var in vars_.items()
                        if s == sid and sl == slot]
            for (g_key, g_var) in member_to_group_vars.get(sid, []):
                if g_key[3] == slot:  # slot matches
                    possible.append(g_var)
            if possible:
                model.Add(sum(possible) <= 1)

    # Limit repeats of the same student/teacher/subject combination. Groups
    # follow the same rules as individual students, so include their variables
    # here as well.
    triple_map = {}
    for (sid, tid, subj, sl), var in vars_.items():
        triple_map.setdefault((sid, tid, subj), {})[sl] = var

    adjacency_vars = []
    repeat_limit = max_repeats if allow_repeats else 1
    for (sid, tid, subj), slot_map in triple_map.items():
        vars_list = list(slot_map.values())
        ct = model.Add(sum(vars_list) <= repeat_limit)
        if add_assumptions:
            ct.OnlyEnforceIf(assumptions['repeat_restrictions'])
        if not allow_consecutive and repeat_limit > 1:
            for s in range(slots - 1):
                if s in slot_map and s + 1 in slot_map:
                    ct2 = model.Add(slot_map[s] + slot_map[s + 1] <= 1)
                    if add_assumptions:
                        ct2.OnlyEnforceIf(assumptions['repeat_restrictions'])
        if prefer_consecutive and allow_consecutive and repeat_limit > 1:
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

    if not allow_multi_teacher:
        by_student_subject = {}
        for (sid, tid, subj, sl), var in vars_.items():
            by_student_subject.setdefault((sid, subj), []).append(var)
        for key, vlist in by_student_subject.items():
            if len(vlist) > 1:
                ct = model.Add(sum(vlist) <= 1)
                if add_assumptions:
                    ct.OnlyEnforceIf(assumptions['repeat_restrictions'])

    # Limit total lessons per teacher
    for teacher in teachers:
        t_vars = [var for (sid, tid, subj, sl), var in vars_.items()
                  if tid == teacher['id']]
        if not t_vars:
            continue
        tmin = teacher['min_lessons']
        tmax = teacher['max_lessons']
        tmin = teacher_min_lessons if tmin is None else tmin
        tmax = teacher_max_lessons if tmax is None else tmax
        ct = model.Add(sum(t_vars) >= tmin)
        if add_assumptions:
            ct.OnlyEnforceIf(assumptions['teacher_limits'])
        if tmax is not None:
            ct2 = model.Add(sum(t_vars) <= tmax)
            if add_assumptions:
                ct2.OnlyEnforceIf(assumptions['teacher_limits'])

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
                    if add_assumptions:
                        ct.OnlyEnforceIf(assumptions['student_limits'])
                total_set.update(subject_vars)
        # Group lessons should only count once toward the student's total lesson
        # limits even when they satisfy multiple subject requirements.
        for (_, g_var) in member_to_group_vars.get(sid, []):
            total_set.add(g_var)
        total = list(total_set)
        if total:
            ct_min = model.Add(sum(total) >= min_lessons)
            ct_max = model.Add(sum(total) <= max_lessons)
            if add_assumptions:
                ct_min.OnlyEnforceIf(assumptions['student_limits'])
                ct_max.OnlyEnforceIf(assumptions['student_limits'])

    # Objective: prioritize scheduling lessons, optionally preferring consecutive repeats
    weighted_sum = sum(var * var_weights.get(var, 1) for var in vars_.values())
    if prefer_consecutive and allow_consecutive and repeat_limit > 1 and adjacency_vars:
        model.Maximize(
            weighted_sum + consecutive_weight * sum(adjacency_vars)
        )
    else:
        model.Maximize(weighted_sum)

    return model, vars_, assumptions


def solve_and_print(model, vars_, assumptions=None):
    """Solve the given model and return assignments and failing assumptions."""
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assignments = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (sid, tid, subj, slot), var in vars_.items():
            if solver.BooleanValue(var):
                assignments.append((sid, tid, subj, slot))

    core = []
    if status == cp_model.INFEASIBLE and assumptions:
        indices = solver.SufficientAssumptionsForInfeasibility()
        order = list(assumptions.keys())
        for idx in indices:
            if 0 <= idx < len(order):
                core.append(order[idx])

    return status, assignments, core
