from ortools.sat.python import cp_model
from app import summarize_unsat_core
from cp_sat_timetable import AssumptionInfo, build_model, solve_and_print
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
    model, vars_, loc_vars, assumption_registry = build_model(
        students, teachers, slots,
        min_lessons=0, max_lessons=2,
        unavailable=[], fixed=[],
        add_assumptions=True,
        locations=None,  # no locations configured
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumption_registry)
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
    model, vars_, loc_vars, assumption_registry = build_model(
        students, teachers, slots,
        min_lessons=2, max_lessons=2,
        allow_repeats=True, max_repeats=2,
        allow_multi_teacher=False,
        unavailable=[], fixed=[],
        add_assumptions=True,
        student_limits={1: (2, 2)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumption_registry)
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
    model, vars_, loc_vars, assumption_registry = build_model(
        students, teachers, slots,
        min_lessons=1, max_lessons=1,
        allow_repeats=False,
        unavailable=unavailable, fixed=[],
        add_assumptions=True,
        student_limits={1: (1, 1)},
        locations=[],
    )
    status, assignments, core, progress = solve_and_print(model, vars_, loc_vars, assumption_registry)
    assert status == cp_model.INFEASIBLE, "Expected infeasible due to teacher unavailability and student min"
    assert core, "Expected an unsat core to be reported"
    # Core likely includes teacher_availability and student_limits
    assert any(getattr(info, "kind", None) in ("teacher_availability", "student_limits") for info in core), f"Unexpected core: {core}"
    assert progress == [], "No progress messages expected when infeasible"


def make_info(kind, label, context):
    return AssumptionInfo(literal=None, kind=kind, label=label, context=context)


def test_summarize_unsat_core_groups_teacher_conflicts():
    core = [
        make_info(
            "teacher_availability",
            "teacher_slot_t1_sl0",
            {"teacher_id": 1, "teacher_name": "Alice", "slot": 0, "candidate_lessons": 2},
        ),
        make_info(
            "teacher_availability",
            "teacher_slot_t1_sl1",
            {"teacher_id": 1, "teacher_name": "Alice", "slot": 1, "candidate_lessons": 3},
        ),
        make_info(
            "teacher_availability",
            "block_s1_t1_sl0",
            {
                "teacher_id": 1,
                "teacher_name": "Alice",
                "student_id": 1,
                "student_name": "Bob",
                "subject": "Math",
                "slot": 0,
                "reasons": ["teacher_unavailable"],
            },
        ),
        make_info(
            "teacher_availability",
            "block_s2_t1_sl1",
            {
                "teacher_id": 1,
                "teacher_name": "Alice",
                "student_id": 2,
                "student_name": "Carol",
                "subject": "English",
                "slot": 1,
                "reasons": ["teacher_blocked"],
            },
        ),
    ]
    messages = summarize_unsat_core(core)
    assert len(messages) == 2
    slot_msg = next(msg for msg in messages if "has conflicts" in msg)
    assert "Teacher Alice" in slot_msg
    assert "slots 0, 1" in slot_msg
    assert "Bob (Math)" in slot_msg and "Carol (English)" in slot_msg
    block_msg = next(msg for msg in messages if "cannot teach" in msg)
    assert "teacher unavailable" in block_msg.lower()
    assert "teacher blocked" in block_msg.lower()


def test_summarize_unsat_core_groups_student_slots():
    core = [
        make_info(
            "student_limits",
            "student_slot_s1_sl0",
            {"student_id": 1, "student_name": "Bob", "slot": 0, "candidate_lessons": 2},
        ),
        make_info(
            "student_limits",
            "student_slot_s1_sl1",
            {"student_id": 1, "student_name": "Bob", "slot": 1, "candidate_lessons": 3},
        ),
    ]
    messages = summarize_unsat_core(core)
    assert len(messages) == 1
    msg = messages[0]
    assert "Student Bob" in msg
    assert "slots 0, 1" in msg
    assert "0: 2" in msg and "1: 3" in msg


def main():
    tests = [
        ("no_locations", test_no_locations_allows_schedule),
        ("multi_teacher_disallowed_repeats_same_teacher", test_multi_teacher_disallowed_allows_repeats_same_teacher),
        ("unsat_core", test_unsat_core_present_on_conflict),
        ("summarize_teacher_conflicts", test_summarize_unsat_core_groups_teacher_conflicts),
        ("summarize_student_slots", test_summarize_unsat_core_groups_student_slots),
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

