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
CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
  method TEXT NOT NULL, path TEXT NOT NULL, status INT NOT NULL, outcome TEXT NOT NULL, detail TEXT,
  actor_type TEXT NOT NULL, person TEXT, person_sub TEXT, agent TEXT, source TEXT,
  correlation_id TEXT, object TEXT,
  token_header JSONB, token_claims JSONB, token_verified BOOLEAN NOT NULL, token_error TEXT
);
-- append-only: the API never updates or deletes audit rows
CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS
  $$ BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$;
DROP TRIGGER IF EXISTS audit_no_change ON audit_events;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_append_only();
"""


@contextmanager
def conn():
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        yield c
