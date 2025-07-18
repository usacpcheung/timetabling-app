from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import json
import os

from cp_sat_timetable import build_model, solve_and_print

app = Flask(__name__)
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
    c.execute('DROP TABLE IF EXISTS timetable')

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
        name TEXT UNIQUE,
        subjects TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        subjects TEXT
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
            ('Teacher A', json.dumps(['Math', 'English'])),
            ('Teacher B', json.dumps(['Science'])),
            ('Teacher C', json.dumps(['History'])),
        ]
        c.executemany('INSERT INTO teachers (name, subjects) VALUES (?, ?)', teachers)
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
        c.execute('UPDATE config SET slots_per_day=?, slot_duration=?, lesson_duration=?, min_lessons=?, max_lessons=? WHERE id=1',
                  (slots_per_day, slot_duration, lesson_duration, min_lessons, max_lessons))
        # update teachers
        teacher_ids = request.form.getlist('teacher_id')
        teacher_names = request.form.getlist('teacher_name')
        teacher_subjects = request.form.getlist('teacher_subjects')
        deletes = set(request.form.getlist('teacher_delete'))
        for tid, name, subj in zip(teacher_ids, teacher_names, teacher_subjects):
            if tid:
                if tid in deletes:
                    c.execute('DELETE FROM teachers WHERE id=?', (int(tid),))
                else:
                    subj_json = json.dumps([s.strip() for s in subj.split(',') if s.strip()])
                    c.execute('UPDATE teachers SET name=?, subjects=? WHERE id=?', (name, subj_json, int(tid)))
        new_tname = request.form.get('new_teacher_name')
        new_tsubj = request.form.get('new_teacher_subjects')
        if new_tname and new_tsubj:
            subj_json = json.dumps([s.strip() for s in new_tsubj.split(',') if s.strip()])
            c.execute('INSERT INTO teachers (name, subjects) VALUES (?, ?)', (new_tname, subj_json))
        # update students
        student_ids = request.form.getlist('student_id')
        student_names = request.form.getlist('student_name')
        student_subjects = request.form.getlist('student_subjects')
        deletes_s = set(request.form.getlist('student_delete'))
        for sid, name, subj in zip(student_ids, student_names, student_subjects):
            if sid:
                if sid in deletes_s:
                    c.execute('DELETE FROM students WHERE id=?', (int(sid),))
                else:
                    subj_json = json.dumps([s.strip() for s in subj.split(',') if s.strip()])
                    c.execute('UPDATE students SET name=?, subjects=? WHERE id=?', (name, subj_json, int(sid)))
        new_sname = request.form.get('new_student_name')
        new_ssubj = request.form.get('new_student_subjects')
        if new_sname and new_ssubj:
            subj_json = json.dumps([s.strip() for s in new_ssubj.split(',') if s.strip()])
            c.execute('INSERT INTO students (name, subjects) VALUES (?, ?)', (new_sname, subj_json))
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
    conn.close()
    return render_template('config.html', config=cfg, teachers=teachers, students=students, json=json)


def generate_schedule():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM config WHERE id=1')
    cfg = c.fetchone()
    slots = cfg['slots_per_day']
    min_lessons = cfg['min_lessons']
    max_lessons = cfg['max_lessons']

    c.execute('SELECT * FROM teachers')
    teachers = c.fetchall()
    c.execute('SELECT * FROM students')
    students = c.fetchall()

    # clear previous timetable
    c.execute('DELETE FROM timetable')

    # Build and solve CP-SAT model
    model, vars_ = build_model(students, teachers, slots, min_lessons, max_lessons)
    status, assignments = solve_and_print(model, vars_)

    # Insert solver results into DB
    if assignments:
        for sid, tid, subj, slot in assignments:
            c.execute(
                'INSERT INTO timetable (student_id, teacher_id, subject, slot) VALUES (?, ?, ?, ?)',
                (sid, tid, subj, slot)
            )

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
