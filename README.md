# Timetabling Optimization App

A local-first, browser-based school timetabling application built with **Python (Flask)** and **SQLite**. Configure teachers, students, locations and constraints in the browser, then let OR-Tools CP-SAT build an optimized timetable for the selected day.

---

## 💡 Key Features

- Manage teachers, students, subjects, groups and locations from a single configuration page, including availability, fixed lessons and per-student restrictions. 【F:app.py†L1233-L2268】【F:app.py†L288-L356】
- Record nuanced student rules such as teacher blocks, repeat limits, slot unavailability and permitted locations. 【F:app.py†L1709-L1863】【F:app.py†L1968-L2033】
- Generate timetables with OR-Tools CP-SAT, balancing teacher workloads, honoring attendance priorities, respecting location limits and applying a configurable solver time limit. 【F:app.py†L2899-L3159】
- View timetables by teacher or location, highlight unmet subject requirements, and inspect lesson counts and group membership snapshots. 【F:app.py†L3238-L3412】
- Edit saved timetables, assign worksheets, or remove lessons while attendance logs stay in sync. 【F:app.py†L3591-L3790】
- Track attendance history for active and archived students with automatic updates from every timetable. 【F:app.py†L2899-L3099】【F:app.py†L3490-L3546】
- Save, load and migrate configuration presets or export/import full database backups directly from the UI. 【F:app.py†L636-L2268】【F:app.py†L4118-L4208】

## 📦 Project Structure

```
app.py                          # Flask routes, data access, presets and backup utilities
cp_sat_timetable.py             # OR-Tools model builder, diagnostics and solver helpers
data/                           # Writable directory containing the SQLite database and backups
CODE_GUIDE.txt                  # Walkthrough of the code for newcomers
static/                         # Front-end scripts and styles
    attendance.js               # Attendance tables and filtering helpers
    config.js                   # Dynamic behaviour for the configuration form
    main.js                     # Confirmation prompts and timetable edit helpers
    ui.js                       # Flowbite initialisation and component fixes
    flowbite-accordion-selectinput-fix.css  # Workaround for Flowbite styling bug
    dist/app.css                # Generated Tailwind + Flowbite stylesheet
    src/app.css                 # Tailwind source used when rebuilding CSS
    vendor/                     # Bundled Flowbite assets used by the templates
templates/                      # HTML templates rendered by Flask
    index.html                  # Landing page and timetable viewer
    config.html                 # Comprehensive configuration form
    timetable.html              # Read-only timetable grid
    edit_timetable.html         # Interactive timetable editor and worksheet tracker
    attendance.html             # Attendance summaries for active/deleted students
    manage_timetables.html      # Timetable list, preset actions and backup tools
tests/                          # Unit tests covering validation helpers
    test_block_rules.py
tools/                          # Maintenance scripts for snapshots, presets and worksheets
```

## ▶️ Running

### Python dependencies

Create a virtual environment and install the required packages:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use .venv\Scripts\activate
pip install -r requirements.txt
```

Start the development server:

```bash
python app.py
```

The app will be available at `http://localhost:5000`. The SQLite database is stored in `data/timetable.db` relative to the project root. When deploying on Windows for all users, ensure the `data` directory is writable so the application can create and update the database. 【F:app.py†L31-L73】

### Front-end tooling

Tailwind CSS **4.1.11** and Flowbite **3.1.2** are bundled locally. Install the Node dependencies once:

```bash
npm install
```

Rebuild the stylesheet after changing any template or Tailwind source file:

```bash
npm run build:css
```

For rapid development you can also run `npm run watch:css` to keep the CSS in sync while editing. The generated CSS is written to `static/dist/app.css` and served by Flask. 【F:package.json†L1-L15】

## ⚙️ Configuration Tour

Open `/config` to manage all scheduling inputs. Subjects are defined separately and then attached to teachers, students and groups. The default database contains a simple demo scenario to get you started. 【F:app.py†L1233-L2268】

### General settings

