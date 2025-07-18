from ortools.sat.python import cp_model
import json


def build_model(students, teachers, slots, min_lessons, max_lessons):
    """Build CP-SAT model for the scheduling problem.

    Args:
        students: iterable of sqlite rows or mappings with ``id`` and ``subjects`` fields.
        teachers: iterable of sqlite rows or mappings with ``id`` and ``subjects`` fields.
        slots: number of discrete time slots in the day.
        min_lessons: minimum number of lessons each student should receive.
        max_lessons: maximum number of lessons each student can receive.

    Returns:
        model (cp_model.CpModel): The constructed model.
        vars_ (dict): Mapping (student_id, teacher_id, subject, slot) -> BoolVar.
    """
    model = cp_model.CpModel()
    vars_ = {}

    # Create variables for allowed (student, teacher, subject) triples
    for student in students:
        student_subs = set(json.loads(student['subjects']))
        for teacher in teachers:
            teacher_subs = set(json.loads(teacher['subjects']))
            common = student_subs & teacher_subs
            for subject in common:
                for slot in range(slots):
                    vars_[(student['id'], teacher['id'], subject, slot)] = model.NewBoolVar(
                        f"x_s{student['id']}_t{teacher['id']}_sub{subject}_sl{slot}")

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

    # Maximize total scheduled lessons
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
