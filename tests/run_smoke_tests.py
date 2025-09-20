from ortools.sat.python import cp_model
from cp_sat_timetable import build_model, solve_and_print
from app import summarise_core_conflicts
import json


def make_row(id_, subjects):
    return {"id": id_, "subjects": json.dumps(subjects)}


def test_no_locations_allows_schedule():
    students = [make_row(1, ["Math"]), make_row(2, ["English"])]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
        {"id": 2, "subjects": json.dumps(["English"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 2
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=0, max_lessons=2,
        unavailable=[], fixed=[],
        add_assumptions=True,
        locations=None,  # no locations configured
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert len(assignments) > 0, "Expected some lessons to be scheduled without locations"
    assert progress, "Expected at least one progress message"


def test_multi_teacher_disallowed_allows_repeats_same_teacher():
    students = [make_row(1, ["Math"]) ]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
        {"id": 2, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 2
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=2, max_lessons=2,
        allow_repeats=True, max_repeats=2,
        allow_multi_teacher=False,
        unavailable=[], fixed=[],
        add_assumptions=True,
        student_limits={1: (2, 2)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    # Both slots scheduled, but with the same teacher id
    assigned = [(sid, tid, subj, sl) for (sid, tid, subj, sl, loc) in assignments]
    assert len(assigned) == 2
    tids = {t for (_, t, _, _) in assigned}
    assert len(tids) == 1, f"Expected one teacher only; got {tids}"
    assert progress, "Expected progress messages for feasible solve"


def test_unsat_core_present_on_conflict():
    # One student needs 1 lesson, one teacher is unavailable at the only slot.
    students = [make_row(1, ["Math"]) ]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 1
    unavailable = [{"teacher_id": 1, "slot": 0}]
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=1, max_lessons=1,
        allow_repeats=False,
        unavailable=unavailable, fixed=[],
        add_assumptions=True,
        student_limits={1: (1, 1)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to teacher unavailability and student min"
    assert core, "Expected an unsat core to be reported"
    assert all(isinstance(detail, dict) for detail in core), f"Expected structured metadata, got: {core}"
    teacher_details = [detail for detail in core if detail.get('category') == 'teacher_availability']
    assert teacher_details, f"Teacher constraint missing from core: {core}"
    assert any(detail.get('teacher_id') == 1 for detail in teacher_details), f"Teacher identifier missing: {teacher_details}"
    assert any(detail.get('slot') == 0 for detail in teacher_details), f"Slot detail missing: {teacher_details}"

    student_details = [detail for detail in core if detail.get('category') == 'student_limits']
    assert student_details, f"Student constraint missing from core: {core}"
    assert any(detail.get('type') == 'total' for detail in student_details), f"Student requirement missing: {student_details}"
    assert any(detail.get('student_id') == 1 for detail in student_details), f"Student identifier missing: {student_details}"

    summaries = summarise_core_conflicts(core)
    assert summaries, "Aggregated conflict summaries should not be empty"
    assert any('Teacher' in msg and 'unavailable' in msg.lower() for msg in summaries), (
        f"Expected teacher availability summary, got: {summaries}"
    )
    assert any('Student' in msg and ('must' in msg.lower() or 'unavailable' in msg.lower()) for msg in summaries), (
        f"Expected student-related summary, got: {summaries}"
    )
    assert progress == [], "No progress messages expected when infeasible"

    # Repeat-limit plus multi-teacher conflict should aggregate per subject.
    students = [make_row(1, ["Math"])]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
        {"id": 2, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 2
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=2, max_lessons=2,
        allow_repeats=False,
        allow_multi_teacher=False,
        unavailable=[], fixed=[],
        add_assumptions=True,
        student_limits={1: (2, 2)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to repeat and single-teacher limits"
    repeat_details = [detail for detail in core if detail.get('type') == 'repeat_limit']
    assert len(repeat_details) >= 2, f"Expected repeat limits for both teachers, got: {repeat_details}"
    multi_details = [detail for detail in core if detail.get('type') == 'multi_teacher']
    assert multi_details, f"Expected multi-teacher constraint in core, got: {core}"
    summaries = summarise_core_conflicts(core)
    assert any('may take at most one lesson' in msg.lower() and 'Teacher #1' in msg and 'Teacher #2' in msg for msg in summaries), (
        f"Expected aggregated repeat limit mentioning both teachers, got: {summaries}"
    )
    assert any('must use a single teacher' in msg and 'Teacher #1' in msg and 'Teacher #2' in msg for msg in summaries), (
        f"Expected aggregated multi-teacher summary with teacher names, got: {summaries}"
    )

    # Teacher lesson minimum should report a shortfall based on feasible slots.
    students = [
        make_row(1, ["Math"]),
        make_row(2, ["Math"]),
        make_row(3, ["Math"]),
    ]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 3, "max_lessons": None},
    ]
    slots = 1
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=0, max_lessons=3,
        allow_repeats=False,
        unavailable=[], fixed=[],
        add_assumptions=True,
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to teacher minimum"
    limit_details = [detail for detail in core if detail.get('category') == 'teacher_limits']
    assert limit_details, f"Teacher limit missing from unsat core: {core}"
    summaries = summarise_core_conflicts(core)
    assert any('needs at least 3 lessons' in msg or 'must teach at least 3 lessons' in msg for msg in summaries), (
        f"Expected mention of the teacher minimum shortfall, got: {summaries}"
    )
    assert any('only 1' in msg and 'slot' in msg.lower() for msg in summaries), (
        f"Expected summary to mention limited feasible slots, got: {summaries}"
    )

    # Subject requirement conflicts should group students by subject.
    students = [
        make_row(1, ["Math"]),
        make_row(2, ["Math"]),
    ]
    teachers = [
        {"id": 1, "subjects": json.dumps(["Math"]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 1
    unavailable = [{"teacher_id": 1, "slot": 0}]
    model, vars_, loc_vars, assumptions = build_model(
        students, teachers, slots,
        min_lessons=0, max_lessons=1,
        allow_repeats=False,
        unavailable=unavailable, fixed=[],
        add_assumptions=True,
        student_limits={1: (0, 1), 2: (0, 1)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumptions)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to missing subject coverage"
    summaries = summarise_core_conflicts(core)
    assert any(
        'subject math' in msg.lower() and 'still missing' in msg.lower()
        and 'student #1' in msg and 'student #2' in msg
        for msg in summaries
    ), f"Expected grouped subject requirement summary, got: {summaries}"


def main():
    tests = [
        ("no_locations", test_no_locations_allows_schedule),
        ("multi_teacher_disallowed_repeats_same_teacher", test_multi_teacher_disallowed_allows_repeats_same_teacher),
        ("unsat_core", test_unsat_core_present_on_conflict),
    ]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            failures.append(name)
    if failures:
        raise SystemExit(1)
    print("All smoke tests passed.")


if __name__ == "__main__":
    main()

