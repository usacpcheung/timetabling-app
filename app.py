from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import json
import os

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), 'timetable.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY,
        slots_per_day INTEGER,
        slot_duration INTEGER,
        lesson_duration INTEGER,
        min_lessons INTEGER,
        max_lessons INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        subject TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        subjects TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teacher_restrictions (
        teacher_id INTEGER,
        student_id INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS teacher_unavailability (
        teacher_id INTEGER,
        start_slot INTEGER,
        end_slot INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS subject_distribution (
        student_id INTEGER,
        subject TEXT,
        percent_min REAL,
        percent_max REAL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS subject_distribution_global (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        percent_min REAL,
        percent_max REAL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS slot_times (
        slot INTEGER PRIMARY KEY,
        start_time TEXT
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
        c.execute('INSERT INTO config (id, slots_per_day, slot_duration, lesson_duration, min_lessons, max_lessons) VALUES (1, 8, 30, 30, 1, 4)')
    c.execute('SELECT COUNT(*) FROM teachers')
    if c.fetchone()[0] == 0:
        teachers = [
            ('Teacher A', 'Math'),
            ('Teacher B', 'English'),
            ('Teacher C', 'Science'),
            ('Teacher D', 'History')
        ]
        c.executemany('INSERT INTO teachers (name, subject) VALUES (?, ?)', teachers)
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
    c.execute('SELECT COUNT(*) FROM slot_times')
    if c.fetchone()[0] == 0:
        start_minutes = 8 * 60 + 30
        duration = 30
        for s in range(8):
            mins = start_minutes + duration * s
            hour = mins // 60
            minute = mins % 60
            c.execute('INSERT INTO slot_times (slot, start_time) VALUES (?, ?)',
                      (s, f"{hour:02d}:{minute:02d}"))
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
        lesson_duration = int(request.form['lesson_duration'])
        slot_duration = lesson_duration
        min_lessons = int(request.form['min_lessons'])
        max_lessons = int(request.form['max_lessons'])
        c.execute('UPDATE config SET slots_per_day=?, slot_duration=?, lesson_duration=?, min_lessons=?, max_lessons=? WHERE id=1',
                  (slots_per_day, slot_duration, lesson_duration, min_lessons, max_lessons))
        # update teachers
        teacher_ids = request.form.getlist('teacher_id')
        teacher_names = request.form.getlist('teacher_name')
        teacher_subjects = request.form.getlist('teacher_subject')
        for tid, name, subj in zip(teacher_ids, teacher_names, teacher_subjects):
            if tid:
                c.execute('UPDATE teachers SET name=?, subject=? WHERE id=?', (name, subj, int(tid)))
                restrict_ids = request.form.getlist(f'teacher_restrict_{tid}')
                c.execute('DELETE FROM teacher_restrictions WHERE teacher_id=?', (int(tid),))
                for sid in restrict_ids:
                    c.execute('INSERT INTO teacher_restrictions (teacher_id, student_id) VALUES (?, ?)',
                              (int(tid), int(sid)))
                unavail_slots = request.form.getlist(f'teacher_unavail_{tid}')
                c.execute('DELETE FROM teacher_unavailability WHERE teacher_id=?', (int(tid),))
                for sl in unavail_slots:
                    c.execute('INSERT INTO teacher_unavailability (teacher_id, start_slot, end_slot) VALUES (?, ?, ?)',
                              (int(tid), int(sl)-1, int(sl)-1))

        new_t_name = request.form.get('new_teacher_name', '').strip()
        new_t_subject = request.form.get('new_teacher_subject', '').strip()
        if new_t_name and new_t_subject:
            c.execute('INSERT INTO teachers (name, subject) VALUES (?, ?)', (new_t_name, new_t_subject))
        # update students
        student_ids = request.form.getlist('student_id')
        student_names = request.form.getlist('student_name')
        student_subjects = request.form.getlist('student_subjects')
        for sid, name, subj in zip(student_ids, student_names, student_subjects):
            if sid:
                subj_json = json.dumps([s.strip() for s in subj.split(',') if s.strip()])
                c.execute('UPDATE students SET name=?, subjects=? WHERE id=?', (name, subj_json, int(sid)))
                dist = request.form.get(f'student_dist_{sid}', '')
                c.execute('DELETE FROM subject_distribution WHERE student_id=?', (int(sid),))
                for item in [d.strip() for d in dist.split(';') if ':' in d]:
                    subject, rng = item.split(':',1)
                    if '-' in rng:
                        pmin, pmax = rng.split('-',1)
                    else:
                        pmin = pmax = rng
                    c.execute('INSERT INTO subject_distribution (student_id, subject, percent_min, percent_max) VALUES (?, ?, ?, ?)',
                              (int(sid), subject.strip(), float(pmin), float(pmax)))
        new_name = request.form.get('new_student_name', '').strip()
        new_subj = request.form.get('new_student_subjects', '').strip()
        if new_name and new_subj:
            subj_json = json.dumps([s.strip() for s in new_subj.split(',') if s.strip()])
            c.execute('INSERT INTO students (name, subjects) VALUES (?, ?)', (new_name, subj_json))
        for i in range(slots_per_day):
            time_str = request.form.get(f'slot_time_{i}', '')
            if time_str:
                c.execute('INSERT OR REPLACE INTO slot_times (slot, start_time) VALUES (?, ?)', (i, time_str))

        # global subject distribution
        g_ids = request.form.getlist('global_dist_id')
        g_subjects = request.form.getlist('global_dist_subject')
        g_mins = request.form.getlist('global_dist_min')
        g_maxs = request.form.getlist('global_dist_max')
        for gid, subj, pmin, pmax in zip(g_ids, g_subjects, g_mins, g_maxs):
            if gid:
                if subj.strip() == '':
                    c.execute('DELETE FROM subject_distribution_global WHERE id=?', (int(gid),))
                else:
                    c.execute('UPDATE subject_distribution_global SET subject=?, percent_min=?, percent_max=? WHERE id=?',
                              (subj.strip(), float(pmin), float(pmax), int(gid)))
        new_g_subj = request.form.get('new_global_subject', '').strip()
        new_g_min = request.form.get('new_global_min', '')
        new_g_max = request.form.get('new_global_max', '')
        if new_g_subj and new_g_min and new_g_max:
            c.execute('INSERT INTO subject_distribution_global (subject, percent_min, percent_max) VALUES (?, ?, ?)',
                      (new_g_subj, float(new_g_min), float(new_g_max)))
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
    c.execute('SELECT * FROM teacher_restrictions')
    restr_rows = c.fetchall()
    teacher_restrict = {}
    for r in restr_rows:
        teacher_restrict.setdefault(r['teacher_id'], []).append(str(r['student_id']))
    c.execute('SELECT * FROM teacher_unavailability')
    unavail_rows = c.fetchall()
    teacher_unavail = {}
    for r in unavail_rows:
        for s in range(r['start_slot'], r['end_slot']+1):
            teacher_unavail.setdefault(r['teacher_id'], []).append(str(s+1))
    c.execute('SELECT * FROM subject_distribution')
    dist_rows = c.fetchall()
    student_dist = {}
    for r in dist_rows:
        student_dist.setdefault(r['student_id'], []).append(f"{r['subject']}:{r['percent_min']}-{r['percent_max']}")
    c.execute('SELECT * FROM subject_distribution_global')
    global_dist_rows = c.fetchall()
    c.execute('SELECT * FROM slot_times ORDER BY slot')
    slot_rows = c.fetchall()
    slot_times = {row['slot']: row['start_time'] for row in slot_rows}
    conn.close()
    return render_template('config.html', config=cfg, teachers=teachers, students=students,
                           json=json, teacher_restrict=teacher_restrict,
                           teacher_unavail=teacher_unavail, student_dist=student_dist,
                           slot_times=slot_times, global_dist=global_dist_rows)


def generate_schedule():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']
    max_lessons = cfg['max_lessons']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    c.execute('SELECT * FROM students')
    students = c.fetchall()
    c.execute('SELECT * FROM teacher_restrictions')
    restr_rows = c.fetchall()
    teacher_restrict = {}
    for r in restr_rows:
        teacher_restrict.setdefault(r['teacher_id'], set()).add(r['student_id'])
    c.execute('SELECT * FROM teacher_unavailability')
    unavail_rows = c.fetchall()
    teacher_unavail = {}
    for r in unavail_rows:
        for s in range(r['start_slot'], r['end_slot']+1):
            teacher_unavail.setdefault(r['teacher_id'], set()).add(s)
    c.execute('SELECT * FROM subject_distribution')
    dist_rows = c.fetchall()
    student_dist = {}
    for r in dist_rows:
        student_dist.setdefault(r['student_id'], {})[r['subject']] = (r['percent_min'], r['percent_max'])
    c.execute('SELECT * FROM subject_distribution_global')
    g_rows = c.fetchall()
    global_dist = {r['subject']: (r['percent_min'], r['percent_max']) for r in g_rows}

    # clear previous timetable
    c.execute('DELETE FROM timetable')

    teacher_schedule = {t['id']: [None]*slots for t in teachers}
    student_schedule = {s['id']: [None]*slots for s in students}

    # build lists of students per subject
    subject_students = {}
    for s in students:
        for subj in json.loads(s['subjects']):
            subject_students.setdefault(subj, []).append(s['id'])

    # count lessons per student
    lesson_count = {s['id']: 0 for s in students}
    subject_count = {s['id']: {subj: 0 for subj in json.loads(s['subjects'])} for s in students}
    prev_subject = {s['id']: None for s in students}

    max_per_subject = {}
    for s in students:
        dist = global_dist.copy()
        dist.update(student_dist.get(s['id'], {}))
        max_per_subject[s['id']] = {}
        for subj in json.loads(s['subjects']):
            perc_min, perc_max = dist.get(subj, (0, 100))
            max_per_subject[s['id']][subj] = int(perc_max * max_lessons / 100)

    for slot in range(slots):
        for t in teachers:
            subj = t['subject']
            candidates = subject_students.get(subj, [])
            chosen = None
            for sid in candidates:
                if student_schedule[sid][slot] is not None:
                    continue
                if lesson_count[sid] >= max_lessons:
                    continue
                if sid in teacher_restrict.get(t['id'], set()):
                    continue
                if slot in teacher_unavail.get(t['id'], set()):
                    continue
                if subject_count[sid].get(subj, 0) >= max_per_subject[sid].get(subj, max_lessons):
                    continue
                if prev_subject[sid] == subj:
                    continue
                chosen = sid
                break
            if chosen is not None:
                teacher_schedule[t['id']][slot] = chosen
                student_schedule[chosen][slot] = t['id']
                lesson_count[chosen] += 1
                subject_count[chosen][subj] = subject_count[chosen].get(subj, 0) + 1
                prev_subject[chosen] = subj
                c.execute('INSERT INTO timetable (student_id, teacher_id, subject, slot) VALUES (?, ?, ?, ?)',
                          (chosen, t['id'], subj, slot))

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
    c.execute('SELECT * FROM slot_times ORDER BY slot')
    slot_rows = c.fetchall()
    slot_times = {row['slot']: row['start_time'] for row in slot_rows}
    conn.close()

    # build grid [slot][teacher] => student
    grid = {slot: {te['id']: None for te in teachers} for slot in range(slots)}
    for r in rows:
        # get teacher id by name
        tid = next(te['id'] for te in teachers if te['name'] == r['teacher'])
        grid[r['slot']][tid] = f"{r['student']} ({r['subject']})"

    return render_template('timetable.html', slots=range(slots), teachers=teachers, grid=grid, slot_times=slot_times)


@app.route('/delete_student/<int:student_id>')
def delete_student(student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM students WHERE id=?', (student_id,))
    c.execute('DELETE FROM subject_distribution WHERE student_id=?', (student_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))


@app.route('/delete_teacher/<int:teacher_id>')
def delete_teacher(teacher_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM teachers WHERE id=?', (teacher_id,))
    c.execute('DELETE FROM teacher_restrictions WHERE teacher_id=?', (teacher_id,))
    c.execute('DELETE FROM teacher_unavailability WHERE teacher_id=?', (teacher_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))


@app.route('/delete_global_dist/<int:dist_id>')
def delete_global_dist(dist_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM subject_distribution_global WHERE id=?', (dist_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('config'))


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
