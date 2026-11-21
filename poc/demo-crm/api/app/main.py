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
