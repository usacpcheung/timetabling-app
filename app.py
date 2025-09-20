"""A heavily commented Flask web application for generating simple school timetables.

This file contains all of the web routes and database access logic.  Data is
stored in a local SQLite database which is initialized with some sample values
on first run.
The comments throughout this file explain each step in detail so beginning programmers can follow the flow.  Users interact with the app via standard web forms to configure
teachers, students and various scheduling parameters.  When a timetable is
requested, the configuration is passed to the CP-SAT model defined in
``cp_sat_timetable.py`` and the resulting schedule is saved back to the
database.
"""

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import sqlite3
import json
import os
import logging
from datetime import date
import statistics
import tempfile
import zipfile
from datetime import datetime
from collections import OrderedDict
from werkzeug.utils import secure_filename

from cp_sat_timetable import build_model, solve_and_print, AssumptionInfo

app = Flask(__name__)
app.secret_key = 'dev'

# Store the SQLite database inside a dedicated ``data`` directory.  This keeps
# application files read-only and allows the database folder to have relaxed
# permissions when deployed system-wide (e.g. under ``Program Files`` on
# Windows).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "timetable.db")

CURRENT_PRESET_VERSION = 2
MAX_PRESETS = 10  # maximum number of configuration presets to keep

# Tables that represent configuration data. Presets only dump and restore
# these tables so previously generated timetables, worksheets or logs remain
# untouched when a preset is loaded.
CONFIG_TABLES = [
    'config',
    'teachers',
    'teachers_archive',
    'students',
    'students_archive',
    'subjects',
    'subjects_archive',
    'teacher_unavailable',
    'student_unavailable',
    'fixed_assignments',
    'groups',
    'group_members',
    'groups_archive',
    'student_teacher_block',
    'locations',
    'locations_archive',
    'student_locations',
    'group_locations',
]


