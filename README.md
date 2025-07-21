# Timetabling Optimization App

A local-first, browser-based school timetabling application built with **Python (Flask)** and **SQLite**. Users can configure teachers, students and scheduling parameters then generate an optimized timetable for a single day.

---

## 💡 Key Features

- Configure teachers, students and lesson constraints
- Generate optimized, conflict-free timetables
- Simple web interface, no external database setup
- Attendance report showing how often each student attended each subject. History
  is tied to the numeric `student_id`; deleting a student and re-adding one with
  the same name creates a new ID and past attendance is not merged.

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

Another option lets you disable the rule that every student must attend at
least one lesson for each of their subjects. When unchecked the solver may skip
some subjects if required to satisfy other constraints. Any omitted subjects are
listed on the timetable page.

Attendance history can also influence scheduling. When **Use attendance
priority** is checked each subject gets a *Min %* threshold. If a student's past
attendance percentage for a subject is below this value the solver boosts the
weight of scheduling that lesson. For group lessons the median attendance of all
members is compared against the threshold. The weight added is controlled by the
**Attendance weight** setting. A good starting weight is **10**, which makes

under-attended subjects roughly ten times more attractive than others. Increase
this value if you want the solver to focus even more on improving attendance.

When using group lessons you can adjust **Group weight** to bias the solver
toward scheduling them. This multiplier boosts the objective weight of any
variable whose ``student_id`` represents a group, making joint lessons more
appealing relative to individual ones. A value around **2** is a good
starting point and roughly doubles the attractiveness of group lessons.

Two numbers define the minimum and maximum lessons each teacher should teach.
Individual teachers can override these global limits. Leave the per-teacher
fields blank to use the global values.

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
* Minimum lesson values cannot exceed maximum values for either global or per-teacher settings.

If any of these conditions fail the assignment is rejected and a message is
shown at the top of the page. Other sections rely on database constraints (for
example unique teacher and student names) to enforce correctness.
