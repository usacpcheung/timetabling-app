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
    removed_dups = c.rowcount

    # Remove snapshots for dates that no longer have timetable entries
    c.execute(
        """
        DELETE FROM timetable_snapshot
        WHERE date NOT IN (SELECT DISTINCT date FROM timetable)
        """
    )
    removed_orphaned = c.rowcount

    rows = c.execute("SELECT date, missing, group_data FROM timetable_snapshot").fetchall()
    dates_to_delete = []
    for row in rows:
        missing = row["missing"]
        outdated = False
        if missing:
            try:
                data = json.loads(missing)
            except json.JSONDecodeError:
                outdated = True
            else:
                for subjects in data.values():
                    for entry in subjects:
                        if not isinstance(entry, dict) or "subject_id" not in entry:
                            outdated = True
                            break
                    if outdated:
                        break
        group_raw = row["group_data"]
        if not outdated:
            if not group_raw:
                outdated = True
            else:
                try:
                    group_info = json.loads(group_raw)
                except json.JSONDecodeError:
                    outdated = True
                else:
                    if not isinstance(group_info, dict):
                        outdated = True
                    else:
                        for info in group_info.values():
                            if not isinstance(info, dict):
                                outdated = True
                                break
                            members = info.get("members")
                            if not isinstance(members, list):
                                outdated = True
                                break
                            for member in members:
                                if not isinstance(member, dict) or "id" not in member:
                                    outdated = True
                                    break
                            if outdated:
                                break
        if outdated:
            dates_to_delete.append(row["date"])

    if dates_to_delete:
        c.executemany(
            "DELETE FROM timetable_snapshot WHERE date = ?",
            [(d,) for d in dates_to_delete],
        )

    removed_outdated = len(dates_to_delete)

    conn.commit()
    print(
        "Deduplicated {0} rows, removed {1} orphaned snapshots and {2} outdated snapshots".format(
            removed_dups, removed_orphaned, removed_outdated
        )
    )
    conn.close()


if __name__ == "__main__":
    cleanup()
