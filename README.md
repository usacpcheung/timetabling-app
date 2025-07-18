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
