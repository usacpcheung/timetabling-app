# -*- coding: utf-8 -*-
"""Solve a basic school timetabling problem with CP-SAT.

This standalone script constructs a weekly timetable where teachers teach
subjects to students without overlaps. It illustrates how to model the
problem described in the instructions using Google OR-Tools.

The script first asks the user to input teachers and students with their
subjects. It then builds a constraint programming model and prints any
feasible timetable found.
"""

from __future__ import annotations

from typing import Dict, List

from ortools.sat.python import cp_model

# Constants defining the planning horizon
DAYS = 5
SLOTS_PER_DAY = 8


def get_data_from_user() -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Ask the user for teacher and student information.

    Returns
    -------
    tuple
        Two dictionaries: teachers and students.
    """
    teachers: Dict[str, List[str]] = {}
    print("Enter teachers (blank name to finish)")
    while True:
        name = input("Teacher name: ").strip()
        if not name:
            break
        subjects = [s.strip() for s in input("Subjects (comma separated): ").split(',') if s.strip()]
        teachers[name] = subjects

    students: Dict[str, List[str]] = {}
    print("\nEnter students (blank name to finish)")
    while True:
        name = input("Student name: ").strip()
        if not name:
            break
        subjects = [s.strip() for s in input("Required subjects (comma separated): ").split(',') if s.strip()]
        students[name] = subjects

    return teachers, students


def build_model(teachers: Dict[str, List[str]], students: Dict[str, List[str]]) -> tuple[cp_model.CpModel, dict, dict]:
    """Create the CP-SAT model using boolean variables.

    Parameters
    ----------
    teachers : dict
        Mapping teacher names to the subjects they can teach.
    students : dict
        Mapping student names to subjects they must attend.

    Returns
    -------
    model : cp_model.CpModel
        The populated model ready to be solved.
    x, y : dict
        Dictionaries of the created boolean decision variables.
    """
    model = cp_model.CpModel()
    x = {}
    for t, subj_list in teachers.items():
        for d in range(DAYS):
            for p in range(SLOTS_PER_DAY):
                for s in subj_list:
                    x[(t, d, p, s)] = model.NewBoolVar(f"x_{t}_{d}_{p}_{s}")

    y = {}
    for u, subj_list in students.items():
        for d in range(DAYS):
            for p in range(SLOTS_PER_DAY):
                for s in subj_list:
                    y[(u, d, p, s)] = model.NewBoolVar(f"y_{u}_{d}_{p}_{s}")

    # Teacher no-overlap: one subject per slot
    for t, subj_list in teachers.items():
        for d in range(DAYS):
            for p in range(SLOTS_PER_DAY):
                model.Add(sum(x[(t, d, p, s)] for s in subj_list) <= 1)

    # Daily load: at most SLOTS_PER_DAY lessons per day for each teacher
    for t, subj_list in teachers.items():
        for d in range(DAYS):
            model.Add(
                sum(x[(t, d, p, s)] for p in range(SLOTS_PER_DAY) for s in subj_list)
                <= SLOTS_PER_DAY
            )

    # Each student must attend each required subject exactly once
    for u, subj_list in students.items():
        for s in subj_list:
            model.Add(
                sum(y[(u, d, p, s)] for d in range(DAYS) for p in range(SLOTS_PER_DAY))
                == 1
            )

    # Students cannot attend more than one subject in the same slot
    for u, subj_list in students.items():
        for d in range(DAYS):
            for p in range(SLOTS_PER_DAY):
                model.Add(sum(y[(u, d, p, s)] for s in subj_list) <= 1)

    # Link attendance to teaching
    for u, subj_list in students.items():
        for s in subj_list:
            for d in range(DAYS):
                for p in range(SLOTS_PER_DAY):
                    teacher_vars = [
                        x[(t, d, p, s)]
                        for t, t_subjects in teachers.items()
                        if s in t_subjects
                    ]
                    if teacher_vars:
                        model.Add(y[(u, d, p, s)] <= sum(teacher_vars))
                    else:
                        # No teacher can teach this subject -> attendance impossible
                        model.Add(y[(u, d, p, s)] == 0)

    # Ensure teachers teach only if at least one student attends their lesson
    for t, subj_list in teachers.items():
        for s in subj_list:
            for d in range(DAYS):
                for p in range(SLOTS_PER_DAY):
                    attending = [
                        y[(u, d, p, s)]
                        for u, u_subjects in students.items()
                        if s in u_subjects
                    ]
                    if attending:
                        model.Add(sum(attending) >= x[(t, d, p, s)])
                    else:
                        model.Add(x[(t, d, p, s)] == 0)

    return model, x, y


def solve_and_print(model: cp_model.CpModel, x: dict, y: dict, teachers: Dict[str, List[str]], students: Dict[str, List[str]]) -> None:
    """Solve the model and display a timetable."""
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("No feasible timetable found")
        return

    print("\nGenerated timetable:\n")
    for d in range(DAYS):
        print(f"Day {d + 1}")
        for p in range(SLOTS_PER_DAY):
            print(f"  Slot {p + 1}")
            for t, subj_list in teachers.items():
                taught_subj = None
                for s in subj_list:
                    if solver.Value(x[(t, d, p, s)]):
                        taught_subj = s
                        break
                if taught_subj is None:
                    continue

                attending = [
                    u
                    for u, u_subjects in students.items()
                    if taught_subj in u_subjects and solver.Value(y[(u, d, p, taught_subj)])
                ]
                student_str = ", ".join(attending) if attending else "-"
                print(f"    {t} teaches {taught_subj} -> {student_str}")
        print()


def main() -> None:
    teachers, students = get_data_from_user()
    if not teachers or not students:
        print("Both teachers and students are required to build a timetable.")
        return

    model, x, y = build_model(teachers, students)
    solve_and_print(model, x, y, teachers, students)


if __name__ == "__main__":
    main()
