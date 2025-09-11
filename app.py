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
from werkzeug.utils import secure_filename

from cp_sat_timetable import build_model, solve_and_print

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

CURRENT_PRESET_VERSION = 1

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
    'teacher_unavailable',
    'student_unavailable',
    'fixed_assignments',
    'groups',
    'group_members',
    'groups_archive',
    'student_teacher_block',
    'locations',
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


def populate_student_subject_ids(c):
    """Ensure each student row has ``subject_ids`` populated.

    The legacy schema stored required subjects as a JSON array of names in the
    ``subjects`` column.  Newer versions track the canonical integer ids in the
    ``subject_ids`` column to avoid ambiguity when subjects are renamed.  This
    helper backfills ``subject_ids`` for any rows missing the data by looking up
    ids from the ``subjects`` table.  It is safe to call repeatedly.
    """
    c.execute('SELECT id, name FROM subjects')
    rows = c.fetchall()
    name_to_id = {r['name'].lower(): r['id'] for r in rows}
    c.execute('SELECT id, subjects, subject_ids FROM students')
    srows = c.fetchall()
    for r in srows:
        if r['subject_ids']:
            continue
        names = json.loads(r['subjects'] or '[]')
        ids = [name_to_id.get(n.lower()) for n in names if name_to_id.get(n.lower()) is not None]
        c.execute('UPDATE students SET subject_ids=? WHERE id=?', (json.dumps(ids), r['id']))


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
            well_attend_weight REAL
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
            subject_ids TEXT,
            active INTEGER DEFAULT 1,
            min_lessons INTEGER,
            max_lessons INTEGER,
            allow_repeats INTEGER,
            max_repeats INTEGER,
            allow_consecutive INTEGER,
            prefer_consecutive INTEGER,
            allow_multi_teacher INTEGER
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
        if not column_exists('students', 'subject_ids'):
            c.execute('ALTER TABLE students ADD COLUMN subject_ids TEXT')
            populate_student_subject_ids(c)

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
            slot INTEGER
        )''')
    elif not column_exists('fixed_assignments', 'group_id'):
        c.execute('ALTER TABLE fixed_assignments ADD COLUMN group_id INTEGER')

    if not table_exists('timetable'):
        c.execute('''CREATE TABLE timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            group_id INTEGER,
            teacher_id INTEGER,
            subject TEXT,
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

    if not table_exists('timetable_snapshot'):
        c.execute('''CREATE TABLE timetable_snapshot (
            date TEXT PRIMARY KEY,
            missing TEXT,
            lesson_counts TEXT
        )''')

    if not table_exists('locations'):
        c.execute('''CREATE TABLE locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
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

    if not table_exists('attendance_log'):
        c.execute('''CREATE TABLE attendance_log (
            student_id INTEGER,
            student_name TEXT,
            subject TEXT,
            date TEXT
        )''')

    if not table_exists('worksheets'):
        c.execute('''CREATE TABLE worksheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject TEXT,
            subject_id INTEGER,
            date TEXT,
            FOREIGN KEY(subject_id) REFERENCES subjects(id)
        )''')
    else:
        if not column_exists('worksheets', 'subject_id'):
            c.execute('ALTER TABLE worksheets ADD COLUMN subject_id INTEGER')
            c.execute(
                'UPDATE worksheets SET subject_id = ('
                'SELECT id FROM subjects WHERE LOWER(name) = LOWER(worksheets.subject)'
                ') WHERE subject_id IS NULL'
            )
    # Clean up any duplicate worksheet rows (same student, subject, date)
    if table_exists('worksheets'):
        # Keep the oldest row per (student_id, subject_id, date)
        c.execute(
            '''DELETE FROM worksheets WHERE rowid NOT IN (
                   SELECT MIN(rowid) FROM worksheets
                   GROUP BY student_id, subject_id, date
               )'''
        )
        removed = c.rowcount
        # Enforce uniqueness to prevent future duplicates
        c.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_worksheets_unique '
            'ON worksheets(student_id, subject_id, date)'
        )
        # Invalidate cached snapshots only if duplicates were cleaned up
        if removed and table_exists('timetable_snapshot'):
            c.execute('DELETE FROM timetable_snapshot')

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
        for r in rows[5:]:
            cur.execute('DELETE FROM config_presets WHERE id=?', (r['id'],))
        for r in rows[:5]:
            try:
                json.loads(r['data'])
            except Exception:
                logging.warning('Removing corrupted preset %s', r['id'])
                cur.execute('DELETE FROM config_presets WHERE id=?', (r['id'],))

    cleanup_presets(c)

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
            well_attend_weight
        ) VALUES (1, 8, 30, ?, 1, 4, 1, 8, 0, 2, 0, 1, 3, 1, 0, 10, 2.0, 1, 0, 1, 1)''',
                  (json.dumps(times),))
        teachers = [
            ('Teacher A', json.dumps(['Math', 'English']), None, None),
            ('Teacher B', json.dumps(['Science']), None, None),
            ('Teacher C', json.dumps(['History']), None, None),
        ]
        c.executemany('INSERT INTO teachers (name, subjects, min_lessons, max_lessons) VALUES (?, ?, ?, ?)', teachers)
        students = [
            ('Student 1', json.dumps(['Math', 'English'])),
            ('Student 2', json.dumps(['Math', 'Science'])),
            ('Student 3', json.dumps(['English', 'History'])),
            ('Student 4', json.dumps(['Science', 'Math'])),
            ('Student 5', json.dumps(['History'])),
            ('Student 6', json.dumps(['English', 'Science'])),
            ('Student 7', json.dumps(['Math'])),
            ('Student 8', json.dumps(['History', 'Science'])),
            ('Student 9', json.dumps(['English']))
        ]
        c.executemany('INSERT INTO students (name, subjects) VALUES (?, ?)', students)
        subjects = [
            ('Math', 0),
            ('English', 0),
            ('Science', 0),
            ('History', 0)
        ]
        c.executemany('INSERT INTO subjects (name, min_percentage) VALUES (?, ?)', subjects)
        populate_student_subject_ids(c)
    conn.commit()
    conn.close()


