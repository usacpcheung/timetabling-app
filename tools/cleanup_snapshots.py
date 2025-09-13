import os
import sys
import json
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from app import DB_PATH


def cleanup():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Deduplicate rows by keeping the first row per date
    c.execute(
        """
        DELETE FROM timetable_snapshot
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM timetable_snapshot GROUP BY date
        )
        """
    )

    rows = c.execute("SELECT date, missing FROM timetable_snapshot").fetchall()
    dates_to_delete = []
    for row in rows:
        missing = row["missing"]
        if not missing:
            continue
        try:
            data = json.loads(missing)
        except json.JSONDecodeError:
            dates_to_delete.append(row["date"])
            continue
        outdated = False
        for subjects in data.values():
            for entry in subjects:
                if not isinstance(entry, dict) or "subject_id" not in entry:
                    outdated = True
                    break
            if outdated:
                break
        if outdated:
            dates_to_delete.append(row["date"])

    if dates_to_delete:
        c.executemany("DELETE FROM timetable_snapshot WHERE date = ?", [(d,) for d in dates_to_delete])

    conn.commit()
    print(f"Deduplicated and removed {len(dates_to_delete)} old snapshots")
    conn.close()


if __name__ == "__main__":
    cleanup()
