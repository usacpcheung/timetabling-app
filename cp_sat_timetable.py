from ortools.sat.python import cp_model
import json


def build_model(students, teachers, slots, min_lessons, max_lessons,
                allow_repeats=False, max_repeats=1,
                prefer_consecutive=False, unavailable=None, fixed=None):
    """Build CP-SAT model for the scheduling problem.

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
            consecutive slots.

    Returns:
        model (cp_model.CpModel): The constructed model.
        vars_ (dict): Mapping (student_id, teacher_id, subject, slot) -> BoolVar.
    """
    model = cp_model.CpModel()
    vars_ = {}
    unavailable = unavailable or []
    fixed = fixed or []
    unavailable_set = {(u['teacher_id'], u['slot']) for u in unavailable}
    fixed_set = {(f['student_id'], f['teacher_id'], f['subject'], f['slot'])
                 for f in fixed}

    # Create variables for allowed (student, teacher, subject) triples
    for student in students:
        student_subs = set(json.loads(student['subjects']))
        for teacher in teachers:
            teacher_subs = set(json.loads(teacher['subjects']))
            common = student_subs & teacher_subs
            for subject in common:
                for slot in range(slots):
                    key = (student['id'], teacher['id'], subject, slot)
                    if key not in fixed_set and (teacher['id'], slot) in unavailable_set:
                        continue
                    vars_[key] = model.NewBoolVar(
                        f"x_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}")
                    if key in fixed_set:
                        model.Add(vars_[key] == 1)

    # Teacher cannot teach more than one lesson in a slot
    for teacher in teachers:
        for slot in range(slots):
            possible = [var for (sid, tid, subj, sl), var in vars_.items()
                        if tid == teacher['id'] and sl == slot]
            if possible:
                model.Add(sum(possible) <= 1)

    # Student cannot attend more than one lesson in a slot
    for student in students:
        for slot in range(slots):
            possible = [var for (sid, tid, subj, sl), var in vars_.items()
                        if sid == student['id'] and sl == slot]
            if possible:
                model.Add(sum(possible) <= 1)

    # Limit repeats of the same student/teacher/subject combination
    triple_map = {}
    for (sid, tid, subj, sl), var in vars_.items():
        triple_map.setdefault((sid, tid, subj), {})[sl] = var

    adjacency_vars = []
    repeat_limit = max_repeats if allow_repeats else 1
    for (sid, tid, subj), slot_map in triple_map.items():
        vars_list = list(slot_map.values())
        model.Add(sum(vars_list) <= repeat_limit)
        if prefer_consecutive and repeat_limit > 1:
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

    # Limit total lessons per student and ensure each required subject is taken
    for student in students:
        total = []
        subs = json.loads(student['subjects'])
        for subject in subs:
            subject_vars = [var for (sid, tid, subj, sl), var in vars_.items()
                            if sid == student['id'] and subj == subject]
            if subject_vars:
                model.Add(sum(subject_vars) >= 1)
                total.extend(subject_vars)
        if total:
            model.Add(sum(total) >= min_lessons)
            model.Add(sum(total) <= max_lessons)

    # Objective: prioritize scheduling lessons, optionally preferring consecutive repeats
    if prefer_consecutive and repeat_limit > 1 and adjacency_vars:
        model.Maximize(
            sum(var * 10 for var in vars_.values()) + sum(adjacency_vars)
        )
    else:
        model.Maximize(sum(vars_.values()))

    return model, vars_


def solve_and_print(model, vars_):
    """Solve the given model and return list of assignments."""
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    assignments = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for (sid, tid, subj, slot), var in vars_.items():
            if solver.BooleanValue(var):
                assignments.append((sid, tid, subj, slot))

    return status, assignments