def dump_configuration():
    """Serialize configuration tables to a JSON-compatible dict.

    Timetables, worksheets and other runtime data are intentionally excluded so
    presets capture only the settings needed to regenerate a schedule.
    """
    conn = get_db()
    c = conn.cursor()
    populate_student_subject_ids(c)
    data = {}
    for table in CONFIG_TABLES:
        c.execute(f'SELECT * FROM {table}')
        rows = [dict(r) for r in c.fetchall()]
        data[table] = rows
    conn.close()
    return {'version': CURRENT_PRESET_VERSION, 'data': data}


def migrate_preset(preset):
    """Upgrade preset data from older versions to CURRENT_PRESET_VERSION."""
    # Currently only version 1 exists. Future migrations will modify ``preset``.
    return preset


def restore_configuration(preset, overwrite=False):
    """Restore configuration tables from a preset dump.

    Existing timetables and worksheet counts remain unchanged. When ``overwrite``
    is False and current configuration differs from the preset, ``False`` is
    returned so the caller can prompt the user for confirmation.
    """
    version = preset.get('version', 0)
    if version > CURRENT_PRESET_VERSION:
        raise ValueError('Preset version is newer than supported.')
    if version < CURRENT_PRESET_VERSION:
        preset = migrate_preset(preset)
    conn = get_db()
    c = conn.cursor()
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

    c.execute('SELECT DISTINCT student_id FROM timetable WHERE student_id IS NOT NULL')
    s_ids = [r['student_id'] for r in c.fetchall()]
    student_names = {}
    if s_ids:
        placeholders = ','.join(['?'] * len(s_ids))
        c.execute(f'SELECT id, name FROM students WHERE id IN ({placeholders})', s_ids)
        student_names = {r['id']: r['name'] for r in c.fetchall()}
        c.execute(f'SELECT id, name FROM students_archive WHERE id IN ({placeholders})', s_ids)
        for r in c.fetchall():
            student_names.setdefault(r['id'], r['name'])

    c.execute('SELECT DISTINCT student_id, student_name FROM attendance_log')
    log_students = {r['student_id']: r['student_name'] for r in c.fetchall()}
    for sid, name in student_names.items():
        log_students.setdefault(sid, name)

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

    populate_student_subject_ids(c)

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
        group_students.setdefault(gm['group_id'], []).append(gm['student_id'])

    c.execute('SELECT id, name FROM subjects')
    subj_rows = c.fetchall()
    id_to_name = {r['id']: r['name'] for r in subj_rows}
    name_to_id = {r['name'].lower(): r['id'] for r in subj_rows}

    c.execute('SELECT id, name, subject_ids, subjects, active FROM students')
    student_rows = c.fetchall()

    assigned = {s['id']: set() for s in student_rows}
    lesson_counts = {s['id']: 0 for s in student_rows}

    c.execute('SELECT student_id, group_id, subject FROM timetable WHERE date=?', (date,))
    lessons = c.fetchall()
    for les in lessons:
        subj_id = name_to_id.get(les['subject'].lower()) if les['subject'] else None
        if subj_id is None:
            continue
        if les['group_id']:
            for sid in group_students.get(les['group_id'], []):
                assigned.setdefault(sid, set()).add(subj_id)
                lesson_counts[sid] = lesson_counts.get(sid, 0) + 1
        elif les['student_id']:
            assigned.setdefault(les['student_id'], set()).add(subj_id)
            lesson_counts[les['student_id']] = lesson_counts.get(les['student_id'], 0) + 1

    missing = {}
    for s in student_rows:
        if s['subject_ids']:
            required_ids = set(json.loads(s['subject_ids']))
        else:
            names = json.loads(s['subjects'] or '[]')
            required_ids = {name_to_id.get(n.lower()) for n in names if name_to_id.get(n.lower()) is not None}
        miss_ids = required_ids - assigned.get(s['id'], set())
        if miss_ids:
            subj_list = []
            for sid_ in sorted(miss_ids):
                sid = s['id']
                # Count worksheets assigned (by distinct date to avoid duplicates)
                c.execute(
                    'SELECT COUNT(DISTINCT w.date) FROM worksheets w '
                    'WHERE w.student_id=? AND w.subject_id=? AND w.date<=?',
                    (sid, sid_, date),
                )
                worksheet_count = c.fetchone()[0]
                c.execute(
                    'SELECT 1 FROM worksheets w '
                    'WHERE w.student_id=? AND w.subject_id=? AND w.date=?',
                    (sid, sid_, date),
                )
                assigned_today = c.fetchone() is not None
                subj_list.append({'subject': id_to_name.get(sid_, ''), 'count': worksheet_count, 'assigned': assigned_today})
            missing[s['id']] = subj_list

    return missing, lesson_counts


