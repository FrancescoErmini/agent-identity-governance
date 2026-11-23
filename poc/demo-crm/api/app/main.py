import json
import os
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .audit import AuditMiddleware, mark
from .auth import caller, require_role
from .db import conn
from .seed import seed

app = FastAPI(title="demo-crm API", version="0.2.0")
app.add_middleware(AuditMiddleware)


@app.on_event("startup")
def _startup() -> None:
    seed()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(who: dict = Depends(caller)):
    return who


@app.get("/accounts")
def search_accounts(q: str = "", limit: int = 20, who: dict = Depends(caller)):
    require_role(who, "rep")
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM accounts WHERE territory = %s AND (name ILIKE %s OR city ILIKE %s) "
            "ORDER BY id LIMIT %s",
            (who["territory"], f"%{q}%", f"%{q}%", min(limit, 100)),
        ).fetchall()
    return {"territory": who["territory"], "accounts": rows}


def _own_account(c, account_id: str, who: dict) -> dict:
    acc = c.execute("SELECT * FROM accounts WHERE id = %s", (account_id,)).fetchone()
    if not acc or acc["territory"] != who["territory"]:
        raise HTTPException(404, "account not found in your territory")
    return acc


@app.get("/accounts/{account_id}")
def get_account(account_id: str, request: Request, who: dict = Depends(caller)):
    mark(request, f"account:{account_id}")
    require_role(who, "rep")
    with conn() as c:
        acc = _own_account(c, account_id, who)
        acc["visits"] = c.execute(
            "SELECT * FROM visits WHERE account_id = %s ORDER BY visit_date DESC LIMIT 10", (account_id,)
        ).fetchall()
    return acc


class NoteIn(BaseModel):
    account_id: str
    text: str = Field(min_length=1, max_length=4000)
    status: Literal["draft", "final"] = "draft"


@app.post("/notes", status_code=201)
def create_note(body: NoteIn, request: Request, who: dict = Depends(caller)):
    require_role(who, "rep")
    status = "draft" if who["agent"] else body.status  # agents never write final notes
    with conn() as c:
        _own_account(c, body.account_id, who)
        note = c.execute(
            "INSERT INTO notes (account_id, text, status, created_by, via_agent, correlation_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.account_id, body.text, status, who["user"], who["agent"], who["correlation_id"]),
        ).fetchone()
    mark(request, f"note:{note['id']} ({status})")
    return note


@app.get("/notes")
def list_notes(who: dict = Depends(caller)):
    require_role(who, "rep")
    with conn() as c:
        return c.execute(
            "SELECT * FROM notes WHERE created_by = %s ORDER BY created_at DESC LIMIT 50", (who["user"],)
        ).fetchall()


@app.get("/reports/team")
def team_report(who: dict = Depends(caller)):
    require_role(who, "area-manager")
    with conn() as c:
        return c.execute(
            "SELECT rep, count(*) AS visits, count(*) FILTER (WHERE outcome IS NULL) AS incomplete "
            "FROM visits GROUP BY rep ORDER BY rep"
        ).fetchall()


@app.post("/notes/{note_id}/confirm")
def confirm_note(note_id: int, request: Request, who: dict = Depends(caller)):
    mark(request, f"note:{note_id}")
    require_role(who, "rep")
    if who["agent"]:
        raise HTTPException(403, "only the rep confirms a note, never an agent")
    with conn() as c:
        note = c.execute("UPDATE notes SET status = 'final' WHERE id = %s AND created_by = %s RETURNING *",
                         (note_id, who["user"])).fetchone()
    if not note:
        raise HTTPException(404, "note not found")
    return note


# --- autonomous data-quality agent ------------------------------------------------------------
@app.get("/dq/incomplete-visits")
def incomplete_visits(limit: int = 20, who: dict = Depends(caller)):
    require_role(who, "dq-agent")
    with conn() as c:
        return c.execute(
            "SELECT v.*, a.name AS account_name FROM visits v JOIN accounts a ON a.id = v.account_id "
            "WHERE (v.outcome IS NULL OR v.next_step IS NULL) "
            "AND NOT EXISTS (SELECT 1 FROM reminders r WHERE r.visit_id = v.id) "
            "ORDER BY v.visit_date DESC LIMIT %s", (min(limit, 100),)
        ).fetchall()


class ReminderIn(BaseModel):
    visit_id: str
    text: str = Field(min_length=1, max_length=1000)


@app.post("/reminders", status_code=201)
def create_reminder(body: ReminderIn, request: Request, who: dict = Depends(caller)):
    require_role(who, "dq-agent")
    with conn() as c:
        visit = c.execute("SELECT * FROM visits WHERE id = %s", (body.visit_id,)).fetchone()
        if not visit:
            raise HTTPException(404, "visit not found")
        reminder = c.execute(
            "INSERT INTO reminders (visit_id, rep, text, created_by, via_agent, correlation_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.visit_id, visit["rep"], body.text, who["user"], who["agent"], who["correlation_id"]),
        ).fetchone()
    mark(request, f"reminder:{reminder['id']} for {visit['rep']}")
    return reminder


@app.get("/reminders")
def list_reminders(who: dict = Depends(caller)):
    require_role(who, "rep")
    with conn() as c:
        return c.execute(
            "SELECT r.*, a.name AS account_name FROM reminders r JOIN visits v ON v.id = r.visit_id "
            "JOIN accounts a ON a.id = v.account_id WHERE r.rep = %s ORDER BY r.created_at DESC LIMIT 50",
            (who["user"],)).fetchall()


# --- audit ------------------------------------------------------------------------------------
@app.get("/audit")
def audit(actor_type: str | None = None, person: str | None = None, agent: str | None = None,
          correlation_id: str | None = None, outcome: str | None = None, writes_only: bool = False, limit: int = 100,
          who: dict = Depends(caller)):
    """Who did what, with the JWT that came in. For area managers, and only as themselves (no agent)."""
    require_role(who, "area-manager")
    if who["agent"]:
        raise HTTPException(403, "the audit trail is not open to agents")
    where, args = [], []
    for col, val in (("actor_type", actor_type), ("person", person), ("agent", agent),
                     ("correlation_id", correlation_id), ("outcome", outcome)):
        if val:
            where.append(f"{col} = %s")
            args.append(val)
    if writes_only:
        where.append("method <> 'GET'")
    sql = "SELECT * FROM audit_events" + (" WHERE " + " AND ".join(where) if where else "")
    with conn() as c:
        return c.execute(sql + " ORDER BY id DESC LIMIT %s", (*args, min(limit, 500))).fetchall()


@app.get("/audit/gateway")
def audit_gateway(correlation_id: str | None = None, limit: int = 50, who: dict = Depends(caller)):
    """The JWTs LiteLLM saw (decoded, written by its auth hook), to set beside the JWT that reached this API."""
    require_role(who, "area-manager")
    if who["agent"]:
        raise HTTPException(403, "the audit trail is not open to agents")
    try:
        with open(os.environ.get("GATEWAY_JWT_LOG", "/var/log/gateway/jwt.jsonl")) as f:
            lines = f.readlines()
    except OSError:
        return []
    rows = [json.loads(line) for line in lines if line.strip()]
    if correlation_id:
        rows = [r for r in rows if r.get("correlation_id") == correlation_id]
    return rows[::-1][:min(limit, 500)]
