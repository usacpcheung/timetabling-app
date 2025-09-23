# Timetabling App – Agent Guide

## Scope
These instructions apply to the entire repository.

## Code Overview
- `app.py` is the main Flask application; it owns the routes, database helpers, preset management, and scheduling workflow.
- `cp_sat_timetable.py` builds and solves the OR-Tools CP-SAT model that the web app invokes.
- `templates/` holds the Jinja templates rendered by the routes, and `static/` contains the client-side JavaScript helpers used on those pages.
- `tests/` contains the pytest suite; add new tests alongside existing modules when possible.
- `tools/` stores maintenance scripts—treat them as references for data migrations and housekeeping.

## Python Guidelines
- Prefer keeping related logic in `app.py` until it clearly belongs in a separate module; mirror the existing structure and naming conventions.
- When touching the solver, maintain the separation where `cp_sat_timetable.py` handles model construction and solution reporting.
- Preserve docstrings and inline comments that explain validation rules or solver assumptions.

## Front-end Guidelines
- Keep shared behaviour in existing assets under `static/` rather than creating duplicates.
- Match the structure and component usage in the current templates when extending UI features.

## Testing
- Run `pytest` from the repository root before submitting changes.
- Include new tests when fixing bugs or adding features.

## Pull Requests
- Provide a concise summary of the change.
- List the tests you ran (including commands and environments).
- Mention any follow-up work or known limitations.
