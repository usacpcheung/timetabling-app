# Timetabling Optimization App

A local-first, browser-based school timetabling application built with **Python (Flask)** and **SQLite**. Users can configure teachers, students and scheduling parameters then generate an optimized timetable for a single day.

---

## 💡 Key Features

- Configure teachers, students, subjects and groups through a web form
- Mark teachers unavailable in specific slots or assign fixed lessons, with batch selection for multiple teachers and slots
- Specify teachers that individual students should avoid
- Generate optimized timetables using OR-Tools CP-SAT
- Record and view attendance history for each student and subject
- Bias scheduling based on past attendance percentages
- Balance teacher workloads and limit total lessons
- Manage groups for joint lessons with adjustable weighting
- Delete or clear saved timetables through the interface

## 📦 Project Structure

```
app.py                          # Flask routes and database setup
cp_sat_timetable.py             # OR-Tools model creation and solving helpers
data/                           # Writable directory holding the SQLite database
CODE_GUIDE.txt                  # Walkthrough of the code for beginners
static/                         # Front-end scripts and styles
    attendance.js               # Data table initialisation on attendance page
    config.js                   # Dynamic form behaviour for configuration
    main.js                     # Confirmation prompts and timetable checks
    ui.js                       # Initialises Flowbite UI components
    style.css                   # Basic styling shared by all pages
    tailwind-input.css          # Source file compiled by Tailwind CLI
    tailwind.css                # Generated Tailwind + Flowbite utilities
    vendor/flowbite.min.js      # Flowbite components (local copy)
    vendor/flowbite-datepicker.min.js  # Flowbite datepicker (local copy)
    vendor/simple-datatables.min.js    # Simple-DataTables (local copy)
    vendor/simple-datatables.css       # Styling for attendance tables
    flowbite-accordion-selectinput-fix.css  # Workaround for a Flowbite bug
templates/                      # HTML templates rendered by Flask
    index.html
    config.html
    timetable.html
    attendance.html
    manage_timetables.html
tests/                          # Unit tests demonstrating key behaviours
    test_block_rules.py         # Verifies teacher blocking logic
```

## ▶️ Running

### Dependencies

Install Flask and OR-Tools before running the application:

```bash
pip install Flask ortools
```

Build the Tailwind CSS bundle (once after cloning, and whenever you change
`static/tailwind-input.css` or the HTML templates):

```bash
npm install
npm run build:css
```

Then start the development server:

```bash
python app.py
```

The app will be available at `http://localhost:5000`.

The SQLite database is stored in `data/timetable.db` relative to the project
root. When deploying on Windows for all users, ensure the `data` directory is
writable so the application can create and update the database.

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
prioritize consecutive placement over other constraints. Another checkbox lets
you allow or forbid a student taking the same subject from different teachers.
When this is disabled the repeat option must also remain off, effectively
limiting each student/subject pair to a single lesson per timetable.
Individual students can further restrict repeated lessons to specific subjects
via their advanced settings. Leaving this selection empty allows repeats for
any of the student's subjects.

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
You can also set a separate **Well-attended weight**. This weight applies once a
student's attendance percentage meets the threshold. Try **0** if you want the
solver to freely drop these subjects after the target is met. Small values such
as `0.1` may not noticeably speed up solving—the solver can still take a few
minutes. When **Use attendance priority** and **Require all subjects?** are both enabled, solving can take significantly longer regardless of the well-attended weight. The configuration page shows a warning when these options are enabled together so you can adjust the settings.

When using group lessons you can adjust **Group weight** to bias the solver
toward scheduling them. This multiplier boosts the objective weight of any
variable whose ``student_id`` represents a group, making joint lessons more
appealing relative to individual ones. A value around **2** is a good
starting point and roughly doubles the attractiveness of group lessons, while
lower values reduce their priority. Setting the weight to **0** effectively
suppresses group lessons entirely.

You can also block specific student/teacher pairings. The configuration form
lets you tick the teachers a student should avoid. The app checks each block
to make sure another teacher remains available for any required group lessons
before saving.

Checking **Balance teacher load** instructs the solver to even out lesson counts
between teachers when possible. The **Balance weight** controls how strongly this
goal influences the objective. Higher values place more emphasis on fairness at
the potential expense of maximizing the total scheduled lessons.

A **Balance weight** around **5** offers decent load balancing without greatly
reducing the number of scheduled lessons. Increase it for stricter balancing at
the expense of total lessons.

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
* Students with fixed assignments cannot be deleted; remove those assignments first.
* Groups with fixed assignments cannot be deleted; remove those assignments first.
* Minimum lesson values cannot exceed maximum values for either global or per-teacher settings.
* Students cannot block a teacher if that teacher already has a fixed assignment with them or if the block would leave their group without a teacher for a subject.
* Groups must have at least one subject and one member. Each subject must be required by all members and a suitable teacher must remain available after considering block rules.
* A warning appears when **Require all subjects?** and **Use attendance priority** are enabled together because solving can take much longer.

If any of these conditions fail the assignment is rejected and a message is
shown at the top of the page. Other sections rely on database constraints (for
example unique teacher and student names) to enforce correctness.
