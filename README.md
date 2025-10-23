# Timetabling Optimization App

A local-first, browser-based school timetabling application built with **Flask**, **SQLite** and a flexible solver layer that defaults to **PuLP/HiGHS** (with an optional Google **OR-Tools CP-SAT** backend). Manage teachers, students, groups, locations and solver preferences from a single interface, then generate and fine-tune optimized schedules without leaving the browser.

## Table of contents

- [Overview](#overview)
- [Key features](#key-features)
- [Project structure](#project-structure)
- [Quick start](#quick-start)
- [Architecture at a glance](#architecture-at-a-glance)
- [Data and persistence](#data-and-persistence)
- [Configuration workflow](#configuration-workflow)
  - [General settings](#general-settings)
  - [Teachers and availability](#teachers-and-availability)
  - [Students and groups](#students-and-groups)
  - [Locations](#locations)
  - [Presets](#presets)
- [Managing timetables](#managing-timetables)
- [Validation safeguards](#validation-safeguards)
- [Testing and maintenance](#testing-and-maintenance)
- [Troubleshooting tips](#troubleshooting-tips)
- [License](#license)
- [Third-party notices](#third-party-notices)
- [Redistribution obligations](#redistribution-obligations)

## Overview

The application focuses on a local, privacy-friendly workflow. All data lives in a writable `data/` directory beside the codebase, and the bundled SQLite database is created on first launch with a small demo scenario so you can immediately experiment with constraints and solver behaviour. The UI is built with Tailwind CSS and Flowbite components, while the solver logic lives behind a backend-neutral API that currently ships with PuLP/HiGHS by default and an optional Google OR-Tools CP-SAT implementation.

## Key features

- Configure teachers, students, subjects, groups and locations from a single configuration page, including availability, fixed lessons and per-student restrictions.
- Capture nuanced student rules such as teacher blocks, repeat limits, slot unavailability and permitted locations.
- Apply batch teacher and student actions to adjust subject assignments, lesson limits, availability, blocked slots, subject membership, teacher blocks and allowed locations across many records while preserving their existing settings.
- Generate timetables with a PuLP/HiGHS mixed-integer model by default, balancing teacher workloads, honoring attendance priorities, respecting location limits and applying a configurable solver time limit. Switch to the OR-Tools CP-SAT backend when you need its advanced constraint programming features.
- Switch between teacher and location views, highlight unmet subject requirements, and inspect lesson counts and group membership snapshots for each schedule.
- Edit saved timetables, assign worksheets, or remove lessons while attendance logs stay in sync.
- Track attendance history for active and archived students with automatic updates from every timetable.
- Snapshot and migrate configuration presets or export/import complete database backups directly from the UI.

## Project structure

```
app.py                          # Flask routes, data access, presets and backup utilities
cp_sat_timetable.py             # OR-Tools model builder, diagnostics and solver helpers (optional backend)
data/                           # Writable directory containing the SQLite database and backups
CODE_GUIDE.txt                  # Walkthrough of the code for newcomers
solver/                        # Backend-neutral solver API and concrete implementations
    api.py                     # Facade used by the web app to build/solve timetables
    pulp_backend.py            # Default PuLP/HiGHS MILP backend
    ortools_backend.py         # Optional Google OR-Tools CP-SAT backend
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

## Quick start

### Python environment

1. Ensure Python 3.10+ is installed.
2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use .venv\Scripts\activate
   ```

3. Install the required backend dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   This installs Flask along with the default PuLP/HiGHS solver stack. Install `ortools` separately if you plan to run the optional CP-SAT backend.

### Launch the development server

Start Flask in development mode:

```bash
python app.py
```

The app runs at `http://localhost:5000` by default. A SQLite database is stored at `data/timetable.db`; the folder must remain writable so the application can create, migrate and back up data. Windows users can double-click `run_app.bat` for a convenience launcher.

### Front-end assets

Tailwind CSS **4.1.11** and Flowbite **3.1.2** are bundled locally. Install Node dependencies once:

```bash
npm install
```

Rebuild the stylesheet after changing any template or Tailwind source file:

```bash
npm run build:css
```

During active development, run `npm run watch:css` to keep the generated CSS (`static/dist/app.css`) in sync while editing.

## Architecture at a glance

- `app.py` hosts the Flask application: route handlers, configuration forms, validation helpers, preset management and backup utilities live here.
- `solver/api.py` exposes a backend-neutral facade used by the app. It defaults to the PuLP/HiGHS mixed-integer formulation (`solver/pulp_backend.py`) while still supporting the legacy Google OR-Tools CP-SAT implementation (`solver/ortools_backend.py`).
- `cp_sat_timetable.py` retains the OR-Tools CP-SAT model construction helpers used by the optional backend.
- Templates under `templates/` render the UI, with supporting JavaScript housed in `static/` for dynamic forms, timetable manipulation and Flowbite tweaks.
- A lightweight test suite in `tests/` exercises critical validation logic used when configuring teachers, students and fixed assignments.

Refer to `CODE_GUIDE.txt` for a guided walkthrough of how these pieces interact.

## Data and persistence

- On the first run the app seeds the database with a demo timetable configuration: core subjects, three example teachers and nine students. Feel free to replace or extend these records once you are familiar with the workflow.
- Database schema migrations run automatically via `init_db()` whenever the application starts. Existing data is preserved, new columns are added when required, and subject references are normalised to integer identifiers.
- Presets store configuration-only snapshots. Full database backups (including timetables, worksheets and attendance logs) can be created, downloaded or restored from the *Manage Timetables* interface.
- The solver progress snapshot recorded in `timetable_snapshot` makes it easy to inspect missing subjects, lesson counts and per-location allocations for historic runs.

## Configuration workflow

Visit `/config` after launching the server to manage all scheduling inputs. The default data gives you a starting point for experimentation.

### General settings

- Configure **slots per day**, **slot duration** and **slot start times** to define the timetable grid. Times must respect the duration so slots do not overlap.
- Set global minimum and maximum lesson counts for students and teachers. Override values per person when needed.
- Control repeat behaviour: allow/disallow repeats, cap occurrences, choose whether consecutive slots are permitted or preferred, and tune the weight applied to consecutive runs.
- Decide whether the solver must place every required subject for every student and whether attendance-aware weighting should boost underscheduled subjects.
- Adjust additional solver weights such as group biasing, teacher load balancing and the solver time limit (seconds).
- Allow or forbid a student taking the same subject with multiple teachers globally or per student.

### Teachers and availability

- Assign subjects to each teacher, set optional min/max lesson limits and mark unavailable slots.
- Configure fixed assignments that reserve specific teacher/student (or group) combinations for a slot and subject. Validation prevents conflicts with availability or missing subject requirements.
- Use the batch teacher actions panel to apply shared subject updates, toggle availability and adjust lesson defaults for multiple teachers simultaneously.

### Students and groups

- Maintain active students, their required subjects, lesson limits and repeat preferences (including per-subject repeat allow-lists). Use the _Needs lessons?_ toggle to temporarily exclude a student from scheduling without deleting their data.
- Record student unavailability, block individual teachers (while ensuring viable alternatives remain) and restrict allowable locations.
- Group students for joint lessons. Each subject in the group must be taught by at least one unblocked teacher, and optional location limits can keep lessons in suitable rooms.
- Use the batch student actions panel to add or remove blocked slots, subjects, teacher blocks, allowed locations and toggle the _Needs lessons?_ status for multiple students at once.
- Batch changes merge with existing data for both teachers and students, ensuring only the selected fields are updated.

### Locations

Define teaching locations, optionally limit which ones students or groups may use, and attach locations to fixed assignments so the solver respects capacity or equipment preferences.

### Presets

Use the *Presets* modal to snapshot the current configuration, download previous versions or restore presets later. Presets include configuration tables only, leaving historical timetables and attendance untouched.

## Managing timetables

- Generate a timetable from the home page or `/generate`. Existing records for that date are cleared before saving the new solution and associated attendance entries.
- Switch between teacher and location views when inspecting timetables. Missing subject summaries, lesson counts and group membership snapshots help diagnose conflicts.
- Visit `/edit_timetable/<date>` to add, edit or delete lessons and assign worksheets; attendance logs and unmet-subject snapshots refresh automatically.
- `/manage_timetables` lists saved dates, solver snapshots and backup archives. Delete individual timetables, clear everything, or download solver progress snapshots when investigating issues.
- Create verified database backups or restore previous snapshots (including uploaded ZIP archives) without leaving the browser. Integrity checks run before replacing the live database.

## Validation safeguards

- Fixed assignments must use subjects taught by the chosen teacher and required by the student or group. Slots cannot clash with teacher unavailability or duplicate assignments.
- Students and groups cannot be deleted while referenced by fixed assignments, ensuring configurations stay consistent.
- Lesson limits must fit within the available slots for teachers and students, accounting for unavailability rules.
- Teacher blocks are rejected if they would leave a group without an eligible instructor.
- The UI warns when combining "Require all subjects" with attendance priority because solving can take longer under both constraints. Errors are flashed at the top of the configuration page and database-level constraints (for example unique teacher and student names) add extra safety nets.

## Testing and maintenance

- Run the automated tests from the project root:

  ```bash
  pytest
  ```

- Utility scripts in `tools/` assist with migrations and diagnostics, including repairing worksheets, backfilling timetable snapshots and migrating legacy presets. Each script contains usage instructions in its docstring.
- When adjusting CSS or templates remember to rebuild or watch the Tailwind assets as described above.

## Troubleshooting tips

- If the solver reports infeasibility, inspect the generated assumption diagnostics via the solver snapshot download, or temporarily relax constraints such as repeat limits or teacher blocks.
- Clearing the database from the *Manage Timetables* page will recreate the default demo dataset, which is useful during demos or when testing new solver strategies.
- Ensure the `data/` directory remains writable—permission issues are the most common cause of missing timetables or failed backups on shared machines.

## License

This project is released under the [MIT License](LICENSE).

## Third-party notices

The application bundles Flowbite JavaScript assets within `static/vendor/`. Their MIT license notices are stored in
`static/vendor/THIRD_PARTY_NOTICES.md` and must accompany any redistribution of those files.

## Redistribution obligations

When creating downstream distributions (for example compiled executables or Docker images), include:

- A copy of this project's [MIT License](LICENSE).
- The Flowbite license notices from `static/vendor/THIRD_PARTY_NOTICES.md` alongside the bundled assets.
- Google OR-Tools' Apache-2.0 license and attribution. The OR-Tools project publishes the license and NOTICE file in its
  repository—include their Apache-2.0 text and an acknowledgement such as “This product includes software developed by
  Google LLC (OR-Tools)” in your distribution's NOTICE section to meet the dependency's requirements.
