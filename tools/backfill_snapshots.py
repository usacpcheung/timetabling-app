import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from app import DB_PATH, get_missing_and_counts


def backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    dates = [row['date'] for row in c.execute('SELECT DISTINCT date FROM timetable')]
    created = 0
    for d in dates:
        c.execute('SELECT 1 FROM timetable_snapshot WHERE date=?', (d,))
        if c.fetchone() is None:
            get_missing_and_counts(c, d, refresh=True)
            created += 1
    conn.commit()
    conn.close()
    print(f"Created {created} snapshot(s).")


if __name__ == '__main__':
    backfill()