def get_db():
    """Return a connection to the SQLite database.

    Each view function calls this helper to obtain a connection. Setting
    ``row_factory`` allows rows to behave like dictionaries so template
    code can access columns by name.
    """
    dir_ = os.path.dirname(DB_PATH)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the SQLite tables and populate default rows.

    This function also performs simple migrations when new columns are added in
    later versions of the code. It is called on start-up and whenever the
    database is reset via the web interface."""
    # ``get_db`` will create the SQLite file if it does not already exist. To
    # distinguish a brand new database from an existing one we check for the
    # file beforehand.
    db_exists = os.path.exists(DB_PATH)
    conn = get_db()
    c = conn.cursor()

    def table_exists(name):
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
        return c.fetchone() is not None

    def column_exists(table, column):
        c.execute(f"PRAGMA table_info({table})")
        return column in [row[1] for row in c.fetchall()]

    # create tables if not present
    if not table_exists('config'):
        c.execute('''CREATE TABLE config (
            id INTEGER PRIMARY KEY,
            slots_per_day INTEGER,
            slot_duration INTEGER,
            slot_start_times TEXT,
            min_lessons INTEGER,
            max_lessons INTEGER,
            teacher_min_lessons INTEGER,
            teacher_max_lessons INTEGER,
            allow_repeats INTEGER,
            max_repeats INTEGER,
            prefer_consecutive INTEGER,
            allow_consecutive INTEGER,
            consecutive_weight INTEGER,
            require_all_subjects INTEGER,
            use_attendance_priority INTEGER,
            attendance_weight INTEGER,
            group_weight REAL,
            allow_multi_teacher INTEGER,
            balance_teacher_load INTEGER,
            balance_weight INTEGER,
            well_attend_weight REAL,
            solver_time_limit INTEGER DEFAULT 120
        )''')
    else:
        if not column_exists('config', 'slot_start_times'):
            c.execute('ALTER TABLE config ADD COLUMN slot_start_times TEXT')
        if not column_exists('config', 'require_all_subjects'):
            c.execute('ALTER TABLE config ADD COLUMN require_all_subjects INTEGER DEFAULT 1')
        if not column_exists('config', 'use_attendance_priority'):
            c.execute('ALTER TABLE config ADD COLUMN use_attendance_priority INTEGER DEFAULT 0')
        if not column_exists('config', 'attendance_weight'):
            c.execute('ALTER TABLE config ADD COLUMN attendance_weight INTEGER DEFAULT 10')
        if not column_exists('config', 'group_weight'):
            c.execute('ALTER TABLE config ADD COLUMN group_weight REAL DEFAULT 2.0')
        if not column_exists('config', 'allow_multi_teacher'):
            c.execute('ALTER TABLE config ADD COLUMN allow_multi_teacher INTEGER DEFAULT 1')
        if not column_exists('config', 'balance_teacher_load'):
            c.execute('ALTER TABLE config ADD COLUMN balance_teacher_load INTEGER DEFAULT 0')
        if not column_exists('config', 'balance_weight'):
            c.execute('ALTER TABLE config ADD COLUMN balance_weight INTEGER DEFAULT 1')
        if not column_exists('config', 'well_attend_weight'):
            c.execute('ALTER TABLE config ADD COLUMN well_attend_weight REAL DEFAULT 1')
        if not column_exists('config', 'solver_time_limit'):
            c.execute('ALTER TABLE config ADD COLUMN solver_time_limit INTEGER DEFAULT 120')

    if not table_exists('teachers'):
        c.execute('''CREATE TABLE teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            subjects TEXT,
            min_lessons INTEGER,
            max_lessons INTEGER
        )''')

    if not table_exists('teachers_archive'):
        c.execute('''CREATE TABLE teachers_archive (
            id INTEGER PRIMARY KEY,
            name TEXT
        )''')

    if not table_exists('students'):
        c.execute('''CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            subjects TEXT,
            active INTEGER DEFAULT 1,
            min_lessons INTEGER,
            max_lessons INTEGER,
            allow_repeats INTEGER,
            max_repeats INTEGER,
            allow_consecutive INTEGER,
            prefer_consecutive INTEGER,
            allow_multi_teacher INTEGER,
            repeat_subjects TEXT
        )''')
    else:
        if not column_exists('students', 'active'):
            c.execute('ALTER TABLE students ADD COLUMN active INTEGER DEFAULT 1')
        if not column_exists('students', 'min_lessons'):
            c.execute('ALTER TABLE students ADD COLUMN min_lessons INTEGER')
        if not column_exists('students', 'max_lessons'):
            c.execute('ALTER TABLE students ADD COLUMN max_lessons INTEGER')
        if not column_exists('students', 'allow_repeats'):
            c.execute('ALTER TABLE students ADD COLUMN allow_repeats INTEGER')
        if not column_exists('students', 'max_repeats'):
            c.execute('ALTER TABLE students ADD COLUMN max_repeats INTEGER')
        if not column_exists('students', 'allow_consecutive'):
            c.execute('ALTER TABLE students ADD COLUMN allow_consecutive INTEGER')
        if not column_exists('students', 'prefer_consecutive'):
            c.execute('ALTER TABLE students ADD COLUMN prefer_consecutive INTEGER')
        if not column_exists('students', 'allow_multi_teacher'):
            c.execute('ALTER TABLE students ADD COLUMN allow_multi_teacher INTEGER')
        if not column_exists('students', 'repeat_subjects'):
            c.execute('ALTER TABLE students ADD COLUMN repeat_subjects TEXT')

    if not table_exists('students_archive'):
        c.execute('''CREATE TABLE students_archive (
            id INTEGER PRIMARY KEY,
            name TEXT
        )''')

    if not table_exists('subjects'):
        c.execute('''CREATE TABLE subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            min_percentage INTEGER
        )''')
    else:
        if not column_exists('subjects', 'min_percentage'):
            c.execute('ALTER TABLE subjects ADD COLUMN min_percentage INTEGER')

    if not table_exists('subjects_archive'):
        c.execute('''CREATE TABLE subjects_archive (
            id INTEGER PRIMARY KEY,
            name TEXT
        )''')

    if not table_exists('teacher_unavailable'):
        c.execute('''CREATE TABLE teacher_unavailable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            slot INTEGER
        )''')

    if not table_exists('student_unavailable'):
        c.execute('''CREATE TABLE student_unavailable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            slot INTEGER
        )''')

    if not table_exists('fixed_assignments'):
        c.execute('''CREATE TABLE fixed_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            student_id INTEGER,
            group_id INTEGER,
            subject TEXT,
            subject_id INTEGER,
            slot INTEGER
        )''')
    else:
        if not column_exists('fixed_assignments', 'group_id'):
            c.execute('ALTER TABLE fixed_assignments ADD COLUMN group_id INTEGER')
        if not column_exists('fixed_assignments', 'subject_id'):
            c.execute('ALTER TABLE fixed_assignments ADD COLUMN subject_id INTEGER')

    if not table_exists('timetable'):
        c.execute('''CREATE TABLE timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            group_id INTEGER,
            teacher_id INTEGER,
            subject TEXT,
            subject_id INTEGER,
            slot INTEGER,
            location_id INTEGER,
            date TEXT
        )''')
    else:
        if not column_exists('timetable', 'date'):
            c.execute('ALTER TABLE timetable ADD COLUMN date TEXT')
        if not column_exists('timetable', 'group_id'):
            c.execute('ALTER TABLE timetable ADD COLUMN group_id INTEGER')
        if not column_exists('timetable', 'location_id'):
            c.execute('ALTER TABLE timetable ADD COLUMN location_id INTEGER')
        if not column_exists('timetable', 'subject_id'):
            c.execute('ALTER TABLE timetable ADD COLUMN subject_id INTEGER')

    if not table_exists('locations'):
        c.execute('''CREATE TABLE locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )''')

    if not table_exists('locations_archive'):
        c.execute('''CREATE TABLE locations_archive (
            id INTEGER PRIMARY KEY,
            name TEXT
        )''')

    if not table_exists('student_locations'):
        c.execute('''CREATE TABLE student_locations (
            student_id INTEGER,
            location_id INTEGER
        )''')

    if not table_exists('group_locations'):
        c.execute('''CREATE TABLE group_locations (
            group_id INTEGER,
            location_id INTEGER
        )''')

    if not table_exists('timetable_snapshot'):
        c.execute('''CREATE TABLE timetable_snapshot (
            date TEXT PRIMARY KEY,
            missing TEXT,
            lesson_counts TEXT,
            group_data TEXT,
            location_data TEXT,
            teacher_data TEXT
        )''')
    else:
        if not column_exists('timetable_snapshot', 'group_data'):
            c.execute('ALTER TABLE timetable_snapshot ADD COLUMN group_data TEXT')
        if not column_exists('timetable_snapshot', 'location_data'):
            c.execute('ALTER TABLE timetable_snapshot ADD COLUMN location_data TEXT')
        if not column_exists('timetable_snapshot', 'teacher_data'):
            c.execute('ALTER TABLE timetable_snapshot ADD COLUMN teacher_data TEXT')
        rows = c.execute(
            "SELECT date FROM timetable_snapshot "
            "WHERE group_data IS NULL OR TRIM(group_data) = '' "
            "OR location_data IS NULL OR TRIM(location_data) = '' "
            "OR teacher_data IS NULL OR TRIM(teacher_data) = ''"
        ).fetchall()
        for row in rows:
            try:
                get_missing_and_counts(c, row['date'], refresh=True)
            except Exception:
                logging.exception('Failed to refresh timetable snapshot for %s', row['date'])

    if not table_exists('attendance_log'):
        c.execute('''CREATE TABLE attendance_log (
            student_id INTEGER,
            student_name TEXT,
            subject TEXT,
            subject_id INTEGER,
            date TEXT
        )''')
    else:
        if not column_exists('attendance_log', 'subject_id'):
            c.execute('ALTER TABLE attendance_log ADD COLUMN subject_id INTEGER')

    if not table_exists('worksheets'):
        c.execute('''CREATE TABLE worksheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject_id INTEGER,
            date TEXT
        )''')
    else:
        if not column_exists('worksheets', 'subject_id'):
            c.execute('ALTER TABLE worksheets ADD COLUMN subject_id INTEGER')

    if not table_exists('groups'):
        c.execute('''CREATE TABLE groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            subjects TEXT
        )''')

    if not table_exists('group_members'):
        c.execute('''CREATE TABLE group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            student_id INTEGER
        )''')

    if not table_exists('groups_archive'):
        c.execute('''CREATE TABLE groups_archive (
            id INTEGER PRIMARY KEY,
            name TEXT
        )''')

    if not table_exists('student_teacher_block'):
        c.execute('''CREATE TABLE student_teacher_block (
            student_id INTEGER,
            teacher_id INTEGER,
            PRIMARY KEY(student_id, teacher_id)
        )''')

    if not table_exists('config_presets'):
        c.execute('''CREATE TABLE config_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            data TEXT,
            version INTEGER,
            created_at TEXT
        )''')


    # prune corrupt or excess presets
    def cleanup_presets(cur):
        cur.execute('SELECT id, data FROM config_presets ORDER BY created_at DESC')
        rows = cur.fetchall()
        for r in rows[MAX_PRESETS:]:
            cur.execute('DELETE FROM config_presets WHERE id=?', (r['id'],))
        for r in rows[:MAX_PRESETS]:
            try:
                json.loads(r['data'])
            except Exception:
                logging.warning('Removing corrupted preset %s', r['id'])
                cur.execute('DELETE FROM config_presets WHERE id=?', (r['id'],))

    cleanup_presets(c)

    # --- migrate subjects from names to ids and populate subject_id columns ---
    # Earlier versions stored subject names directly which caused issues when
    # migrating to integer IDs.  Some runs also introduced duplicate subject
    # rows where the ``name`` column held an old numeric ID.  Clean those up
    # first so subsequent mapping uses a stable subject table.
    c.execute('SELECT id, name FROM subjects')
    rows = c.fetchall()
    existing_ids = {r['id'] for r in rows}
    numeric_dupes = []
    for r in rows:
        nm = r['name']
        if nm and str(nm).isdigit():
            num = int(nm)
            if num in existing_ids and num != r['id']:
                numeric_dupes.append((r['id'], num))

    # Re-point any references that used the duplicate IDs to the correct one
    for bad_id, good_id in numeric_dupes:
        for tbl in ('timetable', 'worksheets', 'fixed_assignments', 'attendance_log'):
            if table_exists(tbl) and column_exists(tbl, 'subject_id'):
                c.execute(f'UPDATE {tbl} SET subject_id=? WHERE subject_id=?', (good_id, bad_id))
        for tbl in ('teachers', 'students', 'groups'):
            if table_exists(tbl):
                c.execute(f'SELECT id, subjects FROM {tbl}')
                for row in c.fetchall():
                    try:
                        subj_ids = json.loads(row['subjects']) if row['subjects'] else []
                    except Exception:
                        subj_ids = []
                    if bad_id in subj_ids:
                        subj_ids = [good_id if i == bad_id else i for i in subj_ids]
                        c.execute(
                            f'UPDATE {tbl} SET subjects=? WHERE id=?',
                            (json.dumps(subj_ids), row['id'])
                        )
        c.execute('DELETE FROM subjects WHERE id=?', (bad_id,))

    # Refresh subject map after cleanup
    c.execute('SELECT id, name FROM subjects')
    subj_map = {r['name']: r['id'] for r in c.fetchall()}

    def ensure_subject(value):
        if value is None:
            return None
        # Treat integers or digit strings as existing IDs when possible
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            sid = int(value)
            c.execute('SELECT 1 FROM subjects WHERE id=?', (sid,))
            if c.fetchone():
                return sid
            return None
        name = value
        sid = subj_map.get(name)
        if sid is None:
            c.execute('INSERT INTO subjects (name) VALUES (?)', (name,))
            sid = c.lastrowid
            subj_map[name] = sid
        return sid

    # convert subject lists for teachers, students and groups
    for table in ('teachers', 'students', 'groups'):
        if table_exists(table):
            c.execute(f'SELECT id, subjects FROM {table}')
            rows = c.fetchall()
            for row in rows:
                try:
                    items = json.loads(row['subjects']) if row['subjects'] else []
                except Exception:
                    items = []
                ids = []
                for it in items:
                    sid = ensure_subject(it)
                    if sid is not None:
                        ids.append(sid)
                c.execute(
                    f'UPDATE {table} SET subjects=? WHERE id=?',
                    (json.dumps(ids), row['id'])
                )

    # populate subject_id columns for existing rows
    for tbl in ('timetable', 'worksheets', 'fixed_assignments', 'attendance_log'):
        if table_exists(tbl) and column_exists(tbl, 'subject_id') and column_exists(tbl, 'subject'):
            # Selecting ``rowid`` directly can return the primary key column name
            # (e.g. ``id``) depending on the table definition.  Alias it to a
            # stable column name so it can be accessed reliably from the row
            # mapping.
            c.execute(
                f'SELECT rowid AS rid, subject FROM {tbl} '
                'WHERE subject IS NOT NULL AND (subject_id IS NULL OR subject_id="")'
            )
            for r in c.fetchall():
                sid = ensure_subject(r['subject'])
                if sid is not None:
                    c.execute(
                        f'UPDATE {tbl} SET subject_id=? WHERE rowid=?',
                        (sid, r['rid'])
                    )

    # Remove legacy subject column from worksheets now that IDs are populated
    if table_exists('worksheets'):
        # purge any remaining duplicates after migration
        c.execute(
            '''DELETE FROM worksheets WHERE rowid NOT IN (
                   SELECT MIN(rowid) FROM worksheets
                   GROUP BY student_id, subject_id, date
               )'''
        )
        removed = c.rowcount
        if column_exists('worksheets', 'subject'):
            c.execute('ALTER TABLE worksheets RENAME TO worksheets_old')
            c.execute('''CREATE TABLE worksheets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                subject_id INTEGER,
                date TEXT
            )''')
            c.execute(
                'INSERT INTO worksheets (id, student_id, subject_id, date) '
                'SELECT id, student_id, subject_id, date FROM worksheets_old'
            )
            c.execute('DROP TABLE worksheets_old')
        c.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_worksheets_unique '
            'ON worksheets(student_id, subject_id, date)'
        )
        if removed and table_exists('timetable_snapshot'):
            c.execute('DELETE FROM timetable_snapshot')

    # Rebuild remaining tables without obsolete subject name columns
    for tbl, create_sql, cols, index_sql in [
        (
            'timetable',
            '''CREATE TABLE timetable (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                group_id INTEGER,
                teacher_id INTEGER,
                subject_id INTEGER,
                slot INTEGER,
                location_id INTEGER,
                date TEXT
            )''',
            'id, student_id, group_id, teacher_id, subject_id, slot, location_id, date',
            None,
        ),
        (
            'fixed_assignments',
            '''CREATE TABLE fixed_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER,
                student_id INTEGER,
                group_id INTEGER,
                subject_id INTEGER,
                slot INTEGER
            )''',
            'id, teacher_id, student_id, group_id, subject_id, slot',
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_fixed_assignments_unique '
            'ON fixed_assignments(teacher_id, student_id, group_id, subject_id, slot)',
        ),
        (
            'attendance_log',
            '''CREATE TABLE attendance_log (
                student_id INTEGER,
                student_name TEXT,
                subject_id INTEGER,
                date TEXT
            )''',
            'student_id, student_name, subject_id, date',
            None,
        ),
    ]:
        if table_exists(tbl) and column_exists(tbl, 'subject'):
            c.execute(f'ALTER TABLE {tbl} RENAME TO {tbl}_old')
            c.execute(create_sql)
            c.execute(
                f'INSERT INTO {tbl} ({cols}) SELECT {cols} FROM {tbl}_old'
            )
            c.execute(f'DROP TABLE {tbl}_old')
            if index_sql:
                c.execute(index_sql)

    conn.commit()

    # Only insert sample data when creating a brand new database file.  If the
    # file already exists, assume any empty tables were intentionally cleared by
    # the user and leave them empty.
    if not db_exists:
        start = 8 * 60 + 30
        times = []
        for i in range(8):
            mins = start + i * 30
            times.append(f"{mins // 60:02d}:{mins % 60:02d}")
        c.execute('''INSERT INTO config (
            id, slots_per_day, slot_duration, slot_start_times,
            min_lessons, max_lessons, teacher_min_lessons, teacher_max_lessons,
            allow_repeats, max_repeats,
            prefer_consecutive, allow_consecutive, consecutive_weight,
            require_all_subjects, use_attendance_priority, attendance_weight, group_weight,
            allow_multi_teacher, balance_teacher_load, balance_weight,
            well_attend_weight, solver_time_limit
        ) VALUES (1, 8, 30, ?, 1, 4, 1, 8, 0, 2, 0, 1, 3, 1, 0, 10, 2.0, 1, 0, 1, 1, 120)''',
                  (json.dumps(times),))
        subjects = [
            ('Math', 0),
            ('English', 0),
            ('Science', 0),
            ('History', 0)
        ]
        c.executemany('INSERT INTO subjects (name, min_percentage) VALUES (?, ?)', subjects)
        c.execute('SELECT id, name FROM subjects')
        subj_map = {r['name']: r['id'] for r in c.fetchall()}
        teachers = [
            ('Teacher A', json.dumps([subj_map['Math'], subj_map['English']]), None, None),
            ('Teacher B', json.dumps([subj_map['Science']]), None, None),
            ('Teacher C', json.dumps([subj_map['History']]), None, None),
        ]
        c.executemany('INSERT INTO teachers (name, subjects, min_lessons, max_lessons) VALUES (?, ?, ?, ?)', teachers)
        students = [
            ('Student 1', json.dumps([subj_map['Math'], subj_map['English']])),
            ('Student 2', json.dumps([subj_map['Math'], subj_map['Science']])),
            ('Student 3', json.dumps([subj_map['English'], subj_map['History']])),
            ('Student 4', json.dumps([subj_map['Science'], subj_map['Math']])),
            ('Student 5', json.dumps([subj_map['History']])),
            ('Student 6', json.dumps([subj_map['English'], subj_map['Science']])),
            ('Student 7', json.dumps([subj_map['Math']])),
            ('Student 8', json.dumps([subj_map['History'], subj_map['Science']])),
            ('Student 9', json.dumps([subj_map['English']]))
        ]
        c.executemany('INSERT INTO students (name, subjects) VALUES (?, ?)', students)
    conn.commit()
    conn.close()


def dump_configuration():
    """Serialize configuration tables to a JSON-compatible dict.

    Timetables, worksheets and other runtime data are intentionally excluded so
    presets capture only the settings needed to regenerate a schedule.
    """
    conn = get_db()
    c = conn.cursor()
    data = {}
    for table in CONFIG_TABLES:
        c.execute(f'SELECT * FROM {table}')
        rows = [dict(r) for r in c.fetchall()]
        data[table] = rows
    conn.close()
    return {'version': CURRENT_PRESET_VERSION, 'data': data}


def migrate_preset(preset):
    """Upgrade preset data from older versions to CURRENT_PRESET_VERSION."""
    data = preset.get('data', {})
    for row in data.get('config', []):
        row.setdefault('solver_time_limit', 120)
    return preset


def restore_configuration(preset, overwrite=False, preset_id=None):
    """Restore configuration tables from a preset dump.

    Existing timetables and worksheet counts remain unchanged. When ``overwrite``
    is False and current configuration differs from the preset, ``False`` is
    returned so the caller can prompt the user for confirmation.
    """
    version = preset.get('version', 0)
    if version > CURRENT_PRESET_VERSION:
        raise ValueError('Preset version is newer than supported.')
    preset = migrate_preset(preset)
    conn = get_db()
    c = conn.cursor()
    if preset_id is not None:
        c.execute(
            'UPDATE config_presets SET data=?, version=? WHERE id=?',
            (json.dumps(preset['data']), CURRENT_PRESET_VERSION, preset_id),
        )
        conn.commit()
    current = dump_configuration()['data']
    if not overwrite and current != preset['data']:
        conn.close()
        return False

    # Capture teacher, group and student references before wiping tables so we
    # can preserve names for any existing timetable or attendance rows.
    c.execute('SELECT DISTINCT teacher_id FROM timetable')
    t_ids = [r['teacher_id'] for r in c.fetchall() if r['teacher_id'] is not None]
    teacher_names = {}
    if t_ids:
        placeholders = ','.join(['?'] * len(t_ids))
        c.execute(f'SELECT id, name FROM teachers WHERE id IN ({placeholders})', t_ids)
        teacher_names = {r['id']: r['name'] for r in c.fetchall()}
        c.execute(f'SELECT id, name FROM teachers_archive WHERE id IN ({placeholders})', t_ids)
        for r in c.fetchall():
            teacher_names.setdefault(r['id'], r['name'])

    c.execute('SELECT DISTINCT group_id FROM timetable')
    g_ids = [r['group_id'] for r in c.fetchall() if r['group_id'] is not None]
    group_names = {}
    if g_ids:
        placeholders = ','.join(['?'] * len(g_ids))
        c.execute(f'SELECT id, name FROM groups WHERE id IN ({placeholders})', g_ids)
        group_names = {r['id']: r['name'] for r in c.fetchall()}
        c.execute(f'SELECT id, name FROM groups_archive WHERE id IN ({placeholders})', g_ids)
        for r in c.fetchall():
            group_names.setdefault(r['id'], r['name'])

    c.execute('SELECT DISTINCT location_id FROM timetable')
    loc_ids = [r['location_id'] for r in c.fetchall() if r['location_id'] is not None]
    location_names = {}
    if loc_ids:
        placeholders = ','.join(['?'] * len(loc_ids))
        c.execute(f'SELECT id, name FROM locations WHERE id IN ({placeholders})', loc_ids)
        location_names = {r['id']: r['name'] for r in c.fetchall()}
        c.execute(f'SELECT id, name FROM locations_archive WHERE id IN ({placeholders})', loc_ids)
        for r in c.fetchall():
            location_names.setdefault(r['id'], r['name'])

    c.execute('SELECT DISTINCT subject_id FROM timetable')
    s_ids = [r['subject_id'] for r in c.fetchall() if r['subject_id'] is not None]
    c.execute('SELECT DISTINCT subject_id FROM attendance_log')
    s_ids.extend([r['subject_id'] for r in c.fetchall() if r['subject_id'] is not None and r['subject_id'] not in s_ids])
    subject_names = {}
    if s_ids:
        placeholders = ','.join(['?'] * len(s_ids))
        c.execute(f'SELECT id, name FROM subjects WHERE id IN ({placeholders})', s_ids)
        subject_names = {r['id']: r['name'] for r in c.fetchall()}
        c.execute(f'SELECT id, name FROM subjects_archive WHERE id IN ({placeholders})', s_ids)
        for r in c.fetchall():
            subject_names.setdefault(r['id'], r['name'])

    c.execute('SELECT DISTINCT student_id, student_name FROM attendance_log')
    log_students = {r['student_id']: r['student_name'] for r in c.fetchall()}

    for table in CONFIG_TABLES:
        rows = preset['data'].get(table, [])
        c.execute(f'DELETE FROM {table}')
        if rows:
            cols = rows[0].keys()
            placeholders = ','.join(['?'] * len(cols))
            for row in rows:
                c.execute(
                    f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                    [row[col] for col in cols],
                )

    # Reinsert archived teachers for any timetable references that no longer
    # resolve to an active teacher.
    for tid in t_ids:
        c.execute('SELECT 1 FROM teachers WHERE id=?', (tid,))
        if c.fetchone() is None:
            c.execute('SELECT 1 FROM teachers_archive WHERE id=?', (tid,))
            if c.fetchone() is None:
                name = teacher_names.get(tid)
                if name:
                    c.execute('INSERT INTO teachers_archive (id, name) VALUES (?, ?)', (tid, name))

    # Reinsert archived groups for timetable references that no longer resolve.
    for gid in g_ids:
        c.execute('SELECT 1 FROM groups WHERE id=?', (gid,))
        if c.fetchone() is None:
            c.execute('SELECT 1 FROM groups_archive WHERE id=?', (gid,))
            if c.fetchone() is None:
                name = group_names.get(gid)
                if name:
                    c.execute('INSERT INTO groups_archive (id, name) VALUES (?, ?)', (gid, name))

    # Reinsert archived locations referenced by timetables that no longer resolve.
    for lid in loc_ids:
        c.execute('SELECT 1 FROM locations WHERE id=?', (lid,))
        if c.fetchone() is None:
            c.execute('SELECT 1 FROM locations_archive WHERE id=?', (lid,))
            if c.fetchone() is None:
                name = location_names.get(lid)
                if name:
                    c.execute('INSERT INTO locations_archive (id, name) VALUES (?, ?)', (lid, name))

    # Reinsert archived subjects for timetable or attendance references that no longer resolve.
    for sid in set(s_ids):
        c.execute('SELECT 1 FROM subjects WHERE id=?', (sid,))
        if c.fetchone() is None:
            c.execute('SELECT 1 FROM subjects_archive WHERE id=?', (sid,))
            if c.fetchone() is None:
                name = subject_names.get(sid)
                if name:
                    c.execute('INSERT INTO subjects_archive (id, name) VALUES (?, ?)', (sid, name))

    # Ensure archived names exist for any students referenced in attendance logs.
    for sid, name in log_students.items():
        c.execute('SELECT 1 FROM students WHERE id=?', (sid,))
        if c.fetchone() is None:
            c.execute('INSERT OR IGNORE INTO students_archive (id, name) VALUES (?, ?)', (sid, name))

    conn.commit()
    conn.close()
    return True


def calculate_missing_and_counts(c, date):
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_students = {}
    for gm in gm_rows:
        group_students.setdefault(gm['group_id'], set()).add(gm['student_id'])

    c.execute('SELECT id, name, subjects, active FROM students')
    student_rows = c.fetchall()

    student_names = {s['id']: s['name'] for s in student_rows}
    c.execute('SELECT id, name FROM students_archive')
    for row in c.fetchall():
        student_names.setdefault(row['id'], row['name'])

    c.execute('SELECT id, name FROM groups')
    group_names = {row['id']: row['name'] for row in c.fetchall()}
    c.execute('SELECT id, name FROM groups_archive')
    for row in c.fetchall():
        group_names.setdefault(row['id'], row['name'])

    assigned = {s['id']: set() for s in student_rows}
    lesson_counts = {s['id']: 0 for s in student_rows}

    c.execute('SELECT id, name FROM subjects')
    subject_names = {r['id']: r['name'] for r in c.fetchall()}

    c.execute(
        'SELECT student_id, group_id, subject_id, teacher_id FROM timetable WHERE date=?',
        (date,),
    )
    lessons = c.fetchall()
    used_groups = set()
    teacher_subjects = {}
    timetable_teachers = set()
    for les in lessons:
        subj = les['subject_id']
        if subj is None:
            continue
        tid = les['teacher_id']
        if tid is not None:
            timetable_teachers.add(tid)
            if subj is not None:
                teacher_subjects.setdefault(tid, set()).add(subj)
        if les['group_id']:
            gid = les['group_id']
            used_groups.add(gid)
            for sid in group_students.get(gid, []):
                assigned.setdefault(sid, set()).add(subj)
                lesson_counts[sid] = lesson_counts.get(sid, 0) + 1
        elif les['student_id']:
            assigned.setdefault(les['student_id'], set()).add(subj)
            lesson_counts[les['student_id']] = lesson_counts.get(les['student_id'], 0) + 1

    missing = {}
    for s in student_rows:
        required = set(json.loads(s['subjects']))
        miss = required - assigned.get(s['id'], set())
        if miss:
            subj_list = []
            for subj in sorted(miss):
                sid = s['id']
                subj_name = subject_names.get(subj)
                # Count worksheets assigned (by distinct date to avoid duplicates)
                c.execute(
                    'SELECT COUNT(DISTINCT date) FROM worksheets WHERE student_id=? '
                    'AND subject_id=? AND date<=?',
                    (sid, subj, date),
                )
                worksheet_count = c.fetchone()[0]
                c.execute(
                    'SELECT 1 FROM worksheets WHERE student_id=? '
                    'AND subject_id=? AND date=?',
                    (sid, subj, date),
                )
                assigned_today = c.fetchone() is not None
                # Track worksheet counts directly to avoid conflating them with lessons
                subj_list.append({
                    'subject_id': subj,
                    'subject': subj_name or str(subj),
                    'count': worksheet_count,
                    'assigned': assigned_today,
                })
            missing[s['id']] = subj_list

    group_data = {}
    for gid in sorted(used_groups):
        members = []
        for sid in sorted(group_students.get(gid, [])):
            member_name = student_names.get(sid) or f'Student {sid}'
            members.append({'id': sid, 'name': member_name})
        group_name = group_names.get(gid) or f'Group {gid}'
        group_data[gid] = {'name': group_name, 'members': members}

    c.execute(
        '''SELECT DISTINCT t.location_id, COALESCE(l.name, la.name) AS location_name
           FROM timetable t
           LEFT JOIN locations l ON t.location_id = l.id
           LEFT JOIN locations_archive la ON t.location_id = la.id
           WHERE t.date=? AND t.location_id IS NOT NULL''',
        (date,),
    )
    location_data = {}
    for row in c.fetchall():
        location_data[row['location_id']] = {'name': row['location_name']}

    c.execute('SELECT id, name, subjects FROM teachers ORDER BY id')
    teacher_rows = c.fetchall()
    teacher_data = []
    teacher_ids = set()
    for row in teacher_rows:
        try:
            subjects = json.loads(row['subjects']) if row['subjects'] else []
        except (TypeError, ValueError, json.JSONDecodeError):
            subjects = []
        teacher_data.append({'id': row['id'], 'name': row['name'], 'subjects': subjects})
        teacher_ids.add(row['id'])

    missing_teacher_ids = sorted(timetable_teachers - teacher_ids)
    archive_names = {}
    if missing_teacher_ids:
        placeholders = ','.join(['?'] * len(missing_teacher_ids))
        c.execute(
            f'SELECT id, name FROM teachers_archive WHERE id IN ({placeholders})',
            missing_teacher_ids,
        )
        archive_names = {row['id']: row['name'] for row in c.fetchall()}
    for tid in missing_teacher_ids:
        name = archive_names.get(tid) or f'Teacher {tid}'
        subjects = sorted(teacher_subjects.get(tid, set()))
        teacher_data.append({'id': tid, 'name': name, 'subjects': subjects})

    return missing, lesson_counts, group_data, location_data, teacher_data


def get_missing_and_counts(c, date, refresh=False):
    def _parse_group_data(raw_value):
        if not raw_value:
            return {}, True
        try:
            data = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, True
        if not isinstance(data, dict):
            return {}, True
        cleaned = {}
        needs_refresh = False
        for key, info in data.items():
            try:
                gid = int(key)
            except (TypeError, ValueError):
                needs_refresh = True
                continue
            if not isinstance(info, dict):
                needs_refresh = True
                continue
            members_raw = info.get('members')
            if members_raw is None:
                needs_refresh = True
                members_raw = []
            elif not isinstance(members_raw, list):
                needs_refresh = True
                if isinstance(members_raw, (tuple, set)):
                    members_raw = list(members_raw)
                else:
                    members_raw = []
            cleaned_members = []
            for member in members_raw:
                if isinstance(member, dict):
                    if 'id' not in member:
                        needs_refresh = True
                        continue
                    try:
                        mid = int(member['id'])
                    except (TypeError, ValueError):
                        needs_refresh = True
                        continue
                    cleaned_members.append({'id': mid, 'name': member.get('name')})
                else:
                    try:
                        mid = int(member)
                    except (TypeError, ValueError):
                        needs_refresh = True
                        continue
                    cleaned_members.append({'id': mid, 'name': None})
                    needs_refresh = True
            cleaned[gid] = {'name': info.get('name'), 'members': cleaned_members}
        return cleaned, needs_refresh

    def _parse_location_data(raw_value):
        if not raw_value:
            return {}, True
        try:
            data = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}, True
        if not isinstance(data, dict):
            return {}, True
        cleaned = {}
        needs_refresh = False
        for key, info in data.items():
            try:
                lid = int(key)
            except (TypeError, ValueError):
                needs_refresh = True
                continue
            name = None
            if isinstance(info, dict):
                name = info.get('name')
                if name is not None and not isinstance(name, str):
                    needs_refresh = True
                    name = str(name)
            elif info is not None:
                needs_refresh = True
            cleaned[lid] = {'name': name}
        return cleaned, needs_refresh

    def _parse_teacher_data(raw_value):
        if not raw_value:
            return [], True
        try:
            data = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [], True
        if not isinstance(data, list):
            return [], True
        cleaned = []
        needs_refresh = False
        for entry in data:
            if not isinstance(entry, dict):
                needs_refresh = True
                continue
            tid = entry.get('id')
            try:
                tid = int(tid)
            except (TypeError, ValueError):
                needs_refresh = True
                continue
            name = entry.get('name')
            if name is not None and not isinstance(name, str):
                name = str(name)
                needs_refresh = True
            subjects_raw = entry.get('subjects')
            subjects = []
            if subjects_raw is None:
                subjects = []
            elif isinstance(subjects_raw, list):
                for subj in subjects_raw:
                    try:
                        subjects.append(int(subj))
                    except (TypeError, ValueError):
                        needs_refresh = True
            else:
                needs_refresh = True
                if isinstance(subjects_raw, (tuple, set)):
                    for subj in subjects_raw:
                        try:
                            subjects.append(int(subj))
                        except (TypeError, ValueError):
                            needs_refresh = True
                else:
                    subjects = []
            cleaned.append({'id': tid, 'name': name, 'subjects': subjects})
        return cleaned, needs_refresh

    if not refresh:
        row = c.execute(
            'SELECT missing, lesson_counts, group_data, location_data, teacher_data FROM timetable_snapshot WHERE date=?',
            (date,),
        ).fetchone()
        if row:
            needs_refresh_missing = False
            needs_refresh_counts = False
            try:
                raw_missing = json.loads(row['missing']) if row['missing'] else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_missing = {}
                needs_refresh_missing = True
            missing = {}
            if not needs_refresh_missing:
                try:
                    missing = {int(k): v for k, v in raw_missing.items()}
                except (TypeError, ValueError):
                    missing = {}
                    needs_refresh_missing = True
            if not needs_refresh_missing:
                needs_refresh_missing = any(
                    isinstance(subs, list)
                    and any('subject_id' not in item for item in subs)
                    for subs in missing.values()
                )

            try:
                raw_counts = json.loads(row['lesson_counts']) if row['lesson_counts'] else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_counts = {}
                needs_refresh_counts = True
            lesson_counts = {}
            if not needs_refresh_counts:
                try:
                    lesson_counts = {int(k): v for k, v in raw_counts.items()}
                except (TypeError, ValueError):
                    lesson_counts = {}
                    needs_refresh_counts = True

            group_data, needs_refresh_groups = _parse_group_data(row['group_data'] if 'group_data' in row.keys() else None)
            location_data, needs_refresh_locations = _parse_location_data(
                row['location_data'] if 'location_data' in row.keys() else None
            )
            teacher_data, needs_refresh_teachers = _parse_teacher_data(
                row['teacher_data'] if 'teacher_data' in row.keys() else None
            )

            if (
                needs_refresh_missing
                or needs_refresh_counts
                or needs_refresh_groups
                or needs_refresh_locations
                or needs_refresh_teachers
            ):
                missing, lesson_counts, group_data, location_data, teacher_data = calculate_missing_and_counts(c, date)
                c.execute(
                    'INSERT OR REPLACE INTO timetable_snapshot '
                    '(date, missing, lesson_counts, group_data, location_data, teacher_data) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (
                        date,
                        json.dumps(missing),
                        json.dumps(lesson_counts),
                        json.dumps(group_data),
                        json.dumps(location_data),
                        json.dumps(teacher_data),
                    ),
                )
            return missing, lesson_counts, group_data, location_data, teacher_data

    missing, lesson_counts, group_data, location_data, teacher_data = calculate_missing_and_counts(c, date)
    c.execute(
        'INSERT OR REPLACE INTO timetable_snapshot '
        '(date, missing, lesson_counts, group_data, location_data, teacher_data) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (
            date,
            json.dumps(missing),
            json.dumps(lesson_counts),
            json.dumps(group_data),
            json.dumps(location_data),
            json.dumps(teacher_data),
        ),
    )
    return missing, lesson_counts, group_data, location_data, teacher_data


@app.route('/check_timetable')
def check_timetable():
    """AJAX endpoint used on the index page.

    It checks whether a timetable already exists for the requested date and
    returns a small JSON response so the browser can warn the user.
    """
    target_date = request.args.get('date')
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT 1 FROM timetable WHERE date=? LIMIT 1', (target_date,))
    exists = c.fetchone() is not None
    conn.close()
    return {'exists': exists}


@app.route('/')
def index():
    """Render the landing page with links to the main actions.

    The page contains small forms to generate a new timetable or view an
    existing one and links to the configuration and attendance pages.
    """
    selected = request.args.get('date')
    mode = request.args.get('mode', 'teacher')
    context = {'today': date.today().isoformat(), 'view_mode': mode}
    if selected:
        data = get_timetable_data(selected, view=mode)
        (sel_date, slots, columns, grid, missing,
         student_names, slot_labels, has_rows, lesson_counts, group_data) = data
        if not has_rows:
            flash('No timetable available. Generate one from the home page.',
                  'error')
        context.update({
            'show_timetable': has_rows,
            'date': sel_date,
            'slots': slots,
            'columns': columns,
            'grid': grid,
            'missing': missing,
            'student_names': student_names,
            'slot_labels': slot_labels,
            'has_rows': has_rows,
            'json': json,
            'lesson_counts': lesson_counts,
            'group_data': group_data,
        })
    return render_template('index.html', **context)

# Helper used when validating student–teacher blocks
# Returns True if blocking is allowed, otherwise False.
def block_allowed(student_id, teacher_id, teacher_map, student_groups,
                  group_members, group_subj_map, block_map, fixed_pairs):
    """Return ``True`` if a teacher block leaves at least one teacher available.

    The configuration form lets students block certain teachers. Before adding a
    block we need to check that every subject the student's groups require still
    has another teacher who is not blocked or unavailable. ``block_map``
    represents the current set of blocks; ``fixed_pairs`` contains teacher--
    student pairs from fixed assignments which cannot be blocked. The function
    temporarily adds the proposed block and verifies another teacher remains for
    each affected subject.
    """

    if (student_id, teacher_id) in fixed_pairs:
        return False
    temp_blocks = {sid: set(tids) for sid, tids in block_map.items()}
    temp_blocks.setdefault(student_id, set()).add(teacher_id)
    for gid in student_groups.get(student_id, []):
        members = group_members.get(gid, [])
        for subj in group_subj_map.get(gid, []):
            available = []
            for tid, subs in teacher_map.items():
                if subj in subs and all(tid not in temp_blocks.get(m, set()) for m in members):
                    available.append(tid)
            if len(available) == 1 and available[0] == teacher_id:
                return False
    return True


@app.route('/config', methods=['GET', 'POST'])
def config():
    """Display and update teachers, students, groups and other settings.

    This route renders a large form when accessed via GET. Submitting the
    form via POST saves the changes back to the database after running a
    number of validation checks.
    """
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        has_error = False
        try:
            slots_per_day = int(request.form['slots_per_day'])
            slot_duration = int(request.form['slot_duration'])
        except (KeyError, TypeError, ValueError):
            flash('Slots per day and slot duration must be positive integers.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if slots_per_day < 1 or slot_duration < 1:
            flash('Slots per day and slot duration must be positive integers.', 'error')
            conn.close()
            return redirect(url_for('config'))
        start_times = []
        for i in range(1, slots_per_day + 1):
            val = request.form.get(f'slot_start_{i}')
            if not val:
                flash(f'Missing start time for slot {i}', 'error')
                has_error = True
                continue
            try:
                h, m = map(int, val.split(':'))
            except Exception:
                flash(f'Invalid time for slot {i}', 'error')
                has_error = True
                continue
            if i > 1:
                ph, pm = map(int, start_times[i - 2].split(':'))
                prev_total = ph * 60 + pm
                curr_total = h * 60 + m
                if curr_total < prev_total + slot_duration:
                    flash(f'Start time of slot {i} must be at least previous start plus slot duration', 'error')
                    has_error = True
            start_times.append(f"{h:02d}:{m:02d}")
        min_lessons = int(request.form['min_lessons'])
        max_lessons = int(request.form['max_lessons'])
        if min_lessons < 0 or max_lessons < 0:
            flash('Minimum and maximum lessons must be zero or greater.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if min_lessons > max_lessons:
            flash('Minimum lessons cannot exceed maximum lessons.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if min_lessons > slots_per_day:
            flash('Minimum lessons cannot exceed slots per day.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if max_lessons > slots_per_day:
            flash('Maximum lessons cannot exceed slots per day.', 'error')
            conn.close()
            return redirect(url_for('config'))
        t_min_lessons = int(request.form['teacher_min_lessons'])
        t_max_lessons = int(request.form['teacher_max_lessons'])
        if t_min_lessons < 0 or t_max_lessons < 0:
            flash('Global teacher minimum and maximum lessons must be zero or greater.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if t_min_lessons > t_max_lessons:
            flash('Global teacher min lessons cannot exceed max lessons.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if t_min_lessons > slots_per_day:
            flash('Global teacher minimum lessons cannot exceed slots per day.', 'error')
            conn.close()
            return redirect(url_for('config'))
        if t_max_lessons > slots_per_day:
            flash('Global teacher maximum lessons cannot exceed slots per day.', 'error')
            conn.close()
            return redirect(url_for('config'))
        allow_repeats = 1 if request.form.get('allow_repeats') else 0
        max_repeats = int(request.form['max_repeats'])
        prefer_consecutive = 1 if request.form.get('prefer_consecutive') else 0
        allow_consecutive = 1 if request.form.get('allow_consecutive') else 0
        consecutive_weight = int(request.form['consecutive_weight'])
        require_all_subjects = 1 if request.form.get('require_all_subjects') else 0
        use_attendance_priority = 1 if request.form.get('use_attendance_priority') else 0
        attendance_weight = int(request.form['attendance_weight'])
        well_attend_weight = float(request.form['well_attend_weight'])
        group_weight = float(request.form['group_weight'])
        allow_multi_teacher = 1 if request.form.get('allow_multi_teacher') else 0
        balance_teacher_load = 1 if request.form.get('balance_teacher_load') else 0
        balance_weight = int(request.form['balance_weight'])
        solver_time_limit_raw = request.form.get('solver_time_limit', '').strip()
        if solver_time_limit_raw:
            try:
                solver_time_limit = int(solver_time_limit_raw)
                if solver_time_limit <= 0:
                    raise ValueError
            except ValueError:
                flash('Solver time limit must be a positive integer', 'error')
                has_error = True
                solver_time_limit = c.execute('SELECT solver_time_limit FROM config WHERE id=1').fetchone()[0]
        else:
            solver_time_limit = c.execute('SELECT solver_time_limit FROM config WHERE id=1').fetchone()[0]

        if require_all_subjects and use_attendance_priority:
            flash(
                'Require all subjects and attendance priority may slow solving.',
                'warning'
            )

        if not allow_repeats:
            allow_consecutive = 0
            prefer_consecutive = 0
        else:
            if not allow_consecutive and prefer_consecutive:
                flash('Cannot prefer consecutive slots when consecutive repeats are disallowed.',
                      'error')
                has_error = True
            if max_repeats < 2:
                flash('Max repeats must be at least 2', 'error')
                has_error = True
        if not allow_multi_teacher and allow_repeats:
            flash('Cannot allow repeats when different teachers per subject are disallowed.', 'error')
            has_error = True

        c.execute("""UPDATE config SET slots_per_day=?, slot_duration=?, slot_start_times=?,
                     min_lessons=?, max_lessons=?, teacher_min_lessons=?, teacher_max_lessons=?,
                     allow_repeats=?, max_repeats=?,
                     prefer_consecutive=?, allow_consecutive=?, consecutive_weight=?,
                     require_all_subjects=?, use_attendance_priority=?, attendance_weight=?,
                     group_weight=?, well_attend_weight=?, allow_multi_teacher=?, balance_teacher_load=?, balance_weight=?, solver_time_limit=?
                     WHERE id=1""",
                  (slots_per_day, slot_duration, json.dumps(start_times), min_lessons,
                   max_lessons, t_min_lessons, t_max_lessons,
                   allow_repeats, max_repeats, prefer_consecutive,
                   allow_consecutive, consecutive_weight, require_all_subjects,
                   use_attendance_priority, attendance_weight, group_weight, well_attend_weight,
                   allow_multi_teacher, balance_teacher_load, balance_weight, solver_time_limit))
        # update subjects
        subj_ids = request.form.getlist('subject_id')
        deletes_sub = set(request.form.getlist('subject_delete'))
        for sid in subj_ids:
            name = request.form.get(f'subject_name_{sid}')
            min_perc = request.form.get(f'subject_min_{sid}')
            min_val = int(min_perc) if min_perc else 0
            if sid in deletes_sub:
                c.execute('SELECT name FROM subjects WHERE id=?', (int(sid),))
                row = c.fetchone()
                if row:
                    sname = row['name']
                    c.execute('SELECT id, name FROM subjects_archive WHERE name LIKE ?', (f"{sname}%",))
                    existing = c.fetchall()
                    for ex in existing:
                        if ex['name'] == sname:
                            c.execute('UPDATE subjects_archive SET name=? WHERE id=?',
                                      (f"{sname} (id {ex['id']})", ex['id']))
                    archive_name = f"{sname} (id {int(sid)})" if existing else sname
                    c.execute('INSERT OR IGNORE INTO subjects_archive (id, name) VALUES (?, ?)',
                              (int(sid), archive_name))
                c.execute('DELETE FROM subjects WHERE id=?', (int(sid),))
            else:
                c.execute('UPDATE subjects SET name=?, min_percentage=? WHERE id=?', (name, min_val, int(sid)))
        new_sub = request.form.get('new_subject_name')
        new_min = request.form.get('new_subject_min')
        if new_sub:
            min_val = int(new_min) if new_min else 0
            c.execute('INSERT INTO subjects (name, min_percentage) VALUES (?, ?)', (new_sub, min_val))

        # update teachers
        teacher_ids = request.form.getlist('teacher_id')
        deletes = set()
        for tid in teacher_ids:
            if request.form.get(f'teacher_delete_{tid}'):
                c.execute('SELECT name FROM teachers WHERE id=?', (int(tid),))
                row = c.fetchone()
                if row:
                    name = row['name']
                    c.execute('SELECT id, name FROM teachers_archive WHERE name LIKE ?', (f"{name}%",))
                    existing = c.fetchall()
                    for ex in existing:
                        if ex['name'] == name:
                            c.execute(
                                'UPDATE teachers_archive SET name=? WHERE id=?',
                                (f"{name} (id {ex['id']})", ex['id']),
                            )
                    archive_name = f"{name} (id {int(tid)})" if existing else name
                    c.execute(
                        'INSERT OR IGNORE INTO teachers_archive (id, name) VALUES (?, ?)',
                        (int(tid), archive_name),
                    )
                c.execute('DELETE FROM teachers WHERE id=?', (int(tid),))
                c.execute('DELETE FROM teacher_unavailable WHERE teacher_id=?', (int(tid),))
                c.execute('DELETE FROM student_teacher_block WHERE teacher_id=?', (int(tid),))
                c.execute('DELETE FROM fixed_assignments WHERE teacher_id=?', (int(tid),))
                deletes.add(tid)
            else:
                name = request.form.get(f'teacher_name_{tid}')
                subs = [int(x) for x in request.form.getlist(f'teacher_subjects_{tid}')]
                subj_json = json.dumps(subs)
                tmin = request.form.get(f'teacher_min_{tid}')
                tmax = request.form.get(f'teacher_max_{tid}')
                min_val = int(tmin) if tmin else None
                max_val = int(tmax) if tmax else None
                if min_val is not None and max_val is not None and min_val > max_val:
                    flash('Teacher min lessons greater than max for ' + name, 'error')
                    has_error = True
                    continue
                c.execute('UPDATE teachers SET name=?, subjects=?, min_lessons=?, max_lessons=? WHERE id=?',
                          (name, subj_json, min_val, max_val, int(tid)))
        new_tname = request.form.get('new_teacher_name')
        new_tsubs = [int(x) for x in request.form.getlist('new_teacher_subjects')]
        new_tmin = request.form.get('new_teacher_min')
        new_tmax = request.form.get('new_teacher_max')
        if new_tname and new_tsubs:
            subj_json = json.dumps(new_tsubs)
            min_val = int(new_tmin) if new_tmin else None
            max_val = int(new_tmax) if new_tmax else None
            if min_val is not None and max_val is not None and min_val > max_val:
                flash('New teacher min lessons greater than max', 'error')
                has_error = True
            else:
                c.execute('INSERT INTO teachers (name, subjects, min_lessons, max_lessons) VALUES (?, ?, ?, ?)',
                          (new_tname, subj_json, min_val, max_val))

        # load current groups and fixed assignments for block validation
        c.execute('SELECT id, subjects FROM teachers')
        trows = c.fetchall()
        teacher_map_block = {t['id']: json.loads(t['subjects']) for t in trows}
        c.execute('SELECT group_id, student_id FROM group_members')
        gm_rows = c.fetchall()
        group_members_block = {}
        student_groups_block = {}
        for gm in gm_rows:
            group_members_block.setdefault(gm['group_id'], []).append(gm['student_id'])
            student_groups_block.setdefault(gm['student_id'], []).append(gm['group_id'])
        c.execute('SELECT id, subjects FROM groups')
        g_rows = c.fetchall()
        group_subj_map_block = {g['id']: json.loads(g['subjects']) for g in g_rows}
        c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
        br_rows = c.fetchall()
        block_map_current = {}
        for r in br_rows:
            block_map_current.setdefault(r['student_id'], set()).add(r['teacher_id'])
        c.execute('SELECT teacher_id, student_id FROM fixed_assignments WHERE student_id IS NOT NULL')
        fr_rows = c.fetchall()
        fixed_pairs = {(r['student_id'], r['teacher_id']) for r in fr_rows}
        # update students
        student_ids = request.form.getlist('student_id')
        for sid in student_ids:
            if request.form.get(f'student_delete_{sid}'):
                # prevent deletion while student belongs to any group
                c.execute('''SELECT g.name FROM group_members gm
                             JOIN groups g ON gm.group_id = g.id
                             WHERE gm.student_id=?''', (int(sid),))
                rows = c.fetchall()
                if rows:
                    names = ', '.join(r['name'] for r in rows)
                    flash(f'Remove student from groups first: {names}', 'error')
                    has_error = True
                    continue
                # prevent deletion if fixed assignments exist
                c.execute('SELECT 1 FROM fixed_assignments WHERE student_id=? LIMIT 1', (int(sid),))
                if c.fetchone():
                    flash('Remove fixed assignments involving this student before deleting', 'error')
                    has_error = True
                    continue
                c.execute('SELECT name FROM students WHERE id=?', (int(sid),))
                row = c.fetchone()
                if row:
                    name = row['name']
                    c.execute('SELECT id, name FROM students_archive WHERE name LIKE ?', (f"{name}%",))
                    existing = c.fetchall()
                    for ex in existing:
                        if ex['name'] == name:
                            c.execute('UPDATE students_archive SET name=? WHERE id=?',
                                      (f"{name} (id {ex['id']})", ex['id']))
                    archive_name = f"{name} (id {int(sid)})" if existing else name
                    c.execute('INSERT OR IGNORE INTO students_archive (id, name) VALUES (?, ?)',
                              (int(sid), archive_name))
                c.execute('DELETE FROM students WHERE id=?', (int(sid),))
                c.execute('DELETE FROM student_teacher_block WHERE student_id=?', (int(sid),))
            else:
                name = request.form.get(f'student_name_{sid}')
                subs = [int(x) for x in request.form.getlist(f'student_subjects_{sid}')]
                active = 1 if request.form.get(f'student_active_{sid}') else 0
                smin = request.form.get(f'student_min_{sid}')
                smax = request.form.get(f'student_max_{sid}')
                allow_rep = 1 if request.form.get(f'student_allow_repeats_{sid}') else 0
                max_rep = request.form.get(f'student_max_repeats_{sid}')
                allow_con = 1 if request.form.get(f'student_allow_consecutive_{sid}') else 0
                prefer_con = 1 if request.form.get(f'student_prefer_consecutive_{sid}') else 0
                allow_multi = 1 if request.form.get(f'student_multi_teacher_{sid}') else 0
                rep_subs = [int(x) for x in request.form.getlist(f'student_repeat_subjects_{sid}')]
                subj_json = json.dumps(subs)
                min_val = int(smin) if smin else None
                max_val = int(smax) if smax else None
                max_rep_val = int(max_rep) if max_rep else None
                rep_sub_json = json.dumps(rep_subs) if rep_subs else None
                c.execute('''UPDATE students SET name=?, subjects=?, active=?,
                             min_lessons=?, max_lessons=?, allow_repeats=?,
                             max_repeats=?, allow_consecutive=?, prefer_consecutive=?,
                             allow_multi_teacher=?, repeat_subjects=? WHERE id=?''',
                          (name, subj_json, active, min_val, max_val,
                           allow_rep, max_rep_val, allow_con, prefer_con,
                           allow_multi, rep_sub_json, int(sid)))
                slots = request.form.getlist(f'student_unavail_{sid}')
                c.execute('DELETE FROM student_unavailable WHERE student_id=?', (int(sid),))
                for sl in slots:
                    c.execute('INSERT INTO student_unavailable (student_id, slot) VALUES (?, ?)',
                              (int(sid), int(sl)))
                blocks = request.form.getlist(f'student_block_{sid}')
                c.execute('DELETE FROM student_teacher_block WHERE student_id=?', (int(sid),))
                block_map_current[int(sid)] = set()
                for tid in blocks:
                    tval = int(tid)
                    if not block_allowed(int(sid), tval, teacher_map_block, student_groups_block,
                                           group_members_block, group_subj_map_block,
                                           block_map_current, fixed_pairs):
                        flash('Cannot block selected teacher for student', 'error')
                        has_error = True
                        continue
                    c.execute('INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
                              (int(sid), tval))
                    block_map_current.setdefault(int(sid), set()).add(tval)
        new_sname = request.form.get('new_student_name')
        new_ssubs = [int(x) for x in request.form.getlist('new_student_subjects')]
        new_blocks = request.form.getlist('new_student_block')
        new_unav = request.form.getlist('new_student_unavail')
        new_smin = request.form.get('new_student_min')
        new_smax = request.form.get('new_student_max')
        new_allow_rep = 1 if request.form.get('new_student_allow_repeats') else 0
        new_max_rep = request.form.get('new_student_max_repeats')
        new_allow_con = 1 if request.form.get('new_student_allow_consecutive') else 0
        new_prefer_con = 1 if request.form.get('new_student_prefer_consecutive') else 0
        new_allow_multi = 1 if request.form.get('new_student_multi_teacher') else 0
        new_rep_subs = [int(x) for x in request.form.getlist('new_student_repeat_subjects')]
        if new_sname and new_ssubs:
            subj_json = json.dumps(new_ssubs)
            min_val = int(new_smin) if new_smin else None
            max_val = int(new_smax) if new_smax else None
            max_rep_val = int(new_max_rep) if new_max_rep else None
            rep_sub_json = json.dumps(new_rep_subs) if new_rep_subs else None
            c.execute('''INSERT INTO students (name, subjects, active, min_lessons, max_lessons,
                      allow_repeats, max_repeats, allow_consecutive, prefer_consecutive, allow_multi_teacher, repeat_subjects)
                      VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (new_sname, subj_json, min_val, max_val, new_allow_rep,
                       max_rep_val, new_allow_con, new_prefer_con, new_allow_multi, rep_sub_json))
            new_sid = c.lastrowid
            for sl in new_unav:
                c.execute('INSERT INTO student_unavailable (student_id, slot) VALUES (?, ?)',
                          (new_sid, int(sl)))
            block_map_current[new_sid] = set()
            for tid in new_blocks:
                tval = int(tid)
                if not block_allowed(new_sid, tval, teacher_map_block, student_groups_block,
                                       group_members_block, group_subj_map_block,
                                       block_map_current, fixed_pairs):
                    flash('Cannot block selected teacher for student', 'error')
                    has_error = True
                    continue
                c.execute('INSERT INTO student_teacher_block (student_id, teacher_id) VALUES (?, ?)',
                          (new_sid, tval))
                block_map_current.setdefault(new_sid, set()).add(tval)
            for lid in request.form.getlist('new_student_locs'):
                c.execute('INSERT INTO student_locations (student_id, location_id) VALUES (?, ?)',
                          (new_sid, int(lid)))

        # Build helper maps used when validating group changes. These maps
        # describe which teachers can teach each subject, what subjects every
        # student requires and any existing teacher blocks.
        c.execute('SELECT id, subjects FROM teachers')
        trows = c.fetchall()
        teacher_map_validate = {t['id']: json.loads(t['subjects']) for t in trows}
        c.execute('SELECT id, subjects FROM students')
        srows = c.fetchall()
        student_subj_map = {s['id']: set(json.loads(s['subjects'])) for s in srows}
        c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
        block_rows = c.fetchall()
        block_map_validate = {}
        for r in block_rows:
            block_map_validate.setdefault(r['student_id'], set()).add(r['teacher_id'])

        # === Update group definitions ===
        # Every existing group is processed. We first handle deletions and then
        # validate any edits to ensure that each subject is actually required by
        # all member students and that at least one unblocked teacher can teach
        # it.
        group_ids = request.form.getlist('group_id')
        deletes_grp = set(request.form.getlist('group_delete'))
        for gid in group_ids:
            if gid in deletes_grp:
                # prevent deletion if fixed assignments exist
                c.execute('SELECT 1 FROM fixed_assignments WHERE group_id=? LIMIT 1', (int(gid),))
                if c.fetchone():
                    flash('Remove fixed assignments involving this group before deleting', 'error')
                    has_error = True
                    continue
                c.execute('SELECT name FROM groups WHERE id=?', (int(gid),))
                row = c.fetchone()
                if row:
                    c.execute('INSERT OR IGNORE INTO groups_archive (id, name) VALUES (?, ?)',
                              (int(gid), row['name']))
                c.execute('DELETE FROM groups WHERE id=?', (int(gid),))
                c.execute('DELETE FROM group_members WHERE group_id=?', (int(gid),))
                c.execute('DELETE FROM group_locations WHERE group_id=?', (int(gid),))
                continue
            name = request.form.get(f'group_name_{gid}')
            subs = [int(x) for x in request.form.getlist(f'group_subjects_{gid}')]
            members = request.form.getlist(f'group_members_{gid}')
            if not subs or not members:
                flash(f'Group {name} must have at least one subject and member', 'error')
                has_error = True
                continue
            # ``member_ids`` holds the numeric ids of all group members. We
            # verify that each subject is required by every student and that at
            # least one teacher can deliver it without violating any blocks.
            valid = True
            member_ids = [int(s) for s in members]
            for subj in subs:
                for sid in member_ids:
                    if subj not in student_subj_map.get(sid, set()):
                        flash(f'Student does not require {subj} in group {name}', 'error')
                        has_error = True
                        valid = False
                        break
                if not valid:
                    break
                ok = False
                for tid, tsubs in teacher_map_validate.items():
                    if subj in tsubs and all(tid not in block_map_validate.get(mid, set()) for mid in member_ids):
                        ok = True
                        break
                if not ok:
                    flash(f'No teacher available for {subj} in group {name}', 'error')
                    has_error = True
                    valid = False
                    break
            if not valid:
                continue
            c.execute('UPDATE groups SET name=?, subjects=? WHERE id=?',
                      (name, json.dumps(subs), int(gid)))
            c.execute('DELETE FROM group_members WHERE group_id=?', (int(gid),))
            for sid in member_ids:
                c.execute('INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
                          (int(gid), sid))
        # Handle creation of a brand new group. The same validation rules apply
        # as above: every subject must be required by all listed students and we
        # check that at least one suitable teacher remains unblocked for each
        # subject.
        ng_name = request.form.get('new_group_name')
        ng_subs = [int(x) for x in request.form.getlist('new_group_subjects')]
        ng_members = request.form.getlist('new_group_members')
        if ng_name and ng_subs and ng_members:
            member_ids = [int(s) for s in ng_members]
            valid = True
            for subj in ng_subs:
                for sid in member_ids:
                    if subj not in student_subj_map.get(sid, set()):
                        flash(f'Student does not require {subj} in group {ng_name}', 'error')
                        has_error = True
                        valid = False
                        break
                if not valid:
                    break
                ok = False
                for tid, tsubs in teacher_map_validate.items():
                    if subj in tsubs and all(tid not in block_map_validate.get(mid, set()) for mid in member_ids):
                        ok = True
                        break
                if not ok:
                    flash(f'No teacher available for {subj} in group {ng_name}', 'error')
                    has_error = True
                    valid = False
                    break
            if valid:
                c.execute('INSERT INTO groups (name, subjects) VALUES (?, ?)',
                          (ng_name, json.dumps(ng_subs)))
                gid = c.lastrowid
                for sid in member_ids:
                    c.execute('INSERT INTO group_members (group_id, student_id) VALUES (?, ?)',
                              (gid, sid))
                for lid in request.form.getlist('new_group_locs'):
                    c.execute('INSERT INTO group_locations (group_id, location_id) VALUES (?, ?)',
                              (gid, int(lid)))

        # update locations and restrictions
        loc_ids = request.form.getlist('location_id')
        del_locs = set(request.form.getlist('location_delete'))
        for lid in loc_ids:
            name = request.form.get(f'location_name_{lid}')
            if lid in del_locs:
                c.execute('SELECT name FROM locations WHERE id=?', (int(lid),))
                row = c.fetchone()
                if row:
                    loc_name = row['name']
                    c.execute('SELECT id, name FROM locations_archive WHERE name LIKE ?', (f"{loc_name}%",))
                    existing = c.fetchall()
                    for ex in existing:
                        if ex['name'] == loc_name:
                            c.execute(
                                'UPDATE locations_archive SET name=? WHERE id=?',
                                (f"{loc_name} (id {ex['id']})", ex['id']),
                            )
                    archive_name = f"{loc_name} (id {int(lid)})" if existing else loc_name
                    c.execute(
                        'INSERT OR IGNORE INTO locations_archive (id, name) VALUES (?, ?)',
                        (int(lid), archive_name),
                    )
                c.execute('DELETE FROM locations WHERE id=?', (int(lid),))
                c.execute('DELETE FROM student_locations WHERE location_id=?', (int(lid),))
                c.execute('DELETE FROM group_locations WHERE location_id=?', (int(lid),))
            else:
                c.execute('UPDATE locations SET name=? WHERE id=?', (name, int(lid)))
        new_loc = request.form.get('new_location_name')
        if new_loc:
            c.execute('INSERT INTO locations (name) VALUES (?)', (new_loc,))

        c.execute('SELECT id FROM students')
        student_ids = [r['id'] for r in c.fetchall()]
        for sid in student_ids:
            key = f'student_locs_{sid}'
            if key in request.form:
                sel = [int(x) for x in request.form.getlist(key)]
                c.execute('DELETE FROM student_locations WHERE student_id=?', (sid,))
                for lid in sel:
                    c.execute('INSERT INTO student_locations (student_id, location_id) VALUES (?, ?)', (sid, lid))

        c.execute('SELECT id FROM groups')
        group_ids = [r['id'] for r in c.fetchall()]
        for gid in group_ids:
            key = f'group_locs_{gid}'
            if key in request.form:
                sel = [int(x) for x in request.form.getlist(key)]
                c.execute('DELETE FROM group_locations WHERE group_id=?', (gid,))
                for lid in sel:
                    c.execute('INSERT INTO group_locations (group_id, location_id) VALUES (?, ?)', (gid, lid))

        # update teacher unavailability
        unavail_ids = request.form.getlist('unavail_id')
        del_unav = set(request.form.getlist('unavail_delete'))
        for uid in unavail_ids:
            if uid in del_unav:
                c.execute('DELETE FROM teacher_unavailable WHERE id=?', (int(uid),))
        nu_teachers = [int(t) for t in request.form.getlist('new_unavail_teacher')]
        nu_slots = [int(s) - 1 for s in request.form.getlist('new_unavail_slot')]

        c.execute('SELECT teacher_id, slot FROM teacher_unavailable')
        unav = c.fetchall()
        unav_set = {(u['teacher_id'], u['slot']) for u in unav}
        c.execute('SELECT teacher_id, slot FROM fixed_assignments')
        fixed = c.fetchall()
        fixed_set = {(f['teacher_id'], f['slot']) for f in fixed}

        if nu_teachers and nu_slots:
            for tid in nu_teachers:
                for slot in nu_slots:
                    if (tid, slot) in fixed_set:
                        flash('Cannot mark slot unavailable: fixed assignment exists', 'error')
                        has_error = True
                    elif (tid, slot) in unav_set:
                        flash('Teacher already unavailable in that slot', 'error')
                        has_error = True
                    else:
                        c.execute('INSERT INTO teacher_unavailable (teacher_id, slot) VALUES (?, ?)',
                                  (tid, slot))
                        unav_set.add((tid, slot))

        # update fixed assignments
        assign_ids = request.form.getlist('assign_id')
        del_assign = set(request.form.getlist('assign_delete'))
        for aid in assign_ids:
            if aid in del_assign:
                c.execute('DELETE FROM fixed_assignments WHERE id=?', (int(aid),))
        na_student = request.form.get('new_assign_student')
        na_group = request.form.get('new_assign_group')
        na_teacher = request.form.get('new_assign_teacher')
        na_subject = request.form.get('new_assign_subject')
        na_slot = request.form.get('new_assign_slot')
        # gather data for validation
        c.execute('SELECT id, name FROM subjects')
        subj_lookup = {r['name']: r['id'] for r in c.fetchall()}

        def to_subj_id(val):
            try:
                return int(val)
            except (TypeError, ValueError):
                return subj_lookup.get(val)

        def normalize_list(raw):
            result = []
            for item in json.loads(raw):
                sid = to_subj_id(item)
                if sid is not None:
                    result.append(sid)
            return result

        c.execute('SELECT id, subjects FROM teachers')
        trows = c.fetchall()
        teacher_map = {t["id"]: normalize_list(t["subjects"]) for t in trows}
        c.execute('SELECT id, subjects FROM students')
        srows = c.fetchall()
        student_map = {s["id"]: normalize_list(s["subjects"]) for s in srows}
        c.execute('SELECT id, subjects FROM groups')
        grows = c.fetchall()
        group_subj = {g["id"]: normalize_list(g["subjects"]) for g in grows}
        c.execute('SELECT teacher_id, slot FROM teacher_unavailable')
        unav = c.fetchall()
        unav_set = {(u['teacher_id'], u['slot']) for u in unav}
        c.execute('SELECT teacher_id, slot FROM fixed_assignments')
        fixed = c.fetchall()
        fixed_set = {(f['teacher_id'], f['slot']) for f in fixed}

        subj_id = to_subj_id(na_subject)
        if na_teacher and subj_id is not None and na_slot and (na_student or na_group):
            tid = int(na_teacher)
            slot = int(na_slot) - 1
            if subj_id not in teacher_map.get(tid, []):
                flash('Teacher does not teach the selected subject', 'error')
                has_error = True
            elif (tid, slot) in unav_set:
                flash('Teacher is unavailable in the selected slot', 'error')
                has_error = True
            elif (tid, slot) in fixed_set:
                flash('Duplicate fixed assignment for that slot', 'error')
                has_error = True
            elif na_group and (group_weight > 0 or not na_student):
                gid = int(na_group)
                if subj_id not in group_subj.get(gid, []):
                    flash('Group does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject_id, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, None, gid, subj_id, slot))
            else:
                sid = int(na_student)
                if subj_id not in student_map.get(sid, []):
                    flash('Student does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject_id, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, sid, None, subj_id, slot))
        elif na_teacher and (na_subject or na_slot or na_student or na_group) and subj_id is None:
            flash('Invalid subject selected', 'error')
            has_error = True

        if has_error:
            conn.rollback()
        else:
            conn.commit()
        conn.close()
        return redirect(url_for('config'))

    # load config
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    try:
        slot_times = json.loads(cfg['slot_start_times']) if cfg['slot_start_times'] else []
    except Exception:
        slot_times = []
    c.execute('SELECT * FROM teachers')
    teacher_rows = c.fetchall()
    c.execute('SELECT * FROM students')
    student_rows = c.fetchall()
    c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
    st_rows = c.fetchall()
    block_map = {}
    for r in st_rows:
        block_map.setdefault(r['student_id'], []).append(r['teacher_id'])
    c.execute('SELECT student_id, slot FROM student_unavailable')
    su_rows = c.fetchall()
    student_unavail_map = {}
    for r in su_rows:
        student_unavail_map.setdefault(r['student_id'], []).append(r['slot'])
    c.execute('SELECT * FROM subjects')
    subjects = c.fetchall()
    subj_map = {s['id']: s['name'] for s in subjects}
    c.execute('SELECT * FROM groups')
    group_rows = c.fetchall()
    group_subj_map = {g['id']: json.loads(g['subjects']) for g in group_rows}
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_map = {}
    for gm in gm_rows:
        group_map.setdefault(gm['group_id'], []).append(gm['student_id'])
    # Build mappings of subject IDs for form selections
    teacher_map = {t['id']: json.loads(t['subjects']) for t in teacher_rows}
    student_map = {s['id']: json.loads(s['subjects']) for s in student_rows}
    student_repeat_map = {s['id']: json.loads(s['repeat_subjects']) if s['repeat_subjects'] else [] for s in student_rows}
    teachers = [dict(t) for t in teacher_rows]
    students = [dict(s) for s in student_rows]
    groups = [dict(g) for g in group_rows]
    # Convert stored subject ID lists to names for display
    for t in teachers:
        t['subjects'] = json.dumps([subj_map.get(i, str(i)) for i in teacher_map.get(t['id'], [])])
    for s in students:
        s['subjects'] = json.dumps([subj_map.get(i, str(i)) for i in student_map.get(s['id'], [])])
        s['repeat_subjects'] = student_repeat_map.get(s['id'], [])
    for g in groups:
        g['subjects'] = json.dumps([subj_map.get(i, str(i)) for i in group_subj_map.get(g['id'], [])])
    c.execute('SELECT * FROM locations')
    locations = c.fetchall()
    c.execute('SELECT student_id, location_id FROM student_locations')
    sl_rows = c.fetchall()
    student_loc_map = {}
    for r in sl_rows:
        student_loc_map.setdefault(r['student_id'], []).append(r['location_id'])
    c.execute('SELECT group_id, location_id FROM group_locations')
    gl_rows = c.fetchall()
    group_loc_map = {}
    for r in gl_rows:
        group_loc_map.setdefault(r['group_id'], []).append(r['location_id'])
    c.execute('''SELECT u.id, u.teacher_id, u.slot, t.name as teacher_name
                 FROM teacher_unavailable u JOIN teachers t ON u.teacher_id = t.id''')
    unavailable = c.fetchall()
    c.execute('''SELECT a.id, a.teacher_id, a.student_id, a.group_id,
                        COALESCE(sub.name, suba.name) AS subject, a.slot,
                        t.name as teacher_name,
                        s.name as student_name,
                        COALESCE(g.name, ga.name) as group_name
                 FROM fixed_assignments a
                 JOIN teachers t ON a.teacher_id = t.id
                 LEFT JOIN subjects sub ON a.subject_id = sub.id
                 LEFT JOIN subjects_archive suba ON a.subject_id = suba.id
                 LEFT JOIN students s ON a.student_id = s.id
                 LEFT JOIN groups g ON a.group_id = g.id
                 LEFT JOIN groups_archive ga ON a.group_id = ga.id''')
    assignments = c.fetchall()
    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a['teacher_id'], []).append(a['slot'])
    unavail_map = {}
    for u in unavailable:
        unavail_map.setdefault(u['teacher_id'], []).append(u['slot'])
    c.execute('SELECT id, name FROM config_presets ORDER BY created_at DESC')
    presets = c.fetchall()
    conn.close()

    return render_template('config.html', config=cfg, teachers=teachers,
                           students=students, subjects=subjects, groups=groups,
                           locations=locations,
                           unavailable=unavailable, assignments=assignments,
                           teacher_map=teacher_map, student_map=student_map,
                           unavail_map=unavail_map, assign_map=assign_map,
                           group_map=group_map, group_subj_map=group_subj_map,
                           block_map=block_map, json=json,
                           slot_times=slot_times,
                           student_unavail_map=student_unavail_map,
                           student_loc_map=student_loc_map,
                           subject_map=subj_map,
                           group_loc_map=group_loc_map,
                           presets=presets)


@app.route('/presets', methods=['GET'])
def list_presets():
    """Return a JSON list of saved configuration presets."""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name, created_at FROM config_presets ORDER BY created_at DESC')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return {'presets': rows}


@app.route('/presets/save', methods=['POST'])
def save_preset():
    name = request.form.get('name') or datetime.now().strftime('Preset %Y-%m-%d %H:%M')
    preset = dump_configuration()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO config_presets (name, data, version, created_at) VALUES (?, ?, ?, ?)',
        (name, json.dumps(preset['data']), preset['version'], datetime.utcnow().isoformat()),
    )
    conn.commit()
    # enforce maximum of MAX_PRESETS presets
    c.execute('SELECT id FROM config_presets ORDER BY created_at DESC')
    rows = c.fetchall()
    for r in rows[MAX_PRESETS:]:
        c.execute('DELETE FROM config_presets WHERE id=?', (r['id'],))
    conn.commit()
    conn.close()
    flash('Preset saved.', 'info')
    return redirect(url_for('config'))


@app.route('/presets/load', methods=['POST'])
def load_preset():
    preset_id = request.form.get('preset_id')
    overwrite = bool(request.form.get('overwrite'))
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT data, version FROM config_presets WHERE id=?', (preset_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash('Preset not found.', 'error')
        return redirect(url_for('config'))
    preset = {'version': row['version'], 'data': json.loads(row['data'])}
    ok = restore_configuration(preset, overwrite=overwrite, preset_id=preset_id)
    if not ok:
        flash('Preset differs from current data. Confirm overwrite to load.', 'warning')
    else:
        flash('Preset loaded.', 'info')
    return redirect(url_for('config'))


@app.route('/presets/delete', methods=['POST'])
def delete_preset():
    preset_id = request.form.get('preset_id')
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM config_presets WHERE id=?', (preset_id,))
    conn.commit()
    conn.close()
    flash('Preset deleted.', 'info')
    return redirect(url_for('config'))



UNSAT_REASON_MAP = {
    'teacher_availability': 'A teacher is unavailable or blocked for a required lesson.',
    'teacher_limits': 'Teacher lesson limits are too strict.',
    'student_limits': 'Student lesson or subject requirements conflict.',
    'repeat_restrictions': 'Repeat or consecutive lesson restrictions prevent a schedule.',
    'fixed_assignment': 'A fixed assignment could not be satisfied.',
    'location_restriction': 'Location restrictions prevent required lessons.',
}


def _format_entity(prefix, name, identifier):
    if name and identifier is not None:
        return f"{prefix}={name} (id={identifier})"
    if name:
        return f"{prefix}={name}"
    if identifier is not None:
        return f"{prefix}_id={identifier}"
    return None


def _format_subject_value(name, identifier):
    if name and identifier is not None:
        if str(name) != str(identifier):
            return f"{name} (id={identifier})"
        return str(name)
    if name:
        return str(name)
    if identifier is not None:
        return str(identifier)
    return None


def _compute_slot_label_map(slot_count, slot_times, slot_duration):
    labels = {}
    last_start = None
    for idx in range(slot_count):
        if idx < len(slot_times):
            try:
                hours, minutes = map(int, str(slot_times[idx]).split(':'))
                start = hours * 60 + minutes
            except Exception:
                start = (last_start + slot_duration) if last_start is not None else 8 * 60 + 30
        else:
            start = (last_start + slot_duration) if last_start is not None else 8 * 60 + 30
        end = start + slot_duration
        labels[idx] = f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}"
        last_start = start
    return labels


def _format_list(prefix, values):
    if not values:
        return None
    return f"{prefix}=" + ','.join(str(v) for v in values)


def _format_slot_list(prefix, slots, slot_labels):
    if not slots:
        return None
    formatted = []
    for slot in sorted(slots):
        label = slot_labels.get(slot)
        if label:
            formatted.append(f"{slot} ({label})")
        else:
            formatted.append(str(slot))
    return f"{prefix}=" + ', '.join(formatted)


def _format_pairs(pairs):
    formatted = []
    for student, subject in pairs:
        if not student and subject is None:
            continue
        if student and subject is not None:
            formatted.append(f"{student}/{subject}")
        elif student:
            formatted.append(str(student))
        elif subject is not None:
            formatted.append(str(subject))
    return formatted


def _format_teacher_list(teachers):
    formatted = []
    for name, tid in teachers:
        if name and tid is not None:
            formatted.append(f"{name} (id={tid})")
        elif name:
            formatted.append(str(name))
        elif tid is not None:
            formatted.append(f"id={tid}")
    return formatted


def _summarize_teacher_availability(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        teacher_id = context.get('teacher_id')
        if teacher_id is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        entry = groups.setdefault(teacher_id, {
            'teacher_name': context.get('teacher_name'),
            'capacity_infos': [],
            'block_infos': [],
            'other_infos': [],
        })
        if context.get('teacher_name') and not entry.get('teacher_name'):
            entry['teacher_name'] = context['teacher_name']
        label = getattr(info, 'label', '') or ''
        if label.startswith('teacher_slot_'):
            entry['capacity_infos'].append(info)
        elif label.startswith('block_'):
            entry['block_infos'].append(info)
        else:
            entry['other_infos'].append(info)
    summaries = []
    for teacher_id, entry in groups.items():
        teacher_name = entry.get('teacher_name')
        if entry['capacity_infos']:
            slots = []
            slot_candidates = {}
            slot_labels = {}
            for info in entry['capacity_infos']:
                ctx = getattr(info, 'context', {}) or {}
                slot = ctx.get('slot')
                if slot is not None and slot not in slots:
                    slots.append(slot)
                candidate = ctx.get('candidate_lessons')
                if slot is not None and candidate is not None and slot not in slot_candidates:
                    slot_candidates[slot] = candidate
                label = ctx.get('slot_label')
                if slot is not None and label and slot not in slot_labels:
                    slot_labels[slot] = label
            summaries.append({
                'kind': 'teacher_availability',
                'aggregated': True,
                'category': 'capacity',
                'teacher_id': teacher_id,
                'teacher_name': teacher_name,
                'slots': slots,
                'slot_candidates': slot_candidates,
                'slot_labels': slot_labels,
                'label': getattr(entry['capacity_infos'][0], 'label', ''),
                'infos': list(entry['capacity_infos']),
            })
        if entry['block_infos']:
            slots = []
            pairs = []
            reasons = []
            slot_labels = {}
            for info in entry['block_infos']:
                ctx = getattr(info, 'context', {}) or {}
                slot = ctx.get('slot')
                if slot is not None and slot not in slots:
                    slots.append(slot)
                student_id = ctx.get('student_id')
                student_name = ctx.get('student_name')
                student_label = student_name or (f"Student {student_id}" if student_id is not None else None)
                subject_label = _format_subject_value(ctx.get('subject_name'), ctx.get('subject'))
                if student_label or subject_label is not None:
                    pair = (student_label, subject_label)
                    if pair not in pairs:
                        pairs.append(pair)
                for reason in ctx.get('reasons') or []:
                    if reason and reason not in reasons:
                        reasons.append(reason)
                label = ctx.get('slot_label')
                if slot is not None and label and slot not in slot_labels:
                    slot_labels[slot] = label
            summaries.append({
                'kind': 'teacher_availability',
                'aggregated': True,
                'category': 'block',
                'teacher_id': teacher_id,
                'teacher_name': teacher_name,
                'slots': slots,
                'pairs': pairs,
                'reasons': reasons,
                'slot_labels': slot_labels,
                'label': getattr(entry['block_infos'][0], 'label', ''),
                'infos': list(entry['block_infos']),
            })
        for info in entry['other_infos']:
            summaries.append({'aggregated': False, 'info': info})
    summaries.extend(fallback)
    return summaries


def _summarize_student_limits(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        student_id = context.get('student_id')
        if student_id is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        entry = groups.setdefault(student_id, {
            'student_name': context.get('student_name'),
            'slots': [],
            'blocked_slots': [],
            'subjects': [],
            'min_lessons': None,
            'max_lessons': None,
            'lesson_options': [],
            'candidate_lessons': [],
            'reasons': [],
            'infos': [],
        })
        if context.get('student_name') and not entry['student_name']:
            entry['student_name'] = context['student_name']
        entry['infos'].append(info)
        slot = context.get('slot')
        label = getattr(info, 'label', '') or ''
        if slot is not None and slot not in entry['slots']:
            entry['slots'].append(slot)
        if label.startswith('student_block_') and slot is not None and slot not in entry['blocked_slots']:
            entry['blocked_slots'].append(slot)
        subject_label = _format_subject_value(context.get('subject_name'), context.get('subject'))
        if subject_label and subject_label not in entry['subjects']:
            entry['subjects'].append(subject_label)
        if context.get('min_lessons') is not None:
            entry['min_lessons'] = context['min_lessons']
        if context.get('max_lessons') is not None:
            entry['max_lessons'] = context['max_lessons']
        if context.get('lesson_options') is not None and context['lesson_options'] not in entry['lesson_options']:
            entry['lesson_options'].append(context['lesson_options'])
        if context.get('candidate_lessons') is not None and context['candidate_lessons'] not in entry['candidate_lessons']:
            entry['candidate_lessons'].append(context['candidate_lessons'])
        reason = context.get('reason')
        if reason and reason not in entry['reasons']:
            entry['reasons'].append(reason)
    summaries = []
    for student_id, entry in groups.items():
        summaries.append({
            'kind': 'student_limits',
            'aggregated': True,
            'student_id': student_id,
            'student_name': entry['student_name'],
            'slots': entry['slots'],
            'blocked_slots': entry['blocked_slots'],
            'subjects': entry['subjects'],
            'min_lessons': entry['min_lessons'],
            'max_lessons': entry['max_lessons'],
            'lesson_options': entry['lesson_options'],
            'candidate_lessons': entry['candidate_lessons'],
            'reasons': entry['reasons'],
            'label': getattr(entry['infos'][0], 'label', ''),
            'infos': entry['infos'],
        })
    summaries.extend(fallback)
    return summaries


def _summarize_repeat_restrictions(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        student_id = context.get('student_id')
        subject = context.get('subject')
        if student_id is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        key = (student_id, subject)
        entry = groups.setdefault(key, {
            'student_name': context.get('student_name'),
            'subject_name': context.get('subject_name'),
            'teachers': [],
            'slots': [],
            'repeat_limit': None,
            'reasons': [],
            'infos': [],
        })
        if context.get('student_name') and not entry['student_name']:
            entry['student_name'] = context['student_name']
        if context.get('subject_name') and not entry.get('subject_name'):
            entry['subject_name'] = context['subject_name']
        entry['infos'].append(info)
        teacher_id = context.get('teacher_id')
        teacher_name = context.get('teacher_name')
        if teacher_id is not None or teacher_name:
            label = (teacher_name, teacher_id)
            if label not in entry['teachers']:
                entry['teachers'].append(label)
        for tid in context.get('teacher_ids') or []:
            label = (None, tid)
            if label not in entry['teachers']:
                entry['teachers'].append(label)
        slot = context.get('slot')
        if slot is not None and slot not in entry['slots']:
            entry['slots'].append(slot)
        if context.get('repeat_limit') is not None:
            entry['repeat_limit'] = context['repeat_limit']
        reason = context.get('reason')
        if reason and reason not in entry['reasons']:
            entry['reasons'].append(reason)
    summaries = []
    for (student_id, subject), entry in groups.items():
        summaries.append({
            'kind': 'repeat_restrictions',
            'aggregated': True,
            'student_id': student_id,
            'student_name': entry['student_name'],
            'subject': subject,
            'subject_name': entry.get('subject_name'),
            'teachers': entry['teachers'],
            'slots': entry['slots'],
            'repeat_limit': entry['repeat_limit'],
            'reasons': entry['reasons'],
            'label': getattr(entry['infos'][0], 'label', ''),
            'infos': entry['infos'],
        })
    summaries.extend(fallback)
    return summaries


def _summarize_teacher_limits(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        teacher_id = context.get('teacher_id')
        if teacher_id is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        entry = groups.setdefault(teacher_id, {
            'teacher_name': context.get('teacher_name'),
            'min_lessons': None,
            'max_lessons': None,
            'infos': [],
        })
        if context.get('teacher_name') and not entry['teacher_name']:
            entry['teacher_name'] = context['teacher_name']
        entry['infos'].append(info)
        if context.get('min_lessons') is not None:
            entry['min_lessons'] = context['min_lessons']
        if context.get('max_lessons') is not None:
            entry['max_lessons'] = context['max_lessons']
    summaries = []
    for teacher_id, entry in groups.items():
        summaries.append({
            'kind': 'teacher_limits',
            'aggregated': True,
            'teacher_id': teacher_id,
            'teacher_name': entry['teacher_name'],
            'min_lessons': entry['min_lessons'],
            'max_lessons': entry['max_lessons'],
            'label': getattr(entry['infos'][0], 'label', ''),
            'infos': entry['infos'],
        })
    summaries.extend(fallback)
    return summaries


def _summarize_fixed_assignments(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        student_id = context.get('student_id')
        teacher_id = context.get('teacher_id')
        subject = context.get('subject')
        if student_id is None and teacher_id is None and subject is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        key = (student_id, teacher_id, subject)
        entry = groups.setdefault(key, {
            'student_name': context.get('student_name'),
            'teacher_name': context.get('teacher_name'),
            'subject_name': context.get('subject_name'),
            'slots': [],
            'infos': [],
        })
        if context.get('student_name') and not entry['student_name']:
            entry['student_name'] = context['student_name']
        if context.get('teacher_name') and not entry['teacher_name']:
            entry['teacher_name'] = context['teacher_name']
        if context.get('subject_name') and not entry.get('subject_name'):
            entry['subject_name'] = context['subject_name']
        entry['infos'].append(info)
        slot = context.get('slot')
        if slot is not None and slot not in entry['slots']:
            entry['slots'].append(slot)
    summaries = []
    for (student_id, teacher_id, subject), entry in groups.items():
        summaries.append({
            'kind': 'fixed_assignment',
            'aggregated': True,
            'student_id': student_id,
            'student_name': entry['student_name'],
            'teacher_id': teacher_id,
            'teacher_name': entry['teacher_name'],
            'subject': subject,
            'subject_name': entry.get('subject_name'),
            'slots': entry['slots'],
            'label': getattr(entry['infos'][0], 'label', ''),
            'infos': entry['infos'],
        })
    summaries.extend(fallback)
    return summaries


def _summarize_location_restrictions(infos):
    groups = OrderedDict()
    fallback = []
    for info in infos:
        context = getattr(info, 'context', {}) or {}
        student_id = context.get('student_id')
        teacher_id = context.get('teacher_id')
        subject = context.get('subject')
        if student_id is None and teacher_id is None and subject is None:
            fallback.append({'aggregated': False, 'info': info})
            continue
        key = (student_id, teacher_id, subject)
        entry = groups.setdefault(key, {
            'student_name': context.get('student_name'),
            'teacher_name': context.get('teacher_name'),
            'subject_name': context.get('subject_name'),
            'slots': [],
            'allowed_locations': context.get('allowed_locations'),
            'infos': [],
        })
        if context.get('student_name') and not entry['student_name']:
            entry['student_name'] = context['student_name']
        if context.get('teacher_name') and not entry['teacher_name']:
            entry['teacher_name'] = context['teacher_name']
        if context.get('subject_name') and not entry.get('subject_name'):
            entry['subject_name'] = context['subject_name']
        entry['infos'].append(info)
        slot = context.get('slot')
        if slot is not None and slot not in entry['slots']:
            entry['slots'].append(slot)
        if context.get('allowed_locations') is not None:
            entry['allowed_locations'] = context['allowed_locations']
    summaries = []
    for (student_id, teacher_id, subject), entry in groups.items():
        summaries.append({
            'kind': 'location_restriction',
            'aggregated': True,
            'student_id': student_id,
            'student_name': entry['student_name'],
            'teacher_id': teacher_id,
            'teacher_name': entry['teacher_name'],
            'subject': subject,
            'subject_name': entry.get('subject_name'),
            'slots': entry['slots'],
            'allowed_locations': entry['allowed_locations'],
            'label': getattr(entry['infos'][0], 'label', ''),
            'infos': entry['infos'],
        })
    summaries.extend(fallback)
    return summaries


_UNSAT_SUMMARY_HANDLERS = {
    'teacher_availability': _summarize_teacher_availability,
    'student_limits': _summarize_student_limits,
    'repeat_restrictions': _summarize_repeat_restrictions,
    'teacher_limits': _summarize_teacher_limits,
    'fixed_assignment': _summarize_fixed_assignments,
    'location_restriction': _summarize_location_restrictions,
}


def summarize_unsat_core(core):
    if not core:
        return []
    sequence = []
    grouped = {}
    for info in core:
        if isinstance(info, AssumptionInfo):
            kind = getattr(info, 'kind', None)
        else:
            sequence.append(('info', info))
            continue
        if kind in _UNSAT_SUMMARY_HANDLERS:
            if kind not in grouped:
                grouped[kind] = []
                sequence.append(('kind', kind))
            grouped[kind].append(info)
        else:
            sequence.append(('info', info))
    summaries = []
    for kind, value in sequence:
        if kind == 'kind':
            summaries.extend(_UNSAT_SUMMARY_HANDLERS[value](grouped[value]))
        else:
            summaries.append({'aggregated': False, 'info': value})
    return summaries


def _format_summary_details(summary):
    kind = summary.get('kind')
    details = []
    if kind == 'teacher_availability':
        teacher_detail = _format_entity('teacher', summary.get('teacher_name'), summary.get('teacher_id'))
        if teacher_detail:
            details.append(teacher_detail)
        if summary.get('category') == 'capacity':
            slot_labels = summary.get('slot_labels') or {}
            slots_detail = _format_slot_list('slots', summary.get('slots'), slot_labels)
            if slots_detail:
                details.append(slots_detail)
            slot_candidates = summary.get('slot_candidates') or {}
            if slot_candidates:
                candidate_details = []
                for slot in sorted(slot_candidates):
                    count = slot_candidates[slot]
                    label = slot_labels.get(slot)
                    slot_text = f"slot {slot}"
                    if label:
                        slot_text = f"{slot_text} ({label})"
                    noun = 'lesson' if count == 1 else 'lessons'
                    candidate_details.append(f"{slot_text} has {count} candidate {noun}")
                if candidate_details:
                    details.append('slot demand: ' + '; '.join(candidate_details))
        elif summary.get('category') == 'block':
            slot_labels = summary.get('slot_labels') or {}
            slots_detail = _format_slot_list('blocked_slots', summary.get('slots'), slot_labels)
            if slots_detail:
                details.append(slots_detail)
            pair_labels = _format_pairs(summary.get('pairs', []))
            if pair_labels:
                details.append("students=" + ', '.join(pair_labels))
            reasons = summary.get('reasons')
            if reasons:
                details.append("reasons=" + ', '.join(reasons))
    elif kind == 'student_limits':
        student_detail = _format_entity('student', summary.get('student_name'), summary.get('student_id'))
        if student_detail:
            details.append(student_detail)
        slots_detail = _format_list('slots', summary.get('slots'))
        if slots_detail:
            details.append(slots_detail)
        blocked_detail = _format_list('blocked_slots', summary.get('blocked_slots'))
        if blocked_detail:
            details.append(blocked_detail)
        subject_detail = _format_list('subjects', summary.get('subjects'))
        if subject_detail:
            details.append(subject_detail)
        min_lessons = summary.get('min_lessons')
        max_lessons = summary.get('max_lessons')
        if min_lessons is not None or max_lessons is not None:
            details.append(
                f"lesson_limits=min:{min_lessons if min_lessons is not None else '-'}, max:{max_lessons if max_lessons is not None else '-'}"
            )
        lesson_options = summary.get('lesson_options')
        if lesson_options:
            details.append("lesson_options=" + ', '.join(str(v) for v in lesson_options))
        candidate_lessons = summary.get('candidate_lessons')
        if candidate_lessons:
            details.append("candidate_lessons=" + ', '.join(str(v) for v in candidate_lessons))
        reasons = summary.get('reasons')
        if reasons:
            details.append("reasons=" + ', '.join(reasons))
    elif kind == 'repeat_restrictions':
        student_detail = _format_entity('student', summary.get('student_name'), summary.get('student_id'))
        if student_detail:
            details.append(student_detail)
        subject_label = _format_subject_value(summary.get('subject_name'), summary.get('subject'))
        if subject_label is not None:
            details.append(f"subject={subject_label}")
        teacher_labels = _format_teacher_list(summary.get('teachers', []))
        if teacher_labels:
            details.append("teachers=" + ', '.join(teacher_labels))
        slots_detail = _format_list('slots', summary.get('slots'))
        if slots_detail:
            details.append(slots_detail)
        repeat_limit = summary.get('repeat_limit')
        if repeat_limit is not None:
            details.append(f"repeat_limit={repeat_limit}")
        reasons = summary.get('reasons')
        if reasons:
            details.append("reasons=" + ', '.join(reasons))
    elif kind == 'teacher_limits':
        teacher_detail = _format_entity('teacher', summary.get('teacher_name'), summary.get('teacher_id'))
        if teacher_detail:
            details.append(teacher_detail)
        min_lessons = summary.get('min_lessons')
        max_lessons = summary.get('max_lessons')
        if min_lessons is not None:
            details.append(f"min_lessons={min_lessons}")
        if max_lessons is not None:
            details.append(f"max_lessons={max_lessons}")
    elif kind == 'fixed_assignment':
        student_detail = _format_entity('student', summary.get('student_name'), summary.get('student_id'))
        if student_detail:
            details.append(student_detail)
        teacher_detail = _format_entity('teacher', summary.get('teacher_name'), summary.get('teacher_id'))
        if teacher_detail:
            details.append(teacher_detail)
        subject_label = _format_subject_value(summary.get('subject_name'), summary.get('subject'))
        if subject_label is not None:
            details.append(f"subject={subject_label}")
        slots_detail = _format_list('slots', summary.get('slots'))
        if slots_detail:
            details.append(slots_detail)
    elif kind == 'location_restriction':
        student_detail = _format_entity('student', summary.get('student_name'), summary.get('student_id'))
        if student_detail:
            details.append(student_detail)
        teacher_detail = _format_entity('teacher', summary.get('teacher_name'), summary.get('teacher_id'))
        if teacher_detail:
            details.append(teacher_detail)
        subject_label = _format_subject_value(summary.get('subject_name'), summary.get('subject'))
        if subject_label is not None:
            details.append(f"subject={subject_label}")
        slots_detail = _format_list('slots', summary.get('slots'))
        if slots_detail:
            details.append(slots_detail)
        allowed_locations = summary.get('allowed_locations')
        if allowed_locations is not None:
            if isinstance(allowed_locations, (list, tuple, set)):
                locs = ', '.join(str(v) for v in allowed_locations)
            else:
                locs = str(allowed_locations)
            details.append(f"allowed_locations={locs}")
    return details

def generate_schedule(target_date=None):
    """Create and solve the CP-SAT model, then save the timetable.

    All configuration data is loaded from the database and translated into
    the variables and constraints needed by OR-Tools. After solving, the
    resulting lessons are inserted into the timetable table along with
    attendance information.
    """
    conn = get_db()
    c = conn.cursor()
    if target_date is None:
        target_date = date.today().isoformat()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']
    slot_duration = cfg['slot_duration']
    try:
        slot_times = json.loads(cfg['slot_start_times']) if cfg['slot_start_times'] else []
    except Exception:
        slot_times = []
    slot_label_map = _compute_slot_label_map(slots, slot_times, slot_duration)
    min_lessons = cfg['min_lessons']
    max_lessons = cfg['max_lessons']
    teacher_min = cfg['teacher_min_lessons']
    teacher_max = cfg['teacher_max_lessons']
    solver_time_limit = cfg['solver_time_limit']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()

    c.execute('SELECT * FROM students WHERE active=1')
    students = c.fetchall()
    c.execute('SELECT * FROM groups')
    groups = c.fetchall()
    c.execute('SELECT id, name FROM subjects')
    subject_rows = c.fetchall()
    subject_lookup = {row['id']: row['name'] for row in subject_rows}
    c.execute('SELECT id, name FROM subjects_archive')
    for row in c.fetchall():
        if row['id'] not in subject_lookup:
            subject_lookup[row['id']] = row['name']
    c.execute('SELECT id, name FROM students')
    name_rows = c.fetchall()
    student_name_map = {r['id']: r['name'] for r in name_rows}
    offset = 10000
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_members = {}
    for gm in gm_rows:
        group_members.setdefault(gm['group_id'], []).append(gm['student_id'])
    group_map_offset = {offset + gid: members for gid, members in group_members.items()}


    group_subjects = {g['id']: json.loads(g['subjects']) for g in groups}
    student_groups = {}
    for gid, members in group_members.items():
        for sid in members:
            student_groups.setdefault(sid, []).append(gid)
    c.execute('SELECT * FROM teacher_unavailable')
    unavailable = c.fetchall()
    c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
    block_rows = c.fetchall()
    block_map_sched = {}
    for r in block_rows:
        block_map_sched.setdefault(r['student_id'], set()).add(r['teacher_id'])

    for gid, members in group_members.items():
        union = set()
        for m in members:
            union.update(block_map_sched.get(m, set()))
        if union:
            block_map_sched[offset + gid] = union
    c.execute('SELECT student_id, slot FROM student_unavailable')
    su_rows = c.fetchall()
    student_unavailable = {}
    for r in su_rows:
        student_unavailable.setdefault(r['student_id'], set()).add(r['slot'])
    c.execute('SELECT * FROM fixed_assignments')
    arows = c.fetchall()
    assignments_fixed = []
    for r in arows:
        row = dict(r)
        if row.get('group_id'):
            row['student_id'] = offset + row['group_id']
        assignments_fixed.append(row)

    c.execute('SELECT id FROM locations')
    locations = [r['id'] for r in c.fetchall()]
    c.execute('SELECT student_id, location_id FROM student_locations')
    sl_rows = c.fetchall()
    student_loc_map = {}
    for r in sl_rows:
        student_loc_map.setdefault(r['student_id'], set()).add(r['location_id'])
    c.execute('SELECT group_id, location_id FROM group_locations')
    gl_rows = c.fetchall()
    group_loc_map = {}
    for r in gl_rows:
        group_loc_map.setdefault(r['group_id'], set()).add(r['location_id'])

    # clear previous timetable, attendance logs, worksheet assignments, and snapshot for the target date
    c.execute('DELETE FROM timetable WHERE date=?', (target_date,))
    c.execute('DELETE FROM attendance_log WHERE date=?', (target_date,))
    c.execute('DELETE FROM worksheets WHERE date=?', (target_date,))
    c.execute('DELETE FROM timetable_snapshot WHERE date=?', (target_date,))

    # Build and solve CP-SAT model
    allow_repeats = bool(cfg['allow_repeats'])
    max_repeats = cfg['max_repeats']
    prefer_consecutive = bool(cfg['prefer_consecutive'])
    allow_consecutive = bool(cfg['allow_consecutive'])
    consecutive_weight = cfg['consecutive_weight']
    require_all_subjects = bool(cfg['require_all_subjects'])
    use_attendance_priority = bool(cfg['use_attendance_priority'])
    attendance_weight = cfg['attendance_weight']
    group_weight = cfg['group_weight']
    well_attend_weight = cfg['well_attend_weight']
    allow_multi_teacher = bool(cfg['allow_multi_teacher'])
    balance_teacher_load = bool(cfg['balance_teacher_load'])
    balance_weight = cfg['balance_weight']
    student_limits = {}
    student_repeat = {}
    student_multi = {}
    for s in students:
        sid = s['id']
        student_limits[sid] = (
            s['min_lessons'] if s['min_lessons'] is not None else min_lessons,
            s['max_lessons'] if s['max_lessons'] is not None else max_lessons)
        repeat_raw = s['repeat_subjects']
        repeat_list = None
        if repeat_raw:
            try:
                parsed = json.loads(repeat_raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, list):
                cleaned = []
                for value in parsed:
                    try:
                        cleaned.append(int(value))
                    except (TypeError, ValueError):
                        app.logger.warning(
                            'Ignoring non-numeric repeat subject %r for student %s',
                            value,
                            sid,
                        )
                repeat_list = cleaned or None
            elif parsed is not None:
                app.logger.warning(
                    'Unexpected repeat_subjects value for student %s: %r',
                    sid,
                    parsed,
                )
        student_repeat[sid] = {
            'allow_repeats': bool(s['allow_repeats']) if s['allow_repeats'] is not None else allow_repeats,
            'max_repeats': s['max_repeats'] if s['max_repeats'] is not None else max_repeats,
            'allow_consecutive': bool(s['allow_consecutive']) if s['allow_consecutive'] is not None else allow_consecutive,
            'prefer_consecutive': bool(s['prefer_consecutive']) if s['prefer_consecutive'] is not None else prefer_consecutive,
            'repeat_subjects': repeat_list,
        }
        student_multi[sid] = bool(s['allow_multi_teacher']) if s['allow_multi_teacher'] is not None else allow_multi_teacher
    # Build the CP-SAT model with assumption literals so that we can obtain
    # an unsat core explaining conflicts when no timetable exists.
    # incorporate groups as pseudo students
    pseudo_students = []
    for g in groups:
        ps = {
            "id": offset + g['id'],
            "subjects": g['subjects'],
            "name": g['name'],
        }
        pseudo_students.append(ps)

    actual_students = [dict(s) for s in students]
    full_students = actual_students + pseudo_students

    subject_weights = {}
    if use_attendance_priority:
        c.execute('SELECT id, min_percentage FROM subjects')
        min_map = {r['id']: r['min_percentage'] or 0 for r in c.fetchall()}
        attendance_pct = {}
        for s in students:
            sid = s['id']
            required = json.loads(s['subjects'])
            c.execute('SELECT subject_id, COUNT(*) as cnt FROM attendance_log WHERE student_id=? GROUP BY subject_id', (sid,))
            rows = c.fetchall()
            total = sum(r['cnt'] for r in rows)
            counts = {r['subject_id']: r['cnt'] for r in rows}
            for subj in required:
                perc = (counts.get(subj, 0) / total * 100) if total else 0
                attendance_pct.setdefault(sid, {})[subj] = perc
                min_val = min_map.get(subj, 0)
                if perc < min_val and min_val > 0:
                    deficit = (min_val - perc) / min_val
                    weight = well_attend_weight + attendance_weight * deficit
                else:
                    weight = well_attend_weight
                subject_weights[(sid, subj)] = weight
        for g in groups:
            gid = g['id']
            gsubs = json.loads(g['subjects'])
            members = group_members.get(gid, [])
            for subj in gsubs:
                percs = [attendance_pct.get(m, {}).get(subj, 0) for m in members]
                if percs:
                    med = statistics.median(sorted(percs))
                else:
                    med = 0
                min_val = min_map.get(subj, 0)
                if med < min_val and min_val > 0:
                    deficit = (min_val - med) / min_val
                    weight = well_attend_weight + attendance_weight * deficit
                else:
                    weight = well_attend_weight
                subject_weights[(offset + gid, subj)] = weight

    loc_restrict = {}
    for sid, locs in student_loc_map.items():
        loc_restrict[sid] = locs
    for gid, locs in group_loc_map.items():
        loc_restrict[offset + gid] = locs

    model, vars_, loc_vars, assumption_registry = build_model(
        full_students, teachers, slots, min_lessons, max_lessons,
        allow_repeats=allow_repeats, max_repeats=max_repeats,
        prefer_consecutive=prefer_consecutive, allow_consecutive=allow_consecutive,
        consecutive_weight=consecutive_weight,
        unavailable=unavailable, fixed=assignments_fixed,
        teacher_min_lessons=teacher_min, teacher_max_lessons=teacher_max,
        add_assumptions=True, group_members=group_map_offset,
        require_all_subjects=require_all_subjects,
        subject_weights=subject_weights,
        group_weight=group_weight,
        allow_multi_teacher=allow_multi_teacher,
        balance_teacher_load=balance_teacher_load,
        balance_weight=balance_weight,
        blocked=block_map_sched,
        student_limits=student_limits,
        student_repeat=student_repeat,
        student_unavailable=student_unavailable,
        student_multi_teacher=student_multi,
        locations=locations,
        location_restrict=loc_restrict,
        subject_lookup=subject_lookup,
        slot_labels=slot_label_map)

    progress_messages = []

    def progress_cb(msg):
        progress_messages.append(msg)
        app.logger.info(msg)

    status, assignments, core, progress = solve_and_print(
        model,
        vars_,
        loc_vars,
        assumption_registry,
        time_limit=solver_time_limit,
        progress_callback=progress_cb,
    )

    from ortools.sat.python import cp_model
    if status == cp_model.OPTIMAL:
        flash('Optimal timetable found.', 'success')
    elif status == cp_model.FEASIBLE:
        flash('Feasible timetable found before time limit.', 'info')

    for msg in progress:
        flash(msg, 'info')

    # Insert solver results into DB
    if assignments:
        group_lessons = set()
        filtered = []
        for sid, tid, subj, slot, loc in assignments:
            if sid >= offset:
                gid = sid - offset
                group_lessons.add((gid, tid, subj, slot, loc))
                filtered.append((None, gid, tid, subj, slot, loc))
        for sid, tid, subj, slot, loc in assignments:
            if sid >= offset:
                continue
            skip = False
            for gid in student_groups.get(sid, []):
                if subj in group_subjects.get(gid, []) and (gid, tid, subj, slot, loc) in group_lessons:
                    skip = True
                    break
            if not skip:
                filtered.append((sid, None, tid, subj, slot, loc))

        attendance_rows = []
        for entry in filtered:
            sid, gid, tid, subj, slot, loc = entry
            c.execute(
                'INSERT INTO timetable (student_id, group_id, teacher_id, subject_id, slot, location_id, date) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (sid, gid, tid, subj, slot, loc, target_date))
            if sid is not None:
                name = student_name_map.get(sid, '')
                attendance_rows.append((sid, name, subj, target_date))
            else:
                for member in group_members.get(gid, []):
                    name = student_name_map.get(member, '')
                    attendance_rows.append((member, name, subj, target_date))
        if attendance_rows:
            c.executemany('INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)',
                          attendance_rows)
    else:
        if status == cp_model.INFEASIBLE:
            flash('No feasible timetable could be generated.', 'error')
            for summary in summarize_unsat_core(core):
                if summary.get('aggregated'):
                    kind = summary.get('kind')
                    base = UNSAT_REASON_MAP.get(kind, summary.get('label') or kind or 'Constraint conflict')
                    details = _format_summary_details(summary)
                    message = base
                    if details:
                        message = f"{base} ({'; '.join(details)})"
                    flash(message, 'error')
                else:
                    info = summary.get('info')
                    kind = getattr(info, 'kind', '')
                    base = UNSAT_REASON_MAP.get(kind, getattr(info, 'label', '') or kind or 'Constraint conflict')
                    details = []
                    label = getattr(info, 'label', None)
                    if label and label != base:
                        details.append(f'label={label}')
                    context = getattr(info, 'context', {}) or {}
                    for key in sorted(context.keys()):
                        value = context[key]
                        if isinstance(value, (list, tuple, set)):
                            value = ','.join(str(v) for v in value)
                        details.append(f"{key}={value}")
                    message = base
                    if details:
                        message = f"{base} ({'; '.join(details)})"
                    flash(message, 'error')
    conn.commit()
    conn.close()


def get_timetable_data(target_date, view='teacher'):
    """Return timetable grid data for the given date.

    Parameters
    ----------
    target_date : str or None
        Date of the timetable to retrieve. If ``None`` the most recent date is
        used.
    view : str
        ``'teacher'`` for the traditional teacher-column layout,
        ``'location'`` to organise columns by location, or
        ``'patient_only'`` to group by location while showing only patient
        names in the time slots.
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']
    try:
        slot_times = json.loads(cfg['slot_start_times']) if cfg['slot_start_times'] else []
    except Exception:
        slot_times = []
    slot_labels = []
    last_start = None
    for i in range(slots):
        if i < len(slot_times):
            try:
                h, m = map(int, slot_times[i].split(':'))
                start = h * 60 + m
            except Exception:
                start = (last_start + cfg['slot_duration']) if last_start is not None else 8 * 60 + 30
        else:
            start = (last_start + cfg['slot_duration']) if last_start is not None else 8 * 60 + 30
        end = start + cfg['slot_duration']
        slot_labels.append({'start': f"{start // 60:02d}:{start % 60:02d}",
                            'end': f"{end // 60:02d}:{end % 60:02d}"})
        last_start = start

    if not target_date:
        c.execute('SELECT DISTINCT date FROM timetable ORDER BY date DESC LIMIT 1')
        row = c.fetchone()
        target_date = row['date'] if row else date.today().isoformat()

    missing, lesson_counts, group_data, location_data, teacher_data = get_missing_and_counts(c, target_date)

    location_views = {'location', 'patient_only'}
    if view in location_views:
        c.execute('SELECT id, name FROM locations')
        columns = [dict(r) for r in c.fetchall()]
        seen = {col['id'] for col in columns}
        extra_ids = sorted(lid for lid in location_data.keys() if lid not in seen)
        archive_names = {}
        if extra_ids:
            placeholders = ','.join('?' for _ in extra_ids)
            c.execute(
                f'SELECT id, name FROM locations_archive WHERE id IN ({placeholders})',
                extra_ids,
            )
            archive_names = {row['id']: row['name'] for row in c.fetchall()}
        for lid in extra_ids:
            info = location_data.get(lid, {})
            name = info.get('name') or archive_names.get(lid) or f'Location {lid}'
            columns.append({'id': lid, 'name': name})
    else:
        subj_map = {r['id']: r['name'] for r in c.execute('SELECT id, name FROM subjects')}
        if teacher_data:
            columns = []
            for entry in teacher_data:
                tid = entry.get('id')
                name = entry.get('name') or (f'Teacher {tid}' if tid is not None else 'Unknown Teacher')
                subjects = entry.get('subjects') or []
                subject_names = [subj_map.get(s, str(s)) for s in subjects]
                columns.append({'id': tid, 'name': name, 'subjects': json.dumps(subject_names)})
        else:
            c.execute(
                'SELECT id, name, subjects FROM teachers '
                "UNION ALL SELECT id, name, '[]' as subjects FROM teachers_archive"
            )
            columns = [dict(r) for r in c.fetchall()]
            for col in columns:
                subs = json.loads(col['subjects'])
                col['subjects'] = json.dumps([subj_map.get(s, str(s)) for s in subs])

    c.execute('''SELECT t.slot,
                        COALESCE(te.name, ta.name) as teacher,
                        COALESCE(s.name, sa.name) as student,
                        COALESCE(g.name, ga.name) as group_name,
                        COALESCE(sub.name, suba.name) AS subject, t.group_id,
                        t.teacher_id, t.student_id, t.location_id,
                        COALESCE(l.name, la.name) AS location_name
                 FROM timetable t
                 LEFT JOIN subjects sub ON t.subject_id = sub.id
                 LEFT JOIN subjects_archive suba ON t.subject_id = suba.id
                 LEFT JOIN teachers te ON t.teacher_id = te.id
                 LEFT JOIN teachers_archive ta ON t.teacher_id = ta.id
                 LEFT JOIN students s ON t.student_id = s.id
                 LEFT JOIN students_archive sa ON t.student_id = sa.id
                 LEFT JOIN groups g ON t.group_id = g.id
                 LEFT JOIN groups_archive ga ON t.group_id = ga.id
                 LEFT JOIN locations l ON t.location_id = l.id
                 LEFT JOIN locations_archive la ON t.location_id = la.id
                 WHERE t.date=?''', (target_date,))
    rows = c.fetchall()
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_students = {}
    for gm in gm_rows:
        group_students.setdefault(gm['group_id'], []).append(gm['student_id'])
    c.execute('SELECT id, name, subjects, active FROM students')
    student_rows = c.fetchall()
    student_names = {s['id']: s['name'] for s in student_rows}
    c.execute('SELECT id, name FROM students_archive')
    for row in c.fetchall():
        student_names.setdefault(row['id'], row['name'])

    snapshot_members = {}
    for gid, info in group_data.items():
        member_ids = []
        for member in info.get('members', []):
            sid = member.get('id')
            if sid is None:
                continue
            member_ids.append(sid)
            name = member.get('name')
            if name:
                student_names.setdefault(sid, name)
        if member_ids:
            snapshot_members[gid] = member_ids

    grid = {slot: {col['id']: None for col in columns} for slot in range(slots)}
    for r in rows:
        if view in location_views:
            lid = r['location_id']
            if lid is None:
                continue
            if r['group_id']:
                members = snapshot_members.get(r['group_id'])
                if members is None:
                    members = group_students.get(r['group_id'], [])
                names = ', '.join(student_names.get(m, f'Student {m}') for m in members)
                if view == 'patient_only':
                    desc = f"{r['group_name']} [{names}]"
                else:
                    desc = f"{r['group_name']} [{names}] ({r['subject']}) with {r['teacher']}"
            else:
                if view == 'patient_only':
                    desc = f"{r['student']}"
                else:
                    desc = f"{r['student']} ({r['subject']}) with {r['teacher']}"
            grid[r['slot']][lid] = desc
        else:
            tid = r['teacher_id']
            loc_name = r['location_name']
            if not loc_name and r['location_id'] is not None:
                info = location_data.get(r['location_id'])
                if info:
                    loc_name = info.get('name')
            loc = f" @ {loc_name}" if loc_name else ''
            if r['group_id']:
                members = snapshot_members.get(r['group_id'])
                if members is None:
                    members = group_students.get(r['group_id'], [])
                names = ', '.join(student_names.get(m, f'Student {m}') for m in members)
                desc = f"{r['group_name']} [{names}] ({r['subject']}){loc}"
            else:
                desc = f"{r['student']} ({r['subject']}){loc}"
            grid[r['slot']][tid] = desc

    conn.commit()
    missing_view = {
        sid: [{'subject': item['subject'], 'count': item['count'], 'today': item['assigned']}
              for item in subs]
        for sid, subs in missing.items()
    }

    group_view = {}
    for gid, info in group_data.items():
        members = []
        for member in info.get('members', []):
            sid = member.get('id')
            name = member.get('name')
            if sid is not None and (name is None or name == ''):
                name = student_names.get(sid, f'Student {sid}')
            members.append({'id': sid, 'name': name})
        group_name = info.get('name') or f'Group {gid}'
        group_view[gid] = {'name': group_name, 'members': members}

    conn.close()

    has_rows = bool(rows)
    return (target_date, range(slots), columns, grid, missing_view,
            student_names, slot_labels, has_rows, lesson_counts, group_view)


