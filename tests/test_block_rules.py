"""Tests for the ``block_allowed`` helper in :mod:`app`.

These tests create a temporary database and verify that students cannot block a
teacher if doing so would conflict with an existing fixed assignment.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlite3
import json
import app


def setup_db(tmp_path):
    """Initialise and return a database connection for testing."""
    db_path = tmp_path / "test.db"
    app.DB_PATH = str(db_path)
    app.init_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_block_teacher_fixed_assignment(tmp_path, monkeypatch):
    """A student cannot block a teacher with a fixed assignment."""
    conn = setup_db(tmp_path)
    # teacher 1 teaches Math, student 1 requires Math
    conn.execute(
        "INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot)"
        " VALUES (1, 1, NULL, 'Math', 0)"
    )
    conn.commit()

    c = conn.cursor()
    c.execute('SELECT id, subjects FROM teachers')
    teacher_map = {r[0]: json.loads(r[1]) for r in c.fetchall()}
    c.execute('SELECT group_id, student_id FROM group_members')
    rows = c.fetchall()
    group_members = {}
    student_groups = {}
    for gid, sid in rows:
        group_members.setdefault(gid, []).append(sid)
        student_groups.setdefault(sid, []).append(gid)
    c.execute('SELECT id, subjects FROM groups')
    group_subj_map = {r[0]: json.loads(r[1]) for r in c.fetchall()}
    c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
    br = c.fetchall()
    block_map = {}
    for sid, tid in br:
        block_map.setdefault(sid, set()).add(tid)
    c.execute('SELECT teacher_id, student_id FROM fixed_assignments WHERE student_id IS NOT NULL')
    fixed_pairs = {(r[1], r[0]) for r in c.fetchall()}

    allowed = app.block_allowed(
        1,
        1,
        teacher_map,
        student_groups,
        group_members,
        group_subj_map,
        block_map,
        fixed_pairs,
    )
    assert not allowed
    conn.close()

