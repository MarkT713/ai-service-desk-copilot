from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .copilot import ARTICLES, analyze_ticket, detect_duplicates

ROOT = Path(__file__).resolve().parent.parent


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=4, max_length=120)
    description: str = Field(min_length=8, max_length=3000)
    requester: str = Field(min_length=2, max_length=80)


class ApplyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(pattern="^(accept|reject)$")
    technician: str = Field(min_length=2, max_length=80)
    note: str = Field(default="", max_length=500)


class TicketUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(new|in_progress|resolved|closed)$")
    technician: str = Field(min_length=2, max_length=80)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL,
 requester TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', priority TEXT NOT NULL DEFAULT 'P4',
 category TEXT NOT NULL DEFAULT 'unclassified', assignment_group TEXT NOT NULL DEFAULT 'Service Desk',
 created_at TEXT NOT NULL, sla_due_at TEXT NOT NULL, analysis_json TEXT
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL, action TEXT NOT NULL,
 actor TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

SEED_TICKETS = [
    ("Suspicious PowerShell activity", "Defender raised an alert after PowerShell launched an encoded command on one billing workstation.", "Avery Morgan"),
    ("Eaglesoft unavailable across front desk", "All 14 front desk workstations cannot reach Eaglesoft. Server is unreachable since 8:10 AM.", "Jordan Lee"),
    ("VPN authentication failure", "Remote employee cannot authenticate to VPN after an MFA reset; exact client error is 691.", "Taylor Brooks"),
    ("Account locked after password attempts", "Single user is locked out after too many password attempts.", "Casey Patel"),
    ("Reception printer offline", "Reception printer is unavailable after a DHCP change; queue still points to the old address.", "Morgan Chen"),
    ("DNS resolution failure", "One workstation can ping the gateway but cannot resolve host names through DNS.", "Riley Adams"),
    ("Endpoint low disk alert", "Monitoring reports 4 GB free on a Windows endpoint and update installation has stopped.", "Jamie Rivera"),
    ("Outlook profile will not open", "Outlook reports that the mail profile cannot be loaded, while webmail still works.", "Alex Kim"),
    ("Possible duplicate VPN report", "VPN login fails after MFA reset for a second remote employee.", "Drew Martin"),
    ("Shared drive access request", "New synthetic employee needs approved read-only access to the Finance training share.", "Sam Wilson"),
]


def _now() -> datetime:
    return datetime.now(UTC)


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["analysis"] = json.loads(data.pop("analysis_json")) if data.get("analysis_json") else None
    return data


