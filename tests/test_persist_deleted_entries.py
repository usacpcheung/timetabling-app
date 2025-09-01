import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def setup_db(tmp_path):
    import app
    app.DB_PATH = str(tmp_path / 'test.db')
    app.init_db()
    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_deleted_records_not_recreated(tmp_path):
    import app
    conn = setup_db(tmp_path)
    conn.execute('DELETE FROM teachers')
    conn.execute('DELETE FROM students')
    conn.commit()
    conn.close()

    # simulate application restart
    app.init_db()

    conn = sqlite3.connect(app.DB_PATH)
    cur = conn.cursor()
    teacher_count = cur.execute('SELECT COUNT(*) FROM teachers').fetchone()[0]
    student_count = cur.execute('SELECT COUNT(*) FROM students').fetchone()[0]
    conn.close()

    assert teacher_count == 0
    assert student_count == 0
