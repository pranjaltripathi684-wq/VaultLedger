import os
import sys
import sqlite3


def _resource_dir():
    """Folder holding bundled read-only files (schema.sql, templates, ...)."""
    # When frozen with PyInstaller, bundled data is extracted to sys._MEIPASS.
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))


def _data_dir():
    """Folder where the persistent database lives.

    For a PyInstaller build, __file__ points inside a temporary extraction
    folder that is wiped on exit, so the database must live next to the .exe.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _data_dir()
DATABASE = os.environ.get('VAULTLEDGER_DB', os.path.join(BASE_DIR, 'finance.db'))
SCHEMA_FILE = os.path.join(_resource_dir(), 'schema.sql')


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create any missing tables. Safe to run repeatedly (CREATE TABLE IF NOT EXISTS)."""
    with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
        schema = f.read()

    conn = get_db_connection()

    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
