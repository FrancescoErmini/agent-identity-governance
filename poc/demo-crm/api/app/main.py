from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .auth import caller, require_role
from .db import conn
from .seed import seed

app = FastAPI(title="demo-crm API", version="0.1.0")


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
def get_account(account_id: str, who: dict = Depends(caller)):
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
def create_note(body: NoteIn, who: dict = Depends(caller)):
    require_role(who, "rep")
    status = "draft" if who["agent"] else body.status  # agents never write final notes
    with conn() as c:
        _own_account(c, body.account_id, who)
        return c.execute(
            "INSERT INTO notes (account_id, text, status, created_by, via_agent, correlation_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.account_id, body.text, status, who["user"], who["agent"], who["correlation_id"]),
        ).fetchone()


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
def confirm_note(note_id: int, who: dict = Depends(caller)):
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
def create_reminder(body: ReminderIn, who: dict = Depends(caller)):
    require_role(who, "dq-agent")
    with conn() as c:
        visit = c.execute("SELECT * FROM visits WHERE id = %s", (body.visit_id,)).fetchone()
        if not visit:
            raise HTTPException(404, "visit not found")
        return c.execute(
            "INSERT INTO reminders (visit_id, rep, text, created_by, via_agent, correlation_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.visit_id, visit["rep"], body.text, who["user"], who["agent"], who["correlation_id"]),
        ).fetchone()


@app.get("/reminders")
def list_reminders(who: dict = Depends(caller)):
    require_role(who, "rep")
    with conn() as c:
        return c.execute(
            "SELECT r.*, a.name AS account_name FROM reminders r JOIN visits v ON v.id = r.visit_id "
            "JOIN accounts a ON a.id = v.account_id WHERE r.rep = %s ORDER BY r.created_at DESC LIMIT 50",
            (who["user"],)).fetchall()
