"""Vercel entry point for the hosted VaultLedger demo.

Vercel functions have a read-only filesystem except /tmp, so the demo keeps its
SQLite file there and fills it with sample data on first start. Visitors can add,
edit and delete freely; the data resets whenever the function instance recycles.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault('VAULTLEDGER_DB', '/tmp/vaultledger-demo.db')
os.environ.setdefault('VAULTLEDGER_DEMO', '1')

import db  # noqa: E402
db.init_db()
import demo_seed  # noqa: E402
demo_seed.seed()

from app import app  # noqa: E402,F401  (initialize_database() runs on import and seals the hash chain)
