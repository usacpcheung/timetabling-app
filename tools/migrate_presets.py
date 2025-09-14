import os
import sys
import sqlite3
import json

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from app import DB_PATH, migrate_preset, CURRENT_PRESET_VERSION


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT id, data, version FROM config_presets')
    rows = c.fetchall()
    updated = 0
    for row in rows:
        preset = {'version': row['version'], 'data': json.loads(row['data'])}
        new = migrate_preset(preset)
        if new['data'] != preset['data'] or row['version'] != CURRENT_PRESET_VERSION:
            c.execute(
                'UPDATE config_presets SET data=?, version=? WHERE id=?',
                (json.dumps(new['data']), CURRENT_PRESET_VERSION, row['id']),
            )
            updated += 1
    conn.commit()
    conn.close()
    print(f"Migrated {updated} preset(s).")


if __name__ == '__main__':
    migrate()