def create_app(db_path: str | None = None) -> FastAPI:
    path = db_path or os.getenv("SERVICE_DESK_DB", str(ROOT / "service-desk.db"))
    app = FastAPI(title="AI Service Desk Copilot", version="0.1.0")

    @contextmanager
    def db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    with db() as conn:
        conn.executescript(SCHEMA)

    def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> dict:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Ticket not found")
        return _row(row)

    def audit(conn: sqlite3.Connection, ticket_id: int, action: str, actor: str, detail: str):
        conn.execute(
            "INSERT INTO audit(ticket_id, action, actor, detail, created_at) VALUES(?,?,?,?,?)",
            (ticket_id, action, actor, detail[:500], _now().isoformat()),
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
        return response

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "synthetic-demo", "human_approval_required": True}

    @app.post("/api/demo/reset")
    def reset_demo():
        with db() as conn:
            conn.execute("DELETE FROM audit")
            conn.execute("DELETE FROM tickets")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('tickets','audit')")
            created = _now()
            for title, description, requester in SEED_TICKETS:
                conn.execute(
                    "INSERT INTO tickets(title,description,requester,created_at,sla_due_at) VALUES(?,?,?,?,?)",
                    (title, description, requester, created.isoformat(), (created + timedelta(hours=24)).isoformat()),
                )
        return {"status": "reset", "ticket_count": len(SEED_TICKETS)}

    @app.post("/api/tickets")
    def create_ticket(body: TicketCreate):
        created = _now()
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO tickets(title,description,requester,created_at,sla_due_at) VALUES(?,?,?,?,?)",
                (body.title, body.description, body.requester, created.isoformat(), (created + timedelta(hours=24)).isoformat()),
            )
            ticket_id = cur.lastrowid
            audit(conn, ticket_id, "ticket_created", "system", "Synthetic ticket created")
            return get_ticket(conn, ticket_id)

    @app.get("/api/tickets")
    def list_tickets():
        with db() as conn:
            return [_row(row) for row in conn.execute("SELECT * FROM tickets ORDER BY id")]

    @app.get("/api/tickets/{ticket_id}")
    def ticket_detail(ticket_id: int):
        with db() as conn:
            ticket = get_ticket(conn, ticket_id)
            others = [dict(row) for row in conn.execute("SELECT id,title,description FROM tickets WHERE id != ?", (ticket_id,))]
            ticket["duplicates"] = detect_duplicates(f"{ticket['title']} {ticket['description']}", others)
            return ticket

    @app.post("/api/tickets/{ticket_id}/analyze")
    def analyze(ticket_id: int):
        with db() as conn:
            ticket = get_ticket(conn, ticket_id)
            result = analyze_ticket(f"{ticket['title']} {ticket['description']}").to_dict()
            others = [dict(row) for row in conn.execute("SELECT id,title,description FROM tickets WHERE id != ?", (ticket_id,))]
            result["duplicate_candidates"] = detect_duplicates(f"{ticket['title']} {ticket['description']}", others)
            conn.execute("UPDATE tickets SET analysis_json = ? WHERE id = ?", (json.dumps(result), ticket_id))
            audit(conn, ticket_id, "copilot_analyzed", "AI Copilot", "Suggestion generated; no ticket fields changed")
            return result

    @app.post("/api/tickets/{ticket_id}/apply")
    def apply(ticket_id: int, body: ApplyDecision):
        with db() as conn:
            ticket = get_ticket(conn, ticket_id)
            analysis = ticket["analysis"]
            if not analysis:
                raise HTTPException(409, "Analyze the ticket before reviewing suggestions")
            if body.decision == "reject":
                audit(conn, ticket_id, "copilot_suggestion_rejected", body.technician, body.note or "No reason supplied")
                return ticket
            status = "escalated" if analysis["requires_escalation"] else "in_progress"
            conn.execute(
                "UPDATE tickets SET category=?, priority=?, assignment_group=?, status=?, sla_due_at=? WHERE id=?",
                (analysis["category"], analysis["priority"], analysis["assignment_group"], status,
                 (_now() + timedelta(hours=analysis["sla_due_hours"])).isoformat(), ticket_id),
            )
            audit(conn, ticket_id, "copilot_suggestion_accepted", body.technician, f"Applied classification and routing. {body.note}".strip())
            return get_ticket(conn, ticket_id)

    @app.patch("/api/tickets/{ticket_id}")
    def update_ticket(ticket_id: int, body: TicketUpdate):
        if body.technician.lower() in {"ai", "ai copilot", "copilot", "system"}:
            raise HTTPException(403, "AI/system identities cannot resolve or close tickets")
        with db() as conn:
            get_ticket(conn, ticket_id)
            conn.execute("UPDATE tickets SET status=? WHERE id=?", (body.status, ticket_id))
            audit(conn, ticket_id, "status_changed", body.technician, f"Status set to {body.status}")
            return get_ticket(conn, ticket_id)

    @app.get("/api/tickets/{ticket_id}/audit")
    def ticket_audit(ticket_id: int):
        with db() as conn:
            get_ticket(conn, ticket_id)
            return [dict(row) for row in conn.execute("SELECT * FROM audit WHERE ticket_id=? ORDER BY id DESC", (ticket_id,))]

    @app.get("/api/knowledge")
    def knowledge():
        return [{"id": x.id, "title": x.title, "summary": x.summary, "steps": list(x.steps)} for x in ARTICLES.values()]

    @app.get("/api/metrics")
    def metrics():
        with db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            open_count = conn.execute("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved','closed')").fetchone()[0]
            p1 = conn.execute("SELECT COUNT(*) FROM tickets WHERE priority='P1'").fetchone()[0]
            risk = conn.execute("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved','closed') AND sla_due_at <= ?", ((_now()+timedelta(hours=2)).isoformat(),)).fetchone()[0]
            analyzed = conn.execute("SELECT COUNT(*) FROM tickets WHERE analysis_json IS NOT NULL").fetchone()[0]
            return {"ticket_count": total, "open_count": open_count, "p1_count": p1, "sla_at_risk_count": risk, "analyzed_count": analyzed}

    return app


app = create_app()
