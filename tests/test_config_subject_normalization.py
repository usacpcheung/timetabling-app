"""Ensure legacy subject payloads are normalized for the config view."""

import json
import os
import sqlite3
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_config_handles_legacy_subject_payload(tmp_path):
    import app

    legacy_payload = json.dumps({"42": True})
    original_db = app.DB_PATH
    try:
        app.DB_PATH = str(tmp_path / 'legacy.db')
        app.init_db()

        conn = sqlite3.connect(app.DB_PATH)
        conn.execute(
            'INSERT INTO subjects (id, name, min_percentage) VALUES (?, ?, ?)',
            (42, 'Legacy Subject', None),
        )
        conn.execute(
            'INSERT INTO teachers (name, subjects, min_lessons, max_lessons, needs_lessons) '
            'VALUES (?, ?, ?, ?, ?)',
            ('Legacy Teacher', legacy_payload, None, None, 1),
        )
        conn.execute(
            '''
            INSERT INTO students (
                name, subjects, active, min_lessons, max_lessons,
                allow_repeats, max_repeats, allow_consecutive, prefer_consecutive,
                allow_multi_teacher, repeat_subjects
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                'Legacy Student',
                legacy_payload,
                None,
                None,
                1,
                2,
                0,
                0,
                1,
                legacy_payload,
            ),
        )
        conn.execute(
            'INSERT INTO groups (name, subjects) VALUES (?, ?)',
            ('Legacy Group', legacy_payload),
        )
        conn.commit()
        conn.close()

        app.app.config['TESTING'] = True
        with app.app.test_client() as client:
            response = client.get('/config')

        assert response.status_code == 200
        assert b'id="load-preset-modal"' in response.data
    finally:
        app.DB_PATH = original_db