- **Slots per day**, **slot duration** and **slot start times** define the timetable grid. Start times must respect the duration so slots do not overlap. 【F:app.py†L1297-L1346】
- Set global minimum/maximum lessons for students and teachers. Per-teacher or per-student overrides can relax these defaults. 【F:app.py†L1347-L1438】【F:app.py†L1678-L1763】
- Toggle repeat lessons and control their behaviour (maximum count, whether consecutive slots are allowed or preferred, and the weight applied to consecutive runs). 【F:app.py†L1439-L1509】
- Decide if the solver must schedule every subject for every student (**Require all subjects?**). 【F:app.py†L1510-L1534】
- Attendance prioritisation boosts subjects that fall below a configurable attendance percentage and applies a separate weight once the target is met. Combine with **Well-attended weight** for nuanced control. 【F:app.py†L1535-L1568】
- **Group weight** biases joint lessons, **Balance teacher load** minimises workload imbalance, and **Solver time limit** caps CP-SAT runtime in seconds. 【F:app.py†L1569-L1599】【F:app.py†L1420-L1445】
- Allow or forbid a student taking a subject with multiple teachers globally or per student. 【F:app.py†L1500-L1518】【F:app.py†L1661-L1706】

### Teachers and availability

- Assign subjects, personal lesson limits and mark unavailable slots. The form prevents removing availability needed to satisfy minimum lessons or fixed assignments. 【F:app.py†L1600-L1759】【F:app.py†L2034-L2105】
- Fixed assignments reserve a teacher/student (or group) for a specific slot and subject. Validation ensures the teacher teaches the subject, the student/group requires it and the slot is available. 【F:app.py†L2106-L2268】

### Students and groups

- Maintain active students with subject lists, lesson limits, repeat preferences and per-subject repeat allow-lists. 【F:app.py†L1661-L1763】
- Record student unavailability by slot, block specific teachers (while ensuring alternatives remain) and restrict allowable locations. 【F:app.py†L1764-L1863】【F:app.py†L1901-L2033】
- Groups aggregate students for joint lessons. Every subject must be required by each member and at least one unblocked teacher must teach it. Locations can be limited per group as well. 【F:app.py†L1864-L2009】

### Locations

Define teaching locations, restrict which ones students or groups may use, and select locations on fixed assignments so the solver respects capacity preferences. 【F:app.py†L1934-L2033】【F:app.py†L2106-L2268】

### Presets

Use the *Presets* modal to snapshot the current configuration, download previous versions or restore a preset later. Presets only include configuration tables so historical timetables and attendance remain untouched. 【F:app.py†L636-L2268】

## 🗓️ Managing Timetables

- Generate a timetable from the home page or `/generate`. Existing records for that date are cleared before saving the new solution and attendance entries. 【F:app.py†L2899-L3099】【F:app.py†L3433-L3488】
- Switch between teacher and location views when inspecting timetables. Missing subject summaries, lesson counts and group member snapshots help diagnose conflicts. 【F:app.py†L3238-L3412】【F:templates/index.html†L66-L116】
- `/edit_timetable/<date>` allows adding, editing or deleting individual lessons and assigning worksheets. Attendance logs and unmet-subject snapshots refresh automatically. 【F:app.py†L3591-L3819】
- `/manage_timetables` lists saved dates and backup archives. Delete selected timetables, clear everything, or download the solver progress snapshot. 【F:app.py†L3554-L3664】
- Create verified database backups or restore previous snapshots (including uploaded zips) without leaving the browser. Integrity checks run before replacing the live database. 【F:app.py†L4118-L4208】

## ✅ Validation Highlights

- Fixed assignments must use subjects taught by the chosen teacher and required by the student or group. Slots cannot clash with teacher unavailability or duplicate assignments. 【F:app.py†L2106-L2268】
- Students and groups cannot be deleted while referenced by fixed assignments. 【F:app.py†L1808-L1882】【F:app.py†L2239-L2258】
- Lesson limits must stay within the number of available slots for both teachers and students, including the impact of unavailability rules. 【F:app.py†L1347-L1394】【F:app.py†L2034-L2105】
- Blocks are rejected if they would leave a group without an eligible teacher. 【F:app.py†L1864-L1900】
- The UI warns when **Require all subjects?** is combined with **Use attendance priority** because solving can take longer under both constraints. 【F:app.py†L1510-L1568】

Errors are flashed at the top of the configuration page so the user can correct the input before changes are committed. Database-level constraints (for example unique teacher and student names) provide additional safety nets. 【F:app.py†L1233-L2268】
