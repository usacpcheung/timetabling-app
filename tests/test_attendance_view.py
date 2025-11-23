"""Regression tests for the attendance view."""

import os
import sys
import sqlite3


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app

    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_table(html, table_id):
    marker = f'id="{table_id}"'
    start = html.find(marker)
    assert start != -1, f"table {table_id} not found"
    end = html.find('</table>', start)
    assert end != -1, f"table {table_id} not terminated"
    return html[start:end]


def test_inactive_student_not_shown_as_deleted(tmp_path):
    import app

    conn = setup_db(tmp_path)
    cur = conn.cursor()
    student = cur.execute("SELECT id, name FROM students WHERE name='Student 1'").fetchone()
    subject_id = cur.execute("SELECT id FROM subjects WHERE name='Math'").fetchone()[0]
    cur.execute(
        "INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)",
        (student['id'], student['name'], subject_id, '2024-01-01'),
    )
    cur.execute("UPDATE students SET active=0 WHERE id=?", (student['id'],))
    conn.commit()
    conn.close()

    client = app.app.test_client()
    response = client.get('/attendance')
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    deleted_section = _extract_table(html, 'deleted-table')
    assert student['name'] not in deleted_section

    inactive_section = _extract_table(html, 'inactive-table')
    assert student['name'] in inactive_section
