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

from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import json
import os
from datetime import date
import statistics

from cp_sat_timetable import build_model, solve_and_print

app = Flask(__name__)
app.secret_key = 'dev'
DB_PATH = os.path.join(os.path.dirname(__file__), 'timetable.db')


def get_db():
    """Return a connection to the SQLite database.

    Each view function calls this helper to obtain a connection. Setting
    ``row_factory`` allows rows to behave like dictionaries so template
    code can access columns by name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the SQLite tables and populate default rows.

    This function also performs simple migrations when new columns are added in
    later versions of the code. It is called on start-up and whenever the
    database is reset via the web interface."""
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

    if not table_exists('students'):
        c.execute('''CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            subjects TEXT,
            active INTEGER DEFAULT 1
        )''')
    elif not column_exists('students', 'active'):
        c.execute('ALTER TABLE students ADD COLUMN active INTEGER DEFAULT 1')

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
            date TEXT
        )''')
    else:
        if not column_exists('timetable', 'date'):
            c.execute('ALTER TABLE timetable ADD COLUMN date TEXT')
        if not column_exists('timetable', 'group_id'):
            c.execute('ALTER TABLE timetable ADD COLUMN group_id INTEGER')

    if not table_exists('attendance_log'):
        c.execute('''CREATE TABLE attendance_log (
            student_id INTEGER,
            student_name TEXT,
            subject TEXT,
            date TEXT
        )''')

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

    if not table_exists('student_teacher_block'):
        c.execute('''CREATE TABLE student_teacher_block (
            student_id INTEGER,
            teacher_id INTEGER,
            PRIMARY KEY(student_id, teacher_id)
        )''')

    conn.commit()

    # insert defaults if tables empty
    c.execute('SELECT COUNT(*) FROM config')
    if c.fetchone()[0] == 0:
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
    c.execute('SELECT COUNT(*) FROM teachers')
    if c.fetchone()[0] == 0:
        teachers = [
            ('Teacher A', json.dumps(['Math', 'English']), None, None),
            ('Teacher B', json.dumps(['Science']), None, None),
            ('Teacher C', json.dumps(['History']), None, None),
        ]
        c.executemany('INSERT INTO teachers (name, subjects, min_lessons, max_lessons) VALUES (?, ?, ?, ?)', teachers)
    c.execute('SELECT COUNT(*) FROM students')
    if c.fetchone()[0] == 0:
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
    c.execute('SELECT COUNT(*) FROM subjects')
    if c.fetchone()[0] == 0:
        subjects = [
            ('Math', 0),
            ('English', 0),
            ('Science', 0),
            ('History', 0)
        ]
        c.executemany('INSERT INTO subjects (name, min_percentage) VALUES (?, ?)', subjects)
    conn.commit()
    conn.close()


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
    context = {'today': date.today().isoformat()}
    if selected:
        data = get_timetable_data(selected)
        (sel_date, slots, teachers, grid, missing,
         student_names, slot_labels, has_rows) = data
        if not has_rows:
            flash('No timetable available. Generate one from the home page.',
                  'error')
        context.update({
            'show_timetable': has_rows,
            'date': sel_date,
            'slots': slots,
            'teachers': teachers,
            'grid': grid,
            'missing': missing,
            'student_names': student_names,
            'slot_labels': slot_labels,
            'has_rows': has_rows,
            'json': json
        })
    return render_template('index.html', **context)

# Helper used when validating student-teacher blocks
# Returns True if blocking is allowed, otherwise False.
def block_allowed(student_id, teacher_id, teacher_map, student_groups,
                  group_members, group_subj_map, block_map, fixed_pairs):
    if (student_id, teacher_id) in fixed_pairs:
        return False
    tmp_map = {sid: set(tids) for sid, tids in block_map.items()}
    tmp_map.setdefault(student_id, set()).add(teacher_id)
    for gid in student_groups.get(student_id, []):
        members = group_members.get(gid, [])
        for subj in group_subj_map.get(gid, []):
            avail = []
            for tid, subs in teacher_map.items():
                if subj in subs and all(tid not in tmp_map.get(m, set()) for m in members):
                    avail.append(tid)
            if len(avail) == 1 and avail[0] == teacher_id:
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
                c.execute('DELETE FROM teachers WHERE id=?', (int(tid),))
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
                c.execute('SELECT name FROM students WHERE id=?', (int(sid),))
                row = c.fetchone()
                if row:
                    c.execute('INSERT OR IGNORE INTO students_archive (id, name) VALUES (?, ?)',
                              (int(sid), row['name']))
                c.execute('DELETE FROM students WHERE id=?', (int(sid),))
                c.execute('DELETE FROM student_teacher_block WHERE student_id=?', (int(sid),))
            else:
                name = request.form.get(f'student_name_{sid}')
                subs = request.form.getlist(f'student_subjects_{sid}')
                active = 1 if request.form.get(f'student_active_{sid}') else 0
                subj_json = json.dumps(subs)
                c.execute('UPDATE students SET name=?, subjects=?, active=? WHERE id=?',
                          (name, subj_json, active, int(sid)))
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
        new_ssubs = request.form.getlist('new_student_subjects')
        new_blocks = request.form.getlist('new_student_block')
        if new_sname and new_ssubs:
            subj_json = json.dumps(new_ssubs)
            c.execute('INSERT INTO students (name, subjects, active) VALUES (?, ?, 1)',
                      (new_sname, subj_json))
            new_sid = c.lastrowid
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

        # maps used for group validation
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

        # update groups
        group_ids = request.form.getlist('group_id')
        deletes_grp = set(request.form.getlist('group_delete'))
        for gid in group_ids:
            if gid in deletes_grp:
                c.execute('DELETE FROM groups WHERE id=?', (int(gid),))
                c.execute('DELETE FROM group_members WHERE group_id=?', (int(gid),))
                continue
            name = request.form.get(f'group_name_{gid}')
            subs = request.form.getlist(f'group_subjects_{gid}')
            members = request.form.getlist(f'group_members_{gid}')
            if not subs or not members:
                flash(f'Group {name} must have at least one subject and member', 'error')
                has_error = True
                continue
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

        # update teacher unavailability
        unavail_ids = request.form.getlist('unavail_id')
        del_unav = set(request.form.getlist('unavail_delete'))
        for uid in unavail_ids:
            if uid in del_unav:
                c.execute('DELETE FROM teacher_unavailable WHERE id=?', (int(uid),))
        nu_teacher = request.form.get('new_unavail_teacher')
        nu_slot = request.form.get('new_unavail_slot')

        c.execute('SELECT teacher_id, slot FROM teacher_unavailable')
        unav = c.fetchall()
        unav_set = {(u['teacher_id'], u['slot']) for u in unav}
        c.execute('SELECT teacher_id, slot FROM fixed_assignments')
        fixed = c.fetchall()
        fixed_set = {(f['teacher_id'], f['slot']) for f in fixed}

        if nu_teacher and nu_slot:
            tid = int(nu_teacher)
            slot = int(nu_slot) - 1
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
        c.execute('SELECT id, subjects FROM students')
        srows = c.fetchall()
        student_map = {s["id"]: json.loads(s["subjects"]) for s in srows}
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
            elif na_student:
                sid = int(na_student)
                if na_subject not in student_map.get(sid, []):
                    flash('Student does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, sid, None, na_subject, slot))
            else:
                gid = int(na_group)
                if na_subject not in group_subj.get(gid, []):
                    flash('Group does not require the selected subject', 'error')
                    has_error = True
                else:
                    c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, group_id, subject, slot) VALUES (?, ?, ?, ?, ?)',
                              (tid, None, gid, na_subject, slot))

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
    students = c.fetchall()
    c.execute('SELECT student_id, teacher_id FROM student_teacher_block')
    st_rows = c.fetchall()
    block_map = {}
    for r in st_rows:
        block_map.setdefault(r['student_id'], []).append(r['teacher_id'])
    c.execute('SELECT * FROM subjects')
    subjects = c.fetchall()
    c.execute('SELECT * FROM groups')
    groups = c.fetchall()
    c.execute('SELECT group_id, student_id FROM group_members')
    gm_rows = c.fetchall()
    group_map = {}
    for gm in gm_rows:
        group_map.setdefault(gm['group_id'], []).append(gm['student_id'])
    group_subj_map = {g['id']: json.loads(g['subjects']) for g in groups}
    c.execute('''SELECT u.id, u.teacher_id, u.slot, t.name as teacher_name
                 FROM teacher_unavailable u JOIN teachers t ON u.teacher_id = t.id''')
    unavailable = c.fetchall()
    c.execute('''SELECT a.id, a.teacher_id, a.student_id, a.group_id, a.subject, a.slot,
                        t.name as teacher_name,
                        s.name as student_name,
                        g.name as group_name
                 FROM fixed_assignments a
                 JOIN teachers t ON a.teacher_id = t.id
                 LEFT JOIN students s ON a.student_id = s.id
                 LEFT JOIN groups g ON a.group_id = g.id''')
    assignments = c.fetchall()
    assign_map = {}
    for a in assignments:
        assign_map.setdefault(a['teacher_id'], []).append(a['slot'])
    teacher_map = {t['id']: json.loads(t['subjects']) for t in teachers}
    student_map = {s['id']: json.loads(s['subjects']) for s in students}
    unavail_map = {}
    for u in unavailable:
        unavail_map.setdefault(u['teacher_id'], []).append(u['slot'])
    conn.close()

    return render_template('config.html', config=cfg, teachers=teachers,
                           students=students, subjects=subjects, groups=groups,
                           unavailable=unavailable, assignments=assignments,
                           teacher_map=teacher_map, student_map=student_map,
                           unavail_map=unavail_map, assign_map=assign_map,
                           group_map=group_map, group_subj_map=group_subj_map,
                           block_map=block_map, json=json,
                           slot_times=slot_times)


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
    students = c.fetchall()
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
    c.execute('SELECT * FROM fixed_assignments')
    arows = c.fetchall()
    assignments_fixed = []
    for r in arows:
        row = dict(r)
        if row.get('group_id'):
            row['student_id'] = offset + row['group_id']
        assignments_fixed.append(row)

    # clear previous timetable and attendance logs for the target date
    c.execute('DELETE FROM timetable WHERE date=?', (target_date,))
    c.execute('DELETE FROM attendance_log WHERE date=?', (target_date,))

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

    model, vars_, assumptions = build_model(
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
        blocked=block_map_sched)
    status, assignments, core = solve_and_print(model, vars_, assumptions)

    # Insert solver results into DB
    if assignments:
        group_lessons = set()
        filtered = []
        for sid, tid, subj, slot in assignments:
            if sid >= offset:
                gid = sid - offset
                group_lessons.add((gid, tid, subj, slot))
                filtered.append((None, gid, tid, subj, slot))
        for sid, tid, subj, slot in assignments:
            if sid >= offset:
                continue
            skip = False
            for gid in student_groups.get(sid, []):
                if subj in group_subjects.get(gid, []) and (gid, tid, subj, slot) in group_lessons:
                    skip = True
                    break
            if not skip:
                filtered.append((sid, None, tid, subj, slot))

        attendance_rows = []
        for entry in filtered:
            sid, gid, tid, subj, slot = entry
            c.execute('INSERT INTO timetable (student_id, group_id, teacher_id, subject, slot, date) VALUES (?, ?, ?, ?, ?, ?)',
                      (sid, gid, tid, subj, slot, target_date))
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

    conn.commit()
    conn.close()


def get_timetable_data(target_date):
    """Return timetable grid data for the given date."""
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

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    if not target_date:
        c.execute('SELECT DISTINCT date FROM timetable ORDER BY date DESC LIMIT 1')
        row = c.fetchone()
        target_date = row['date'] if row else date.today().isoformat()

    c.execute('''SELECT t.slot, te.name as teacher,
                        COALESCE(s.name, sa.name) as student,
                        g.name as group_name, t.subject, t.group_id, t.teacher_id, t.student_id
                 FROM timetable t
                 JOIN teachers te ON t.teacher_id = te.id
                 LEFT JOIN students s ON t.student_id = s.id
                 LEFT JOIN students_archive sa ON t.student_id = sa.id
                 LEFT JOIN groups g ON t.group_id = g.id
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
    conn.close()

    grid = {slot: {te['id']: None for te in teachers} for slot in range(slots)}
    for r in rows:
        tid = r['teacher_id']
        if r['group_id']:
            members = group_students.get(r['group_id'], [])
            names = ', '.join(student_names.get(m, 'Unknown') for m in members)
            desc = f"{r['group_name']} [{names}] ({r['subject']})"
        else:
            desc = f"{r['student']} ({r['subject']})"
        grid[r['slot']][tid] = desc

    assigned = {s['id']: set() for s in student_rows}
    for r in rows:
        subj = r['subject']
        if r['group_id']:
            for sid in group_students.get(r['group_id'], []):
                assigned.setdefault(sid, set()).add(subj)
        elif r['student_id']:
            assigned.setdefault(r['student_id'], set()).add(subj)
    missing = {}
    for s in student_rows:
        if not s['active']:
            continue
        required = set(json.loads(s['subjects']))
        miss = required - assigned.get(s['id'], set())
        if miss:
            missing[s['id']] = sorted(miss)

    has_rows = bool(rows)
    return target_date, range(slots), teachers, grid, missing, student_names, slot_labels, has_rows


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
        conn.commit()
        conn.close()
    generate_schedule(gen_date)
    return redirect(url_for('index', date=gen_date))


@app.route('/timetable')
def timetable():
    """Render a grid of the lessons scheduled for a particular date.

    Each column shows a teacher while each row represents a time slot. The
    page also lists any subjects that could not be scheduled for active
    students.
    """
    target_date = request.args.get('date')
    (t_date, slots, teachers, grid,
     missing, student_names, slot_labels, has_rows) = get_timetable_data(target_date)
    if not has_rows:
        flash('No timetable available. Generate one from the home page.', 'error')
    return render_template('timetable.html', slots=slots, teachers=teachers,
                           grid=grid, json=json, date=t_date,
                           missing=missing, student_names=student_names,
                           slot_labels=slot_labels)


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
        SELECT al.student_id AS sid, sa.name AS name, al.subject, al.date
        FROM attendance_log al
        JOIN students_archive sa ON al.student_id = sa.id
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
    return render_template('manage_timetables.html', dates=dates)


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
        conn.commit()
        conn.close()
        flash('All timetables deleted.', 'info')
        return redirect(url_for('manage_timetables'))

    dates = request.form.getlist('dates')
    if dates:
        for d in dates:
            c.execute('DELETE FROM timetable WHERE date=?', (d,))
            c.execute('DELETE FROM attendance_log WHERE date=?', (d,))
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


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
