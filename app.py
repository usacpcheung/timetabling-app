from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import json
import os

from cp_sat_timetable import build_model, solve_and_print

app = Flask(__name__)
app.secret_key = 'dev'
DB_PATH = os.path.join(os.path.dirname(__file__), 'timetable.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    # drop old tables when schema changes
    c.execute('DROP TABLE IF EXISTS config')
    c.execute('DROP TABLE IF EXISTS teachers')
    c.execute('DROP TABLE IF EXISTS students')
    c.execute('DROP TABLE IF EXISTS subjects')
    c.execute('DROP TABLE IF EXISTS teacher_unavailable')
    c.execute('DROP TABLE IF EXISTS fixed_assignments')
    c.execute('DROP TABLE IF EXISTS timetable')

    c.execute('''CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY,
        slots_per_day INTEGER,
        slot_duration INTEGER,
        lesson_duration INTEGER,
        min_lessons INTEGER,
        max_lessons INTEGER,
        teacher_min_lessons INTEGER,
        teacher_max_lessons INTEGER,
        allow_repeats INTEGER,
        max_repeats INTEGER,
        prefer_consecutive INTEGER,
        allow_consecutive INTEGER,
        consecutive_weight INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        subjects TEXT,
        min_lessons INTEGER,
        max_lessons INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        subjects TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS teacher_unavailable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        slot INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS fixed_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        student_id INTEGER,
        subject TEXT,
        slot INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        teacher_id INTEGER,
        subject TEXT,
        slot INTEGER
    )''')
    conn.commit()

    # insert defaults if tables empty
    c.execute('SELECT COUNT(*) FROM config')
    if c.fetchone()[0] == 0:
        c.execute('''INSERT INTO config (
            id, slots_per_day, slot_duration, lesson_duration,
            min_lessons, max_lessons, teacher_min_lessons, teacher_max_lessons,
            allow_repeats, max_repeats,
            prefer_consecutive, allow_consecutive, consecutive_weight
        ) VALUES (1, 8, 30, 30, 1, 4, 1, 4, 0, 2, 0, 1, 3)''')
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
        subjects = [('Math',), ('English',), ('Science',), ('History',)]
        c.executemany('INSERT INTO subjects (name) VALUES (?)', subjects)
    conn.commit()
    conn.close()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/config', methods=['GET', 'POST'])
def config():
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        slots_per_day = int(request.form['slots_per_day'])
        slot_duration = int(request.form['slot_duration'])
        lesson_duration = int(request.form['lesson_duration'])
        min_lessons = int(request.form['min_lessons'])
        max_lessons = int(request.form['max_lessons'])
        t_min_lessons = int(request.form['teacher_min_lessons'])
        t_max_lessons = int(request.form['teacher_max_lessons'])
        if t_min_lessons > t_max_lessons:
            flash('Global teacher min lessons cannot exceed max lessons', 'error')
            t_min_lessons = t_max_lessons
        allow_repeats = 1 if request.form.get('allow_repeats') else 0
        max_repeats = int(request.form['max_repeats'])
        prefer_consecutive = 1 if request.form.get('prefer_consecutive') else 0
        allow_consecutive = 1 if request.form.get('allow_consecutive') else 0
        consecutive_weight = int(request.form['consecutive_weight'])

        if not allow_repeats:
            allow_consecutive = 0
            prefer_consecutive = 0
        else:
            if not allow_consecutive and prefer_consecutive:
                prefer_consecutive = 0
                flash('Cannot prefer consecutive slots when consecutive repeats are disallowed.',
                      'error')
            if max_repeats < 2:
                max_repeats = 2
        c.execute('''UPDATE config SET slots_per_day=?, slot_duration=?, lesson_duration=?,
                     min_lessons=?, max_lessons=?, teacher_min_lessons=?, teacher_max_lessons=?,
                     allow_repeats=?, max_repeats=?,
                     prefer_consecutive=?, allow_consecutive=?, consecutive_weight=? WHERE id=1''',
                  (slots_per_day, slot_duration, lesson_duration, min_lessons,
                   max_lessons, t_min_lessons, t_max_lessons,
                   allow_repeats, max_repeats, prefer_consecutive,
                   allow_consecutive, consecutive_weight))
        # update subjects
        subj_ids = request.form.getlist('subject_id')
        deletes_sub = set(request.form.getlist('subject_delete'))
        for sid in subj_ids:
            name = request.form.get(f'subject_name_{sid}')
            if sid in deletes_sub:
                c.execute('DELETE FROM subjects WHERE id=?', (int(sid),))
            else:
                c.execute('UPDATE subjects SET name=? WHERE id=?', (name, int(sid)))
        new_sub = request.form.get('new_subject_name')
        if new_sub:
            c.execute('INSERT INTO subjects (name) VALUES (?)', (new_sub,))

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
            else:
                c.execute('INSERT INTO teachers (name, subjects, min_lessons, max_lessons) VALUES (?, ?, ?, ?)',
                          (new_tname, subj_json, min_val, max_val))

        # update students
        student_ids = request.form.getlist('student_id')
        for sid in student_ids:
            if request.form.get(f'student_delete_{sid}'):
                c.execute('DELETE FROM students WHERE id=?', (int(sid),))
            else:
                name = request.form.get(f'student_name_{sid}')
                subs = request.form.getlist(f'student_subjects_{sid}')
                subj_json = json.dumps(subs)
                c.execute('UPDATE students SET name=?, subjects=? WHERE id=?', (name, subj_json, int(sid)))
        new_sname = request.form.get('new_student_name')
        new_ssubs = request.form.getlist('new_student_subjects')
        if new_sname and new_ssubs:
            subj_json = json.dumps(new_ssubs)
            c.execute('INSERT INTO students (name, subjects) VALUES (?, ?)', (new_sname, subj_json))

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
            elif (tid, slot) in unav_set:
                flash('Teacher already unavailable in that slot', 'error')
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
        c.execute('SELECT teacher_id, slot FROM teacher_unavailable')
        unav = c.fetchall()
        unav_set = {(u['teacher_id'], u['slot']) for u in unav}
        c.execute('SELECT teacher_id, slot FROM fixed_assignments')
        fixed = c.fetchall()
        fixed_set = {(f['teacher_id'], f['slot']) for f in fixed}

        if na_student and na_teacher and na_subject and na_slot:
            tid = int(na_teacher)
            sid = int(na_student)
            slot = int(na_slot) - 1
            if na_subject not in teacher_map.get(tid, []):
                flash('Teacher does not teach the selected subject', 'error')
            elif na_subject not in student_map.get(sid, []):
                flash('Student does not require the selected subject', 'error')
            elif (tid, slot) in unav_set:
                flash('Teacher is unavailable in the selected slot', 'error')
            elif (tid, slot) in fixed_set:
                flash('Duplicate fixed assignment for that slot', 'error')
            else:
                c.execute('INSERT INTO fixed_assignments (teacher_id, student_id, subject, slot) VALUES (?, ?, ?, ?)',
                          (tid, sid, na_subject, slot))

        conn.commit()
        conn.close()
        return redirect(url_for('config'))

    # load config
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    c.execute('SELECT * FROM students')
    students = c.fetchall()
    c.execute('SELECT * FROM subjects')
    subjects = c.fetchall()
    c.execute('''SELECT u.id, u.teacher_id, u.slot, t.name as teacher_name
                 FROM teacher_unavailable u JOIN teachers t ON u.teacher_id = t.id''')
    unavailable = c.fetchall()
    c.execute('''SELECT a.id, a.teacher_id, a.student_id, a.subject, a.slot,
                        t.name as teacher_name, s.name as student_name
                 FROM fixed_assignments a
                 JOIN teachers t ON a.teacher_id = t.id
                 JOIN students s ON a.student_id = s.id''')
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
                           students=students, subjects=subjects,
                           unavailable=unavailable, assignments=assignments,
                           teacher_map=teacher_map, student_map=student_map,
                           unavail_map=unavail_map, assign_map=assign_map,
                           json=json)


