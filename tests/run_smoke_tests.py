from ortools.sat.python import cp_model
from cp_sat_timetable import build_model, solve_and_print
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
    model, vars_, loc_vars, registry = build_model(
        students, teachers, slots,
        min_lessons=0, max_lessons=2,
        unavailable=[], fixed=[],
        add_assumptions=True,
        locations=None,  # no locations configured
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, registry)
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
    model, vars_, loc_vars, registry = build_model(
        students, teachers, slots,
        min_lessons=2, max_lessons=2,
        allow_repeats=True, max_repeats=2,
        allow_multi_teacher=False,
        unavailable=[], fixed=[],
        add_assumptions=True,
        student_limits={1: (2, 2)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, registry)
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
    model, vars_, loc_vars, registry = build_model(
        students, teachers, slots,
        min_lessons=1, max_lessons=1,
        allow_repeats=False,
        unavailable=unavailable, fixed=[],
        add_assumptions=True,
        student_limits={1: (1, 1)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, registry)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to teacher unavailability and student min"
    assert core, "Expected an unsat core to be reported"
    # Core likely includes teacher availability and/or student limits information
    assert any(info.kind in ("teacher_availability", "student_limits") for info in core), f"Unexpected core: {core}"
    assert progress == [], "No progress messages expected when infeasible"


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

