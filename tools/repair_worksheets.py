import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)

import app

if __name__ == "__main__":
    app.init_db()
    print("init_db completed: worksheets deduped and unique index ensured.")