def get_missing_and_counts(c, date, refresh=False):
    if not refresh:
        row = c.execute(
            'SELECT missing, lesson_counts FROM timetable_snapshot WHERE date=?',
            (date,),
        ).fetchone()
        if row:
            missing = {int(k): v for k, v in json.loads(row['missing']).items()}
            lesson_counts = {int(k): v for k, v in json.loads(row['lesson_counts']).items()}
            return missing, lesson_counts

    missing, lesson_counts = calculate_missing_and_counts(c, date)
    c.execute(
        'INSERT OR REPLACE INTO timetable_snapshot (date, missing, lesson_counts) VALUES (?, ?, ?)',
        (date, json.dumps(missing), json.dumps(lesson_counts)),
    )
    return missing, lesson_counts


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
         student_names, slot_labels, has_rows, lesson_counts) = data
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
        slots_per_day = int(request.form['slots_per_day'])
        slot_duration = int(request.form['slot_duration'])
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
        t_min_lessons = int(request.form['teacher_min_lessons'])
        t_max_lessons = int(request.form['teacher_max_lessons'])
        if t_min_lessons > t_max_lessons:
            flash('Global teacher min lessons cannot exceed max lessons', 'error')
            has_error = True
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
                     group_weight=?, well_attend_weight=?, allow_multi_teacher=?, balance_teacher_load=?, balance_weight=?
                     WHERE id=1""",
                  (slots_per_day, slot_duration, json.dumps(start_times), min_lessons,
                   max_lessons, t_min_lessons, t_max_lessons,
                   allow_repeats, max_repeats, prefer_consecutive,
                   allow_consecutive, consecutive_weight, require_all_subjects,
                   use_attendance_priority, attendance_weight, group_weight, well_attend_weight,
                   allow_multi_teacher, balance_teacher_load, balance_weight))
        # update subjects
        subj_ids = request.form.getlist('subject_id')
        deletes_sub = set(request.form.getlist('subject_delete'))
        for sid in subj_ids:
            name = request.form.get(f'subject_name_{sid}')
            min_perc = request.form.get(f'subject_min_{sid}')
            min_val = int(min_perc) if min_perc else 0
            if sid in deletes_sub:
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
                subs = request.form.getlist(f'teacher_subjects_{tid}')
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
        new_tsubs = request.form.getlist('new_teacher_subjects')
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
        c.execute('SELECT id, name FROM subjects')
        subj_rows = c.fetchall()
        subj_map = {r['id']: r['name'] for r in subj_rows}
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
                subs_raw = request.form.getlist(f'student_subject_ids_{sid}')
                sub_ids = [int(x) for x in subs_raw]
                subs = [subj_map[i] for i in sub_ids if i in subj_map]
                active = 1 if request.form.get(f'student_active_{sid}') else 0
                smin = request.form.get(f'student_min_{sid}')
                smax = request.form.get(f'student_max_{sid}')
                allow_rep = 1 if request.form.get(f'student_allow_repeats_{sid}') else 0
                max_rep = request.form.get(f'student_max_repeats_{sid}')
                allow_con = 1 if request.form.get(f'student_allow_consecutive_{sid}') else 0
                prefer_con = 1 if request.form.get(f'student_prefer_consecutive_{sid}') else 0
                allow_multi = 1 if request.form.get(f'student_multi_teacher_{sid}') else 0
                subj_json = json.dumps(subs)
                id_json = json.dumps(sub_ids)
                min_val = int(smin) if smin else None
                max_val = int(smax) if smax else None
                max_rep_val = int(max_rep) if max_rep else None
                c.execute('''UPDATE students SET name=?, subjects=?, subject_ids=?, active=?,
                             min_lessons=?, max_lessons=?, allow_repeats=?,
                             max_repeats=?, allow_consecutive=?, prefer_consecutive=?,
                             allow_multi_teacher=? WHERE id=?''',
                          (name, subj_json, id_json, active, min_val, max_val,
                           allow_rep, max_rep_val, allow_con, prefer_con,
                           allow_multi, int(sid)))
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
        new_ssubs_raw = request.form.getlist('new_student_subject_ids')
        new_ids = [int(x) for x in new_ssubs_raw]
        new_ssubs = [subj_map[i] for i in new_ids if i in subj_map]
        new_blocks = request.form.getlist('new_student_block')
        new_unav = request.form.getlist('new_student_unavail')
        new_smin = request.form.get('new_student_min')
        new_smax = request.form.get('new_student_max')
        new_allow_rep = 1 if request.form.get('new_student_allow_repeats') else 0
        new_max_rep = request.form.get('new_student_max_repeats')
        new_allow_con = 1 if request.form.get('new_student_allow_consecutive') else 0
        new_prefer_con = 1 if request.form.get('new_student_prefer_consecutive') else 0
        new_allow_multi = 1 if request.form.get('new_student_multi_teacher') else 0
        if new_sname and new_ssubs:
            subj_json = json.dumps(new_ssubs)
            id_json = json.dumps(new_ids)
            min_val = int(new_smin) if new_smin else None
            max_val = int(new_smax) if new_smax else None
            max_rep_val = int(new_max_rep) if new_max_rep else None
            c.execute('''INSERT INTO students (name, subjects, subject_ids, active, min_lessons, max_lessons,
                      allow_repeats, max_repeats, allow_consecutive, prefer_consecutive, allow_multi_teacher)
                      VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)''',
                      (new_sname, subj_json, id_json, min_val, max_val, new_allow_rep,
                       max_rep_val, new_allow_con, new_prefer_con, new_allow_multi))
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
        c.execute('SELECT id, subject_ids, subjects FROM students')
        srows = c.fetchall()
        student_subj_map = {}
        for s in srows:
            if s['subject_ids']:
                ids = json.loads(s['subject_ids'])
                names = [subj_map[i] for i in ids if i in subj_map]
            else:
                names = json.loads(s['subjects'] or '[]')
            student_subj_map[s['id']] = set(names)
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
            subs = request.form.getlist(f'group_subjects_{gid}')
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
        ng_subs = request.form.getlist('new_group_subjects')
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
        c.execute('SELECT id, subjects FROM teachers')
        trows = c.fetchall()
        teacher_map = {t["id"]: json.loads(t["subjects"]) for t in trows}
        c.execute('SELECT id, name FROM subjects')
        subj_rows = c.fetchall()
        subj_map = {r['id']: r['name'] for r in subj_rows}
        c.execute('SELECT id, subject_ids, subjects FROM students')
        srows = c.fetchall()
        student_map = {}
        for s in srows:
            if s['subject_ids']:
                ids = json.loads(s['subject_ids'])
                names = [subj_map[i] for i in ids if i in subj_map]
            else:
                names = json.loads(s['subjects'] or '[]')
            student_map[s['id']] = names
        c.execute('SELECT id, subjects FROM groups')
        grows = c.fetchall()
        group_subj = {g["id"]: json.loads(g["subjects"]) for g in grows}
        c.execute('SELECT teacher_id, slot FROM teacher_unavailable')
        unav = c.fetchall()
        unav_set = {(u['teacher_id'], u['slot']) for u in unav}
        c.execute('SELECT teacher_id, slot FROM fixed_assignments')
        fixed = c.fetchall()
        fixed_set = {(f['teacher_id'], f['slot']) for f in fixed}

        if na_teacher and na_subject and na_slot and (na_student or na_group):
            tid = int(na_teacher)
            slot = int(na_slot) - 1
            if na_subject not in teacher_map.get(tid, []):
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
                if na_subject not in group_subj.get(gid, []):
                    flash('Group does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, None, gid, na_subject, slot))
            else:
                sid = int(na_student)
                if na_subject not in student_map.get(sid, []):
                    flash('Student does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, sid, None, na_subject, slot))

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
    teachers = c.fetchall()
    c.execute('SELECT * FROM students')
    students = [dict(s) for s in c.fetchall()]
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
    subj_map = {sub['id']: sub['name'] for sub in subjects}
    name_to_id = {sub['name'].lower(): sub['id'] for sub in subjects}
    for s in students:
        if s.get('subject_ids'):
            ids = json.loads(s['subject_ids'])
        else:
            names = json.loads(s.get('subjects') or '[]')
            ids = [name_to_id.get(n.lower()) for n in names if name_to_id.get(n.lower()) is not None]
            s['subject_ids'] = json.dumps(ids)
        s['subject_names'] = [subj_map.get(i, '') for i in ids]
    c.execute('SELECT * FROM groups')
    groups = c.fetchall()
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_map = {}
    for gm in gm_rows:
        group_map.setdefault(gm['group_id'], []).append(gm['student_id'])
    group_subj_map = {g['id']: json.loads(g['subjects']) for g in groups}
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
    c.execute('''SELECT a.id, a.teacher_id, a.student_id, a.group_id, a.subject, a.slot,
                        t.name as teacher_name,
                        s.name as student_name,
                        COALESCE(g.name, ga.name) as group_name
                 FROM fixed_assignments a
                 JOIN teachers t ON a.teacher_id = t.id
                 LEFT JOIN students s ON a.student_id = s.id
                 LEFT JOIN groups g ON a.group_id = g.id
                 LEFT JOIN groups_archive ga ON a.group_id = ga.id''')
    assignments = c.fetchall()
    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a['teacher_id'], []).append(a['slot'])
    teacher_map = {t['id']: json.loads(t['subjects']) for t in teachers}
    student_map = {s['id']: s['subject_names'] for s in students}
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
    # enforce maximum of five presets
    c.execute('SELECT id FROM config_presets ORDER BY created_at DESC')
    rows = c.fetchall()
    for r in rows[5:]:
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
    ok = restore_configuration(preset, overwrite=overwrite)
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
    min_lessons = cfg['min_lessons']
    max_lessons = cfg['max_lessons']
    teacher_min = cfg['teacher_min_lessons']
    teacher_max = cfg['teacher_max_lessons']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()

    c.execute('SELECT * FROM students WHERE active=1')
    student_rows = c.fetchall()
    c.execute('SELECT id, name FROM subjects')
    subj_rows = c.fetchall()
    id_to_name = {r['id']: r['name'] for r in subj_rows}
    students = []
    for s in student_rows:
        if s['subject_ids']:
            ids = json.loads(s['subject_ids'])
            names = [id_to_name.get(i, '') for i in ids]
        else:
            names = json.loads(s['subjects'] or '[]')
        stu = dict(s)
        stu['subjects'] = json.dumps(names)
        students.append(stu)
    c.execute('SELECT * FROM groups')
    groups = c.fetchall()
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

    # clear previous timetable, attendance logs, and worksheet assignments for the target date
    c.execute('DELETE FROM timetable WHERE date=?', (target_date,))
    c.execute('DELETE FROM attendance_log WHERE date=?', (target_date,))
    c.execute('DELETE FROM worksheets WHERE date=?', (target_date,))

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
        student_repeat[sid] = {
            'allow_repeats': bool(s['allow_repeats']) if s['allow_repeats'] is not None else allow_repeats,
            'max_repeats': s['max_repeats'] if s['max_repeats'] is not None else max_repeats,
            'allow_consecutive': bool(s['allow_consecutive']) if s['allow_consecutive'] is not None else allow_consecutive,
            'prefer_consecutive': bool(s['prefer_consecutive']) if s['prefer_consecutive'] is not None else prefer_consecutive,
        }
        student_multi[sid] = bool(s['allow_multi_teacher']) if s['allow_multi_teacher'] is not None else allow_multi_teacher
    # Build the CP-SAT model with assumption literals so that we can obtain
    # an unsat core explaining conflicts when no timetable exists.
    # incorporate groups as pseudo students
    pseudo_students = []
    for g in groups:
        ps = {"id": offset + g['id'], "subjects": g['subjects']}
        pseudo_students.append(ps)

    actual_students = [dict(s) for s in students]
    full_students = actual_students + pseudo_students

    subject_weights = {}
    if use_attendance_priority:
        c.execute('SELECT name, min_percentage FROM subjects')
        min_map = {r['name']: r['min_percentage'] or 0 for r in c.fetchall()}
        attendance_pct = {}
        for s in students:
            sid = s['id']
            required = json.loads(s['subjects'])
            c.execute('SELECT subject, COUNT(*) as cnt FROM attendance_log WHERE student_id=? GROUP BY subject', (sid,))
            rows = c.fetchall()
            total = sum(r['cnt'] for r in rows)
            counts = {r['subject']: r['cnt'] for r in rows}
            for subj in required:
                perc = (counts.get(subj, 0) / total * 100) if total else 0
                attendance_pct.setdefault(sid, {})[subj] = perc
                if perc < min_map.get(subj, 0):
                    subject_weights[(sid, subj)] = 1 + attendance_weight
                else:
                    subject_weights[(sid, subj)] = well_attend_weight
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
                if med < min_map.get(subj, 0):
                    weight = 1 + attendance_weight
                else:
                    weight = well_attend_weight
                subject_weights[(offset + gid, subj)] = weight

    loc_restrict = {}
    for sid, locs in student_loc_map.items():
        loc_restrict[sid] = locs
    for gid, locs in group_loc_map.items():
        loc_restrict[offset + gid] = locs

    model, vars_, loc_vars, assumptions = build_model(
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
        location_restrict=loc_restrict)
    status, assignments, core = solve_and_print(model, vars_, loc_vars, assumptions)

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
            c.execute('INSERT INTO timetable (student_id, group_id, teacher_id, subject, slot, location_id, date) VALUES (?, ?, ?, ?, ?, ?, ?)',
                      (sid, gid, tid, subj, slot, loc, target_date))
            if sid is not None:
                name = student_name_map.get(sid, '')
                attendance_rows.append((sid, name, subj, target_date))
            else:
                for member in group_members.get(gid, []):
                    name = student_name_map.get(member, '')
                    attendance_rows.append((member, name, subj, target_date))
        if attendance_rows:
            c.executemany('INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (?, ?, ?, ?)',
                          attendance_rows)
    else:
        from ortools.sat.python import cp_model
        if status == cp_model.INFEASIBLE:
            # Map assumption literals from the unsat core to human readable
            # messages explaining why the model is infeasible.
            reason_map = {
                'teacher_availability': 'A teacher is unavailable or blocked for a required lesson.',
                'teacher_limits': 'Teacher lesson limits are too strict.',
                'student_limits': 'Student lesson or subject requirements conflict.',
                'repeat_restrictions': 'Repeat or consecutive lesson restrictions prevent a schedule.',
            }
            flash('No feasible timetable could be generated.', 'error')
            for name in core:
                flash(reason_map.get(name, name), 'error')
    get_missing_and_counts(c, target_date, refresh=True)
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

    location_views = {'location', 'patient_only'}
    if view in location_views:
        c.execute('SELECT * FROM locations')
        columns = c.fetchall()
    else:
        c.execute(
            'SELECT id, name, subjects FROM teachers '
            "UNION ALL SELECT id, name, '[]' as subjects FROM teachers_archive"
        )
        columns = c.fetchall()

    if not target_date:
        c.execute('SELECT DISTINCT date FROM timetable ORDER BY date DESC LIMIT 1')
        row = c.fetchone()
        target_date = row['date'] if row else date.today().isoformat()

    c.execute('''SELECT t.slot,
                        COALESCE(te.name, ta.name) as teacher,
                        COALESCE(s.name, sa.name) as student,
                        COALESCE(g.name, ga.name) as group_name, t.subject, t.group_id,
                        t.teacher_id, t.student_id, t.location_id,
                        l.name AS location_name
                 FROM timetable t
                 LEFT JOIN teachers te ON t.teacher_id = te.id
                 LEFT JOIN teachers_archive ta ON t.teacher_id = ta.id
                 LEFT JOIN students s ON t.student_id = s.id
                 LEFT JOIN students_archive sa ON t.student_id = sa.id
                 LEFT JOIN groups g ON t.group_id = g.id
                 LEFT JOIN groups_archive ga ON t.group_id = ga.id
                 LEFT JOIN locations l ON t.location_id = l.id
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
    grid = {slot: {col['id']: None for col in columns} for slot in range(slots)}
    for r in rows:
        if view in location_views:
            lid = r['location_id']
            if lid is None:
                continue
            if r['group_id']:
                members = group_students.get(r['group_id'], [])
                names = ', '.join(student_names.get(m, 'Unknown') for m in members)
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
            loc = f" @ {r['location_name']}" if r['location_name'] else ''
            if r['group_id']:
                members = group_students.get(r['group_id'], [])
                names = ', '.join(student_names.get(m, 'Unknown') for m in members)
                desc = f"{r['group_name']} [{names}] ({r['subject']}){loc}"
            else:
                desc = f"{r['student']} ({r['subject']}){loc}"
            grid[r['slot']][tid] = desc

    missing, lesson_counts = get_missing_and_counts(c, target_date)
    conn.commit()
    missing_view = {
        sid: [{'subject': item['subject'], 'count': item['count'], 'today': item['assigned']}
              for item in subs]
        for sid, subs in missing.items()
    }

    conn.close()

    has_rows = bool(rows)
    return (target_date, range(slots), columns, grid, missing_view,
            student_names, slot_labels, has_rows, lesson_counts)


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
        conn.commit()
        conn.close()
    generate_schedule(gen_date)
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
     missing, student_names, slot_labels, has_rows, lesson_counts) = get_timetable_data(target_date, view=mode)
    if not has_rows:
        flash('No timetable available. Generate one from the home page.', 'error')
    return render_template('timetable.html', slots=slots, columns=columns,
                           grid=grid, json=json, date=t_date,
                           missing=missing, student_names=student_names,
                           slot_labels=slot_labels,
                           lesson_counts=lesson_counts,
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
        SELECT al.student_id AS sid, s.name AS name, al.subject, al.date
        FROM attendance_log al
        JOIN students s ON al.student_id = s.id
        WHERE s.active=1
    ''')
    active_rows = c.fetchall()
    c.execute('''
        SELECT al.student_id AS sid,
               COALESCE(sa.name, al.student_name) AS name,
               al.subject, al.date
        FROM attendance_log al
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
                    'SELECT student_id, group_id, subject FROM timetable WHERE id=? AND date=?',
                    (entry_id, date),
                )
                row = c.fetchone()
                if row:
                    subj = row['subject']
                    if row['student_id'] is not None:
                        sid = row['student_id']
                        c.execute(
                            'SELECT rowid FROM attendance_log WHERE student_id=? AND subject=? AND date=? LIMIT 1',
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
                                'SELECT rowid FROM attendance_log WHERE student_id=? AND subject=? AND date=? LIMIT 1',
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
                student_id = None
                group_id = None
                if student_group.startswith('s'):
                    student_id = int(student_group[1:])
                elif student_group.startswith('g'):
                    group_id = int(student_group[1:])
                location_id = int(location) if location else None
                c.execute(
                    'INSERT INTO timetable (student_id, group_id, teacher_id, subject, slot, location_id, date) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (student_id, group_id, teacher_id, subject, slot, location_id, date),
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
                        'INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (?, ?, ?, ?)',
                        (student_id, name, subject, date),
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
                        rows.append((sid, name, subject, date))
                    if rows:
                        c.executemany(
                            'INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (?, ?, ?, ?)',
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
                    'SELECT student_id, group_id, subject FROM timetable WHERE id=? AND date=?',
                    (entry_id, date),
                )
                old = c.fetchone()
                if old:
                    old_subj = old['subject']
                    if old['student_id'] is not None:
                        sid = old['student_id']
                        c.execute(
                            'SELECT rowid FROM attendance_log WHERE student_id=? AND subject=? AND date=? LIMIT 1',
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
                                'SELECT rowid FROM attendance_log WHERE student_id=? AND subject=? AND date=? LIMIT 1',
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
                c.execute(
                    'UPDATE timetable SET student_id=?, group_id=?, subject=?, location_id=? WHERE id=? AND date=?',
                    (new_student_id, new_group_id, subject, location_id, entry_id, date),
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
                        'INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (?, ?, ?, ?)',
                        (new_student_id, name, subject, date),
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
                        rows.append((sid, name, subject, date))
                    if rows:
                        c.executemany(
                            'INSERT INTO attendance_log (student_id, student_name, subject, date) VALUES (?, ?, ?, ?)',
                            rows,
                        )
                get_missing_and_counts(c, date, refresh=True)
                conn.commit()
                flash('Lesson updated.', 'info')
        elif action == 'worksheet':
            student_id = request.form.get('student_id')
            subject = request.form.get('subject')
            assign = request.form.get('assign')
            if student_id and subject and assign is not None:
                sid = int(student_id)
                c.execute(
                    'SELECT id FROM subjects WHERE LOWER(name)=LOWER(?)',
                    (subject,),
                )
                row = c.fetchone()
                if row:
                    subj_id = row['id']
                    if assign == '1':
                        c.execute(
                            'SELECT 1 FROM worksheets WHERE student_id=? AND subject_id=? AND date=?',
                            (sid, subj_id, date),
                        )
                        if c.fetchone() is None:
                            c.execute(
                                'INSERT INTO worksheets (student_id, subject, subject_id, date) VALUES (?, ?, ?, ?)',
                                (sid, subject, subj_id, date),
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
    teachers = c.fetchall()

    # Existing lessons with teacher id for grid placement
    c.execute(
        '''SELECT t.id, t.slot, t.subject, t.teacher_id, t.student_id, t.group_id,
                  t.location_id, COALESCE(s.name, sa.name) AS student_name,
                  COALESCE(g.name, ga.name) AS group_name, l.name AS location_name
           FROM timetable t
           LEFT JOIN students s ON t.student_id = s.id
           LEFT JOIN students_archive sa ON t.student_id = sa.id
           LEFT JOIN groups g ON t.group_id = g.id
           LEFT JOIN groups_archive ga ON t.group_id = ga.id
           LEFT JOIN locations l ON t.location_id = l.id
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
            'location_id': les['location_id'],
        }

    c.execute('SELECT id, name FROM students')
    students = c.fetchall()
    c.execute('SELECT id, name FROM groups')
    groups = c.fetchall()
    c.execute('SELECT name FROM subjects')
    subjects = [r['name'] for r in c.fetchall()]
    c.execute('SELECT id, name FROM locations')
    locations = c.fetchall()

    # compute unassigned subjects and worksheet counts
    c.execute('SELECT id, name, subjects, active FROM students')
    student_rows = c.fetchall()
    student_names = {s['id']: s['name'] for s in student_rows}
    c.execute('SELECT id, name FROM students_archive')
    for row in c.fetchall():
        student_names.setdefault(row['id'], row['name'])

    missing, lesson_counts = get_missing_and_counts(c, date)
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
