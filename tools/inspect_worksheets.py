import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from app import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print('DB:', DB_PATH)
total = c.execute('SELECT COUNT(*) AS c FROM worksheets').fetchone()['c']
print('Total worksheets rows:', total)
dups = c.execute('''
    SELECT student_id, subject, date, COUNT(*) AS cnt
    FROM worksheets
    GROUP BY student_id, subject, date
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC
''').fetchall()
print('Duplicate tuples after cleanup:', len(dups))
for r in dups[:10]:
    print(dict(r))

conn.close()
