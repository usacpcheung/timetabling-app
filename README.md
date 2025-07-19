# Timetabling Optimization App

A local-first, browser-based school timetabling application built with **Python (Flask)** and **SQLite**. Users can configure teachers, students and scheduling parameters then generate an optimized timetable for a single day.

---

## 💡 Key Features

- Configure teachers, students and lesson constraints
- Generate optimized, conflict-free timetables
- Simple web interface, no external database setup

## 📦 Project Structure

```
app.py
static/
    style.css
templates/
    index.html
    config.html
    timetable.html
```

## ▶️ Running

### Dependencies

Install Flask and OR-Tools before running the application:

```bash
pip install Flask ortools
```

Then start the development server:

```bash
python app.py
```

The app will be available at `http://localhost:5000`.

### Configuration

Open `/config` to edit teachers, students and general parameters. Subjects are
managed separately and can then be selected for each teacher or student. You
can also define unavailable slots for teachers and fix a particular
teacher/student/subject to a specific slot. Each teacher or student name must be
unique. The default database contains a simple setup with three teachers and
several students to get you started.

The general section also contains options controlling whether a student can
have multiple lessons with the same teacher and subject. When repeats are
enabled you can specify the maximum allowed number. Additional settings allow
consecutive repeats and optionally prefer them. These consecutive options are
ignored when repeat lessons are disabled. A weight value determines how strongly
consecutive repeats are favored in the optimization. For a noticeable effect
set the weight above **10**. Multiples of ten (e.g. `20`, `30`) increasingly
prioritize consecutive placement over other constraints.

A minimal test configuration could be:

```
Teachers
    Teacher A: Math, English
    Teacher B: Science
    Teacher C: History

Students
    Student 1: Math, English
    Student 2: Math, Science
    Student 3: History
```

With `slots_per_day=6` and `max_lessons=3` you should see a timetable after
clicking *Generate Timetable* from the home page.

### Validation Rules

The configuration page performs several checks when saving data:

* The subject chosen for a fixed assignment must be taught by the selected
  teacher **and** required by the student.
* A fixed assignment cannot use a slot marked as unavailable for that teacher.
* A teacher cannot be marked unavailable in a slot that already has a fixed assignment.
* Duplicate fixed assignments for the same teacher and slot are rejected.

If any of these conditions fail the assignment is rejected and a message is
shown at the top of the page. Other sections rely on database constraints (for
example unique teacher and student names) to enforce correctness.