@app.route('/generate', methods=['POST'])
def generate():
    """Process the Generate Timetable form.

    The selected date is passed to generate_schedule and the browser is
    redirected back to the index page once complete. Existing timetables can
    be overwritten when the user confirms the prompt.
    """
    gen_date = request.form.get('date') or date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT 1 FROM timetable WHERE date=? LIMIT 1', (gen_date,))
    exists = c.fetchone() is not None
    conn.close()
    if exists and not request.form.get('confirm'):
        flash('Timetable already exists for that date.', 'error')
        return redirect(url_for('index'))
    if exists:
        conn = get_db()
        conn.execute('DELETE FROM timetable WHERE date=?', (gen_date,))
        conn.execute('DELETE FROM attendance_log WHERE date=?', (gen_date,))
        conn.execute('DELETE FROM worksheets WHERE date=?', (gen_date,))
        conn.execute('DELETE FROM timetable_snapshot WHERE date=?', (gen_date,))
        conn.commit()
        conn.close()
    generate_schedule(gen_date)
    conn = get_db()
    c = conn.cursor()
    get_missing_and_counts(c, gen_date, refresh=True)
    conn.commit()
    conn.close()
    return redirect(url_for('index', date=gen_date))


@app.route('/timetable')
def timetable():
    """Render a grid of the lessons scheduled for a particular date.

    Columns can represent teachers or locations depending on the ``mode`` query
    parameter. Each row represents a time slot and the page also lists any
    subjects that could not be scheduled for active students.
    """
    target_date = request.args.get('date')
    mode = request.args.get('mode', 'teacher')
    (t_date, slots, columns, grid,
     missing, student_names, slot_labels, has_rows, lesson_counts, group_data) = get_timetable_data(target_date, view=mode)
    if not has_rows:
        flash('No timetable available. Generate one from the home page.', 'error')
    return render_template('timetable.html', slots=slots, columns=columns,
                           grid=grid, json=json, date=t_date,
                           missing=missing, student_names=student_names,
                           slot_labels=slot_labels,
                           lesson_counts=lesson_counts,
                           group_data=group_data,
                           view_mode=mode)


