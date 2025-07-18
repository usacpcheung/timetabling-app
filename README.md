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

Install Flask and OR-Tools if needed and start the development server:

```bash
pip install Flask ortools
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
