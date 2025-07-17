import os
import sqlite3
import tempfile
import json
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import app


def run_with_temp_db(func):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    path = tmp.name
    tmp.close()
    original = app.DB_PATH
    app.DB_PATH = path
    try:
        app.init_db()
        func(path)
    finally:
        app.DB_PATH = original
        if os.path.exists(path):
            os.remove(path)


def collect_counts(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM students")
    students = c.fetchall()
    c.execute("SELECT * FROM config WHERE id=1")
    cfg = c.fetchone()
    min_lessons = cfg["min_lessons"]
    max_lessons = cfg["max_lessons"]

    counts = {}
    for s in students:
        subjects = json.loads(s["subjects"])
        per_subject = {}
        for subj in subjects:
            c.execute(
                "SELECT COUNT(*) FROM timetable WHERE student_id=? AND subject=?",
                (s["id"], subj),
            )
            per_subject[subj] = c.fetchone()[0]
        counts[s["id"]] = (subjects, per_subject)
    conn.close()
    return counts, min_lessons, max_lessons


def test_schedule_respects_min_max():
    def inner(path):
        app.generate_schedule()
        counts, min_l, max_l = collect_counts(path)
        for sid, (subjects, per_subject) in counts.items():
            if not subjects:
                continue
            min_per = max(1, min_l // len(subjects))
            max_per = max(1, (max_l + len(subjects) - 1) // len(subjects))
            for subj in subjects:
                count = per_subject.get(subj, 0)
                assert count >= min_per
                assert count <= max_per
    run_with_temp_db(inner)