def analyze_infeasibility(students, teachers, slots, cfg, unavailable, fixed):
    """Return human readable messages about conflicting constraints."""
    teacher_unavail = {t['id']: set() for t in teachers}
    for u in unavailable:
        teacher_unavail[u['teacher_id']].add(u['slot'])
    teacher_fixed = {t['id']: 0 for t in teachers}
    for f in fixed:
        teacher_fixed[f['teacher_id']] += 1

    messages = []
    for t in teachers:
        min_req = t['min_lessons'] if t['min_lessons'] is not None else cfg['teacher_min_lessons']
        max_allow = t['max_lessons'] if t['max_lessons'] is not None else cfg['teacher_max_lessons']
        avail = slots - len(teacher_unavail[t['id']])
        if avail < min_req:
            messages.append(f"Teacher {t['name']} has only {avail} available slots but requires at least {min_req}.")
        if teacher_fixed[t['id']] > max_allow:
            messages.append(f"Teacher {t['name']} has {teacher_fixed[t['id']]} fixed lessons exceeding maximum {max_allow}.")

    for s in students:
        subs = json.loads(s['subjects'])
        missing = []
        for sub in subs:
            avail_teachers = [t for t in teachers if sub in json.loads(t['subjects']) and len(set(range(slots)) - teacher_unavail[t['id']]) > 0]
            if not avail_teachers:
                missing.append(sub)
        if missing:
            messages.append(f"No teacher available for student {s['name']} subject(s): {', '.join(missing)}")

    if not messages:
        messages.append('Configuration too restrictive; adjust lesson limits or availability.')
    return messages


