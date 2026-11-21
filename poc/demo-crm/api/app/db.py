import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DSN = os.environ["DATABASE_URL"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, specialty TEXT NOT NULL,
  city TEXT NOT NULL, territory TEXT NOT NULL, owner TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
  rep TEXT NOT NULL, visit_date DATE NOT NULL,
  outcome TEXT, products TEXT, next_step TEXT
);
CREATE TABLE IF NOT EXISTS notes (
  id SERIAL PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
  text TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('draft', 'final')),
  created_by TEXT NOT NULL, via_agent TEXT, correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reminders (
  id SERIAL PRIMARY KEY, visit_id TEXT NOT NULL REFERENCES visits(id),
  rep TEXT NOT NULL, text TEXT NOT NULL,
  created_by TEXT NOT NULL, via_agent TEXT, correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


@contextmanager
def conn():
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        yield c
