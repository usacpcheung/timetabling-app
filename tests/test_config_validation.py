"""Regression tests for configuration validation logic."""

import os
import sys
import sqlite3

from flask import get_flashed_messages
from werkzeug.datastructures import MultiDict


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app

    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _config_values(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT slots_per_day, slot_duration FROM config WHERE id=1').fetchone()
    conn.close()
    return row['slots_per_day'], row['slot_duration']


def test_reject_zero_slots_per_day(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_values(app.DB_PATH)

    data = MultiDict([
        ('slots_per_day', '0'),
        ('slot_duration', '30'),
    ])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Slots per day and slot duration must be positive integers.') in flashes
    assert _config_values(app.DB_PATH) == original


def test_reject_negative_slot_duration(tmp_path):
    import app

    conn = setup_db(tmp_path)
    conn.close()
    original = _config_values(app.DB_PATH)

    data = MultiDict([
        ('slots_per_day', '8'),
        ('slot_duration', '-5'),
    ])

    with app.app.test_request_context('/config', method='POST', data=data):
        response = app.config()
        flashes = get_flashed_messages(with_categories=True)

    assert response.status_code == 302
    assert ('error', 'Slots per day and slot duration must be positive integers.') in flashes
    assert _config_values(app.DB_PATH) == original
