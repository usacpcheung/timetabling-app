import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solver.api import SolverStatus, build_model, solve_model
from app import summarize_unsat_core, _format_summary_details, UNSAT_REASON_MAP
import json


def make_row(id_, subjects, name=None):
    row = {"id": id_, "subjects": json.dumps(subjects)}
    if name is not None:
        row["name"] = name
    return row


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
    result = solve_model(model, vars_, loc_vars, assumption_registry)
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert len(result.assignments) > 0, "Expected some lessons to be scheduled without locations"
    assert result.progress, "Expected at least one progress message"


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
    result = solve_model(model, vars_, loc_vars, assumption_registry)
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    # Both slots scheduled, but with the same teacher id
    assigned = [assignment.as_tuple()[:-1] for assignment in result.assignments]
    assert len(assigned) == 2
    tids = {t for (_, t, _, _) in assigned}
    assert len(tids) == 1, f"Expected one teacher only; got {tids}"
    assert result.progress, "Expected progress messages for feasible solve"


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
    result = solve_model(model, vars_, loc_vars, assumption_registry)
    assert result.status == SolverStatus.INFEASIBLE, "Expected infeasible due to teacher unavailability and student min"
    assert result.core, "Expected an unsat core to be reported"
    # Core likely includes teacher_availability and student_limits
    assert any(getattr(info, "kind", None) in ("teacher_availability", "student_limits") for info in result.core), f"Unexpected core: {result.core}"
    assert result.progress == [], "No progress messages expected when infeasible"
    summaries = summarize_unsat_core(result.core)
    teacher_summaries = [
        s for s in summaries if s.get('aggregated') and s.get('kind') == 'teacher_availability'
    ]
    assert teacher_summaries, f"Expected teacher summaries; got {summaries}"
    capacity_summary = next(
        (
            s
            for s in teacher_summaries
            if s.get('category') in {"capacity", "block"}
        ),
        None,
    )
    assert capacity_summary is not None, f"Expected capacity summary; got {teacher_summaries}"
    assert 0 in capacity_summary.get('slots', []), f"Expected slot 0 in teacher summary; got {capacity_summary}"
    if capacity_summary.get('category') == 'capacity':
        assert capacity_summary.get('slot_candidates', {}).get(0) == 1, (
            f"Expected one candidate lesson; got {capacity_summary}"
        )
    else:
        assert capacity_summary.get('category') == 'block', capacity_summary
        assert capacity_summary.get('pairs'), f"Expected conflicting lesson pairs; got {capacity_summary}"
    student_summary = next((s for s in summaries if s.get('aggregated') and s.get('kind') == 'student_limits'), None)
    assert student_summary is not None, f"Expected aggregated student summary; got {summaries}"
    slots = student_summary.get('slots', [])
    if slots:
        assert 0 in slots, f"Expected slot 0 in student summary; got {student_summary}"
    else:
        assert student_summary.get('lesson_options') in ([1], {1}), (
            f"Expected lesson options to reference the blocked slot; got {student_summary}"
        )
    candidates = student_summary.get('candidate_lessons')
    if candidates:
        assert candidates == [1], f"Expected candidate lessons of 1; got {student_summary}"
    else:
        assert student_summary.get('lesson_options') in ([1], {1}), (
            f"Expected lesson options fallback; got {student_summary}"
        )


def test_capacity_summary_formats_slot_candidates_human_readable():
    summary = {
        'kind': 'teacher_availability',
        'aggregated': True,
        'category': 'capacity',
        'teacher_id': 5,
        'teacher_name': 'Ms. Wong',
        'slots': [0],
        'slot_candidates': {0: 21},
        'slot_labels': {0: '08:30-09:00'},
    }
    details = _format_summary_details(summary)
    combined = ' '.join(details)
    assert 'slot 0 (08:30-09:00) has 21 candidate lessons' in combined, combined


def test_group_unsat_message_includes_group_and_subject_names():
    group_offset = 10000
    group_id = group_offset + 1
    group_name = "Robotics Club"
    subject_id = 9
    subject_name = "Robotics"

    students = [
        make_row(1, [subject_id], name="Alice"),
        make_row(group_id, [subject_id], name=group_name),
    ]
    teachers = [
        {"id": 1, "subjects": json.dumps([subject_id]), "min_lessons": 0, "max_lessons": None},
    ]
    slots = 1
    unavailable = [{"teacher_id": 1, "slot": 0}]
    model, vars_, loc_vars, assumption_registry = build_model(
        students, teachers, slots,
        min_lessons=1, max_lessons=1,
        allow_repeats=False,
        unavailable=unavailable, fixed=[],
        add_assumptions=True,
        group_members={group_id: [1]},
        student_limits={1: (1, 1)},
        locations=[],
        subject_lookup={subject_id: subject_name},
    )
    result = solve_model(model, vars_, loc_vars, assumption_registry)
    assert result.status == SolverStatus.INFEASIBLE, "Expected infeasible due to group requirements"
    summaries = summarize_unsat_core(result.core)
    aggregated_messages = []
    for summary in summaries:
        if summary.get('aggregated'):
            kind = summary.get('kind')
            base = UNSAT_REASON_MAP.get(kind, summary.get('label') or kind or 'Constraint conflict')
            details = _format_summary_details(summary)
            message = base
            if details:
                message = f"{base} ({'; '.join(details)})"
            aggregated_messages.append(message)
    combined = ' '.join(aggregated_messages)
    assert group_name in combined, f"Expected group name in messages: {aggregated_messages}"
    assert subject_name in combined, f"Expected subject name in messages: {aggregated_messages}"


def main():
    tests = [
        ("no_locations", test_no_locations_allows_schedule),
        ("multi_teacher_disallowed_repeats_same_teacher", test_multi_teacher_disallowed_allows_repeats_same_teacher),
        ("unsat_core", test_unsat_core_present_on_conflict),
        ("capacity_summary_formatting", test_capacity_summary_formats_slot_candidates_human_readable),
        ("group_unsat_message", test_group_unsat_message_includes_group_and_subject_names),
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