def generate_schedule():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']
    min_lessons = cfg['min_lessons']
    max_lessons = cfg['max_lessons']
    teacher_min = cfg['teacher_min_lessons']
    teacher_max = cfg['teacher_max_lessons']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    c.execute('SELECT * FROM students')
    students = c.fetchall()
    c.execute('SELECT * FROM teacher_unavailable')
    unavailable = c.fetchall()
    c.execute('SELECT * FROM fixed_assignments')
    assignments_fixed = c.fetchall()

    # clear previous timetable
    c.execute('DELETE FROM timetable')

    # Build and solve CP-SAT model
    allow_repeats = bool(cfg['allow_repeats'])
    max_repeats = cfg['max_repeats']
    prefer_consecutive = bool(cfg['prefer_consecutive'])
    allow_consecutive = bool(cfg['allow_consecutive'])
    consecutive_weight = cfg['consecutive_weight']
    model, vars_ = build_model(
        students, teachers, slots, min_lessons, max_lessons,
        allow_repeats=allow_repeats, max_repeats=max_repeats,
        prefer_consecutive=prefer_consecutive, allow_consecutive=allow_consecutive,
        consecutive_weight=consecutive_weight,
        unavailable=unavailable, fixed=assignments_fixed,
        teacher_min_lessons=teacher_min, teacher_max_lessons=teacher_max)
    status, assignments = solve_and_print(model, vars_)

    # Insert solver results into DB
    if assignments:
        for sid, tid, subj, slot in assignments:
            c.execute(
                'INSERT INTO timetable (student_id, teacher_id, subject, slot) VALUES (?, ?, ?, ?)',
                (sid, tid, subj, slot)
            )
    else:
        from ortools.sat.python import cp_model
        if status == cp_model.INFEASIBLE:
            msgs = analyze_infeasibility(students, teachers, slots, cfg, unavailable, assignments_fixed)
            flash('No feasible timetable could be generated.', 'error')
            for m in msgs:
                flash(m, 'error')

    conn.commit()
    conn.close()


@app.route('/generate')
def generate():
    generate_schedule()
    return redirect(url_for('timetable'))


@app.route('/timetable')
def timetable():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    c.execute('''SELECT t.slot, te.name as teacher, s.name as student, t.subject
                 FROM timetable t
                 JOIN teachers te ON t.teacher_id = te.id
                 JOIN students s ON t.student_id = s.id''')
    rows = c.fetchall()
    conn.close()

    if not rows:
        flash('No timetable available. Generate one from the home page.', 'error')

    # build grid [slot][teacher] => student
    grid = {slot: {te['id']: None for te in teachers} for slot in range(slots)}
    for r in rows:
        # get teacher id by name
        tid = next(te['id'] for te in teachers if te['name'] == r['teacher'])
        grid[r['slot']][tid] = f"{r['student']} ({r['subject']})"

    return render_template('timetable.html', slots=range(slots), teachers=teachers, grid=grid, json=json)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