@app.route('/attendance')
def attendance():
    """Display tables summarising how often students attended each subject.

    The first table lists currently active students while the second keeps
    records for any students that have been deleted from the configuration.
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT al.student_id AS sid, s.name AS name,
               COALESCE(sub.name, suba.name) AS subject, al.date
        FROM attendance_log al
        JOIN students s ON al.student_id = s.id
        LEFT JOIN subjects sub ON al.subject_id = sub.id
        LEFT JOIN subjects_archive suba ON al.subject_id = suba.id
        WHERE s.active=1
    ''')
    active_rows = c.fetchall()
    c.execute('''
        SELECT al.student_id AS sid,
               COALESCE(sa.name, al.student_name) AS name,
               COALESCE(sub.name, suba.name) AS subject, al.date
        FROM attendance_log al
        LEFT JOIN subjects sub ON al.subject_id = sub.id
        LEFT JOIN subjects_archive suba ON al.subject_id = suba.id
        LEFT JOIN students_archive sa ON al.student_id = sa.id
        LEFT JOIN students s ON al.student_id = s.id
        WHERE s.id IS NULL OR s.active=0
    ''')
    deleted_rows = c.fetchall()
    conn.close()

    def aggregate(rows, include_dates=False):
        data = {}
        totals = {}
        for r in rows:
            sid = r['sid']
            name = r['name']
            subj = r['subject']
            d = r['date']
            if include_dates:
                info = data.setdefault(sid, {'name': name, 'subjects': {}, 'first_date': d, 'last_date': d})
                if d < info['first_date']:
                    info['first_date'] = d
                if d > info['last_date']:
                    info['last_date'] = d
            else:
                info = data.setdefault(sid, {'name': name, 'subjects': {}})
            info['subjects'][subj] = info['subjects'].get(subj, 0) + 1
            totals[sid] = totals.get(sid, 0) + 1
        for sid, info in data.items():
            total = totals.get(sid, 0)
            for subj, count in info['subjects'].items():
                perc = round(100 * count / total, 2) if total else 0
                info['subjects'][subj] = {'count': count, 'percentage': perc}
        return data

    active_data = aggregate(active_rows)
    deleted_data = aggregate(deleted_rows, include_dates=True)

    return render_template('attendance.html', active_attendance=active_data, deleted_attendance=deleted_data)


@app.route('/manage_timetables')
def manage_timetables():
    """Show a list of saved timetable dates.

    Each date links to a form where the user can delete individual timetables
    or clear them all at once.
    """
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT DISTINCT date FROM timetable ORDER BY date DESC')
    dates = [row['date'] for row in c.fetchall()]
    conn.close()
    # Also list existing backup zip files under data/backups
    backups = []
    backups_dir = os.path.join(DATA_DIR, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    try:
        for name in os.listdir(backups_dir):
            if not name.lower().endswith('.zip'):
                continue
            p = os.path.join(backups_dir, name)
            try:
                stat = os.stat(p)
            except OSError:
                continue
            backups.append({
                'name': name,
                'size': stat.st_size,
                'ctime': stat.st_ctime,
                'created': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            })
        backups.sort(key=lambda x: x['ctime'], reverse=True)
    except Exception:
        backups = []
    return render_template('manage_timetables.html', dates=dates, backups=backups)


@app.route('/edit_timetable/<date>', methods=['GET', 'POST'])
def edit_timetable(date):
    """Allow manual editing of a saved timetable for a given date."""
    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            entry_id = request.form.get('entry_id')
            if entry_id:
                # fetch lesson details to adjust attendance log
                c.execute(
                    'SELECT student_id, group_id, subject_id FROM timetable WHERE id=? AND date=?',
                    (entry_id, date),
                )
                row = c.fetchone()
                if row:
                    subj = row['subject_id']
                    if row['student_id'] is not None:
                        sid = row['student_id']
                        c.execute(
                            'SELECT rowid FROM attendance_log WHERE student_id=? AND subject_id=? AND date=? LIMIT 1',
                            (sid, subj, date),
                        )
                        r = c.fetchone()
                        if r:
                            c.execute('DELETE FROM attendance_log WHERE rowid=?', (r['rowid'],))
                    elif row['group_id'] is not None:
                        gid = row['group_id']
                        members = c.execute(
                            'SELECT student_id FROM group_members WHERE group_id=?',
                            (gid,),
                        ).fetchall()
                        for m in members:
                            sid = m['student_id']
                            c.execute(
                                'SELECT rowid FROM attendance_log WHERE student_id=? AND subject_id=? AND date=? LIMIT 1',
                                (sid, subj, date),
                            )
                            r = c.fetchone()
                            if r:
                                c.execute('DELETE FROM attendance_log WHERE rowid=?', (r['rowid'],))
                c.execute('DELETE FROM timetable WHERE id=? AND date=?', (entry_id, date))
                get_missing_and_counts(c, date, refresh=True)
                conn.commit()
                flash('Lesson deleted.', 'info')
        elif action == 'add':
            slot = request.form.get('slot')
            teacher_id = request.form.get('teacher')
            subject = request.form.get('subject')
            student_group = request.form.get('student_group')
            location = request.form.get('location')
            if slot is not None and teacher_id and subject and student_group:
                slot = int(slot)
                teacher_id = int(teacher_id)
                subject_id = int(subject)
                student_id = None
                group_id = None
                if student_group.startswith('s'):
                    student_id = int(student_group[1:])
                elif student_group.startswith('g'):
                    group_id = int(student_group[1:])
                location_id = int(location) if location else None
                c.execute(
                    'INSERT INTO timetable (student_id, group_id, teacher_id, subject_id, slot, location_id, date) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (student_id, group_id, teacher_id, subject_id, slot, location_id, date),
                )
                # record attendance for the new lesson
                if student_id is not None:
                    c.execute('SELECT name FROM students WHERE id=?', (student_id,))
                    r = c.fetchone()
                    if r:
                        name = r['name']
                    else:
                        c.execute('SELECT name FROM students_archive WHERE id=?', (student_id,))
                        r = c.fetchone()
                        name = r['name'] if r else ''
                    c.execute(
                        'INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)',
                        (student_id, name, subject_id, date),
                    )
                elif group_id is not None:
                    members = c.execute(
                        'SELECT student_id FROM group_members WHERE group_id=?',
                        (group_id,),
                    ).fetchall()
                    rows = []
                    for m in members:
                        sid = m['student_id']
                        c.execute('SELECT name FROM students WHERE id=?', (sid,))
                        r = c.fetchone()
                        if r:
                            name = r['name']
                        else:
                            c.execute('SELECT name FROM students_archive WHERE id=?', (sid,))
                            r = c.fetchone()
                            name = r['name'] if r else ''
                        rows.append((sid, name, subject_id, date))
                    if rows:
                        c.executemany(
                            'INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)',
                            rows,
                        )
                get_missing_and_counts(c, date, refresh=True)
                conn.commit()
                flash('Lesson added.', 'info')
        elif action == 'edit':
            entry_id = request.form.get('entry_id')
            subject = request.form.get('subject')
            student_group = request.form.get('student_group')
            location = request.form.get('location')
            if entry_id and subject and student_group:
                c.execute(
                    'SELECT student_id, group_id, subject_id FROM timetable WHERE id=? AND date=?',
                    (entry_id, date),
                )
                old = c.fetchone()
                if old:
                    old_subj = old['subject_id']
                    if old['student_id'] is not None:
                        sid = old['student_id']
                        c.execute(
                            'SELECT rowid FROM attendance_log WHERE student_id=? AND subject_id=? AND date=? LIMIT 1',
                            (sid, old_subj, date),
                        )
                        r = c.fetchone()
                        if r:
                            c.execute('DELETE FROM attendance_log WHERE rowid=?', (r['rowid'],))
                    elif old['group_id'] is not None:
                        gid = old['group_id']
                        members = c.execute(
                            'SELECT student_id FROM group_members WHERE group_id=?',
                            (gid,),
                        ).fetchall()
                        for m in members:
                            sid = m['student_id']
                            c.execute(
                                'SELECT rowid FROM attendance_log WHERE student_id=? AND subject_id=? AND date=? LIMIT 1',
                                (sid, old_subj, date),
                            )
                            r = c.fetchone()
                            if r:
                                c.execute('DELETE FROM attendance_log WHERE rowid=?', (r['rowid'],))

                new_student_id = None
                new_group_id = None
                if student_group.startswith('s'):
                    new_student_id = int(student_group[1:])
                elif student_group.startswith('g'):
                    new_group_id = int(student_group[1:])
                location_id = int(location) if location else None
                new_subject_id = int(subject)
                c.execute(
                    'UPDATE timetable SET student_id=?, group_id=?, subject_id=?, location_id=? WHERE id=? AND date=?',
                    (new_student_id, new_group_id, new_subject_id, location_id, entry_id, date),
                )
                if new_student_id is not None:
                    c.execute('SELECT name FROM students WHERE id=?', (new_student_id,))
                    r = c.fetchone()
                    if r:
                        name = r['name']
                    else:
                        c.execute('SELECT name FROM students_archive WHERE id=?', (new_student_id,))
                        r = c.fetchone()
                        name = r['name'] if r else ''
                    c.execute(
                        'INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)',
                        (new_student_id, name, new_subject_id, date),
                    )
                elif new_group_id is not None:
                    members = c.execute(
                        'SELECT student_id FROM group_members WHERE group_id=?',
                        (new_group_id,),
                    ).fetchall()
                    rows = []
                    for m in members:
                        sid = m['student_id']
                        c.execute('SELECT name FROM students WHERE id=?', (sid,))
                        r = c.fetchone()
                        if r:
                            name = r['name']
                        else:
                            c.execute('SELECT name FROM students_archive WHERE id=?', (sid,))
                            r = c.fetchone()
                            name = r['name'] if r else ''
                        rows.append((sid, name, new_subject_id, date))
                    if rows:
                        c.executemany(
                            'INSERT INTO attendance_log (student_id, student_name, subject_id, date) VALUES (?, ?, ?, ?)',
                            rows,
                        )
                get_missing_and_counts(c, date, refresh=True)
                conn.commit()
                flash('Lesson updated.', 'info')
        elif action == 'worksheet':
            student_id = request.form.get('student_id')
            subject_id = request.form.get('subject_id')
            assign = request.form.get('assign')
            if (
                student_id not in (None, "")
                and subject_id not in (None, "")
                and assign not in (None, "")
            ):
                sid = int(student_id)
                subj_id = int(subject_id)
                if assign == '1':
                    c.execute(
                        'SELECT 1 FROM worksheets WHERE student_id=? AND subject_id=? AND date=?',
                        (sid, subj_id, date),
                    )
                    if c.fetchone() is None:
                        c.execute(
                            'INSERT INTO worksheets (student_id, subject_id, date) VALUES (?, ?, ?)',
                            (sid, subj_id, date),
                        )
                else:
                    c.execute(
                        'DELETE FROM worksheets WHERE student_id=? AND subject_id=? AND date=?',
                        (sid, subj_id, date),
                    )
                get_missing_and_counts(c, date, refresh=True)
                conn.commit()
                flash('Worksheet assignment updated.', 'info')
        elif action == 'refresh':
            get_missing_and_counts(c, date, refresh=True)
            conn.commit()
            flash('Unassigned list refreshed.', 'warning')
        conn.close()
        return redirect(url_for('edit_timetable', date=date))

    # Fetch config to determine slot count and labels
    conf = c.execute('SELECT * FROM config WHERE id=1').fetchone()
    slots = range(conf['slots_per_day'] if conf else 0)
    slot_labels = []
    if conf:
        try:
            slot_times = json.loads(conf['slot_start_times']) if conf['slot_start_times'] else []
        except Exception:
            slot_times = []
        last_start = None
        for i in range(conf['slots_per_day']):
            if i < len(slot_times):
                try:
                    h, m = map(int, slot_times[i].split(':'))
                    start = h * 60 + m
                except Exception:
                    start = (last_start + conf['slot_duration']) if last_start is not None else 8 * 60 + 30
            else:
                start = (last_start + conf['slot_duration']) if last_start is not None else 8 * 60 + 30
            end = start + conf['slot_duration']
            slot_labels.append({'start': f"{start // 60:02d}:{start % 60:02d}",
                                'end': f"{end // 60:02d}:{end % 60:02d}"})
            last_start = start

    # Teachers for columns (include subjects to display in header)
    c.execute('SELECT id, name, subjects FROM teachers')
    teachers = [dict(r) for r in c.fetchall()]
    subj_map = {r['id']: r['name'] for r in c.execute('SELECT id, name FROM subjects')}
    for t in teachers:
        subs = json.loads(t['subjects'])
        t['subjects'] = json.dumps([subj_map.get(s, str(s)) for s in subs])

    # Existing lessons with teacher id for grid placement
    c.execute(
        '''SELECT t.id, t.slot, t.subject_id,
                  COALESCE(sub.name, suba.name) AS subject, t.teacher_id, t.student_id, t.group_id,
                  t.location_id, COALESCE(s.name, sa.name) AS student_name,
                  COALESCE(g.name, ga.name) AS group_name, COALESCE(l.name, la.name) AS location_name
           FROM timetable t
           LEFT JOIN subjects sub ON t.subject_id = sub.id
           LEFT JOIN subjects_archive suba ON t.subject_id = suba.id
           LEFT JOIN students s ON t.student_id = s.id
           LEFT JOIN students_archive sa ON t.student_id = sa.id
           LEFT JOIN groups g ON t.group_id = g.id
           LEFT JOIN groups_archive ga ON t.group_id = ga.id
           LEFT JOIN locations l ON t.location_id = l.id
           LEFT JOIN locations_archive la ON t.location_id = la.id
           WHERE t.date=?''',
        (date,),
    )
    lessons = c.fetchall()

    grid = {slot: {t['id']: None for t in teachers} for slot in slots}
    for les in lessons:
        desc = f"{les['student_name'] or les['group_name']} ({les['subject']})"
        if les['location_name']:
            desc += f" @ {les['location_name']}"
        grid[les['slot']][les['teacher_id']] = {
            'id': les['id'],
            'desc': desc,
            'student_id': les['student_id'],
            'group_id': les['group_id'],
            'subject': les['subject'],
            'subject_id': les['subject_id'],
            'location_id': les['location_id'],
        }

    c.execute('SELECT id, name FROM students')
    students = c.fetchall()
    c.execute('SELECT id, name FROM groups')
    groups = c.fetchall()
    c.execute('SELECT id, name FROM subjects')
    subjects = c.fetchall()
    c.execute('SELECT id, name FROM locations')
    locations = c.fetchall()

    # compute unassigned subjects and worksheet counts
    c.execute('SELECT id, name, subjects, active FROM students')
    student_rows = c.fetchall()
    student_names = {s['id']: s['name'] for s in student_rows}
    c.execute('SELECT id, name FROM students_archive')
    for row in c.fetchall():
        student_names.setdefault(row['id'], row['name'])

    missing, lesson_counts, group_data, _, _ = get_missing_and_counts(c, date)
    conn.commit()
    conn.close()
    return render_template(
        'edit_timetable.html',
        date=date,
        grid=grid,
        slot_labels=slot_labels,
        students=students,
        groups=groups,
        teachers=teachers,
        subjects=subjects,
        locations=locations,
        missing=missing,
        student_names=student_names,
        slots=slots,
        lesson_counts=lesson_counts,
        group_data=group_data,
        json=json,
    )


@app.route('/delete_timetables', methods=['POST'])
def delete_timetables():
    """Handle form submissions to remove saved timetables.

    The user can either tick individual dates to delete or choose the
    *Clear All* option which wipes every saved timetable and related
    attendance log entries.
    """
    conn = get_db()
    c = conn.cursor()
    if request.form.get('clear_all'):
        c.execute('DELETE FROM timetable')
        c.execute('DELETE FROM attendance_log')
        c.execute('DELETE FROM worksheets')
        c.execute('DELETE FROM timetable_snapshot')
        conn.commit()
        conn.close()
        flash('All timetables deleted.', 'info')
        return redirect(url_for('manage_timetables'))

    dates = request.form.getlist('dates')
    if dates:
        for d in dates:
            c.execute('DELETE FROM timetable WHERE date=?', (d,))
            c.execute('DELETE FROM attendance_log WHERE date=?', (d,))
            c.execute('DELETE FROM worksheets WHERE date=?', (d,))
            c.execute('DELETE FROM timetable_snapshot WHERE date=?', (d,))
        conn.commit()
        conn.close()
        flash(f'Deleted timetables for {len(dates)} date(s).', 'info')
    else:
        conn.close()
        flash('No dates selected.', 'error')
    return redirect(url_for('manage_timetables'))


@app.route('/reset_db', methods=['POST'])
def reset_db():
    """Reset the database to its initial state.

    Useful during development or demos when you want to start from a clean
    slate. All existing configuration and timetables are removed.
    """
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    flash('Database reset to default scenario.', 'info')
    return redirect(url_for('config'))


# --- Backup & Restore utilities and routes ---

def _verify_db_integrity(db_path: str) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        conn.close()
        return bool(row and str(row[0]).lower() == 'ok')
    except Exception:
        return False


def _rotate_backups(dest_dir: str, keep: int) -> None:
    try:
        files = [os.path.join(dest_dir, f) for f in os.listdir(dest_dir) if f.lower().endswith('.zip')]
        files = [(f, os.stat(f).st_ctime) for f in files if os.path.isfile(f)]
        files.sort(key=lambda t: t[1], reverse=True)
        for f, _ in files[keep:]:
            try:
                os.remove(f)
            except OSError:
                pass
    except Exception:
        pass


def backup_db(dest_dir: str = None, compress: bool = True, verify: bool = True, keep: int = 10):
    dest_dir = dest_dir or os.path.join(DATA_DIR, 'backups')
    os.makedirs(dest_dir, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_name = f"timetable_{ts}"
    snapshot_path = os.path.join(dest_dir, base_name + '.db')
    zip_path = os.path.join(dest_dir, base_name + '.zip')

    # Create consistent snapshot using sqlite backup API
    src = get_db()
    try:
        dst = sqlite3.connect(snapshot_path)
        src.backup(dst)
        dst.close()
    finally:
        src.close()

    # Verify snapshot
    if verify and not _verify_db_integrity(snapshot_path):
        try:
            os.remove(snapshot_path)
        except OSError:
            pass
        raise RuntimeError('Backup integrity check failed.')

    # Zip snapshot if requested
    if compress:
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_path, arcname=os.path.basename(snapshot_path))
        try:
            os.remove(snapshot_path)
        except OSError:
            pass
        out_path = zip_path
        out_name = os.path.basename(zip_path)
    else:
        out_path = snapshot_path
        out_name = os.path.basename(snapshot_path)

    # Rotation
    _rotate_backups(dest_dir, keep)

    return out_path, out_name


def _validate_backup_filename(name: str) -> str:
    # Ensure the file stays within the backups directory
    backups_dir = os.path.join(DATA_DIR, 'backups')
    path = os.path.normpath(os.path.join(backups_dir, name))
    if not path.startswith(os.path.normpath(backups_dir) + os.sep):
        raise ValueError('Invalid backup filename')
    if not path.lower().endswith('.zip'):
        raise ValueError('Backup must be a .zip file')
    if not os.path.exists(path):
        raise FileNotFoundError('Backup not found')
    return path


def restore_db_from_zip(zip_file_path: str, run_migrations: bool = True) -> None:
    # Extract DB from zip to a temp file
    with zipfile.ZipFile(zip_file_path, 'r') as zf:
        # Find the first .db file inside
        db_members = [m for m in zf.namelist() if m.lower().endswith('.db')]
        if not db_members:
            raise RuntimeError('No .db file inside backup zip')
        member = db_members[0]
        with tempfile.TemporaryDirectory() as td:
            tmp_db = os.path.join(td, os.path.basename(member))
            zf.extract(member, td)
            # When extracted, file is at td/member path; normalize if nested
            extracted_path = os.path.join(td, member)
            if os.path.isdir(extracted_path):
                # safety, but unlikely
                raise RuntimeError('Unexpected backup structure')
            os.replace(extracted_path, tmp_db)

            # Verify integrity
            if not _verify_db_integrity(tmp_db):
                raise RuntimeError('Backup file failed integrity check')

            # Safety copy of current DB
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            pre_path = os.path.join(DATA_DIR, f'timetable_pre_restore_{ts}.db')
            try:
                if os.path.exists(DB_PATH):
                    # Use sqlite backup API to copy current DB safely
                    src = sqlite3.connect(DB_PATH)
                    dst = sqlite3.connect(pre_path)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close()
                        src.close()
            except Exception:
                # If safety copy fails, proceed but inform via flash later
                pre_path = None

            # Replace the DB
            # Ensure directory exists
            os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
            # Use atomic replace where possible
            try:
                os.replace(tmp_db, DB_PATH)
            except PermissionError as e:
                raise RuntimeError('Database file is in use; please retry') from e

    # Run migrations to adjust schema differences
    if run_migrations:
        init_db()


@app.route('/backup_db', methods=['POST'])
def backup_db_route():
    try:
        path, name = backup_db(dest_dir=os.path.join(DATA_DIR, 'backups'), compress=True, verify=True, keep=10)
        # Auto-download; also saved to disk already
        return send_file(path, as_attachment=True, download_name=name, mimetype='application/zip')
    except Exception as e:
        flash(f'Backup failed: {e}', 'error')
        return redirect(url_for('manage_timetables'))


@app.route('/download_backup/<path:filename>')
def download_backup(filename):
    try:
        path = _validate_backup_filename(filename)
        return send_file(path, as_attachment=True, download_name=os.path.basename(path), mimetype='application/zip')
    except Exception as e:
        flash(f'Cannot download backup: {e}', 'error')
        return redirect(url_for('manage_timetables'))


@app.route('/restore_db_existing', methods=['POST'])
def restore_db_existing():
    confirm = request.form.get('confirm', '')
    if confirm.strip() != 'RESTORE':
        flash("Confirmation text mismatch. Type 'RESTORE' exactly.", 'error')
        return redirect(url_for('manage_timetables'))
    name = request.form.get('filename', '')
    try:
        path = _validate_backup_filename(name)
        restore_db_from_zip(path, run_migrations=True)
        flash(f'Restored database from {name}.', 'info')
    except Exception as e:
        flash(f'Restore failed: {e}', 'error')
    return redirect(url_for('manage_timetables'))


@app.route('/restore_db_upload', methods=['POST'])
def restore_db_upload():
    confirm = request.form.get('confirm', '')
    if confirm.strip() != 'RESTORE':
        flash("Confirmation text mismatch. Type 'RESTORE' exactly.", 'error')
        return redirect(url_for('manage_timetables'))
    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('manage_timetables'))
    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.zip'):
        flash('Only .zip backups are accepted.', 'error')
        return redirect(url_for('manage_timetables'))
    backups_dir = os.path.join(DATA_DIR, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_name = f"uploaded_{ts}_{filename}"
    save_path = os.path.join(backups_dir, save_name)
    try:
        file.save(save_path)
        restore_db_from_zip(save_path, run_migrations=True)
        flash(f'Uploaded and restored backup: {save_name}', 'info')
    except Exception as e:
        flash(f'Upload/restore failed: {e}', 'error')
    return redirect(url_for('manage_timetables'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
