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


def test_deleted_subject_not_recreated(tmp_path):
    import app

    conn = setup_db(tmp_path)
    c = conn.cursor()
    # ensure clean state
    c.execute('DELETE FROM subjects')
    c.execute('DELETE FROM subjects_archive')
    c.execute('DELETE FROM teachers')
    conn.commit()

    # create subject and teacher referencing it
    c.execute("INSERT INTO subjects (id, name) VALUES (1, 'Sub')")
    c.execute("INSERT INTO teachers (id, name, subjects) VALUES (1, 'T', '[1]')")
    conn.commit()

    # delete subject and close connection
    c.execute('DELETE FROM subjects WHERE id=1')
    conn.commit()
    conn.close()

    # re-run init to trigger cleanup
    app.init_db()

    conn = sqlite3.connect(app.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # subject should not be recreated with numeric name
    assert c.execute('SELECT COUNT(*) FROM subjects').fetchone()[0] == 0
    # teacher's subject list should be cleared
    assert c.execute('SELECT subjects FROM teachers WHERE id=1').fetchone()['subjects'] == '[]'
    conn.close()

