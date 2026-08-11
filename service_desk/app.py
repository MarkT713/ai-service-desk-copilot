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

from .copilot import ARTICLES, analyze_ticket, detect_duplicates, redact_sensitive_text
from .cost_efficiency import load_verified_report
from .troubleshooting import build_troubleshooting_plan

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


class TroubleshootingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern="^(confirmed|not_found|inconclusive)$")
    observation: str = Field(min_length=3, max_length=1000)
    technician: str = Field(min_length=2, max_length=80)


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    restored: bool
    evidence: str = Field(min_length=3, max_length=1000)
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
CREATE TABLE IF NOT EXISTS troubleshooting_sessions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL, mode TEXT NOT NULL,
 status TEXT NOT NULL, current_step INTEGER NOT NULL DEFAULT 1, hypothesis TEXT NOT NULL,
 confidence TEXT NOT NULL, stop_condition TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS troubleshooting_steps (
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, ordinal INTEGER NOT NULL,
 instruction TEXT NOT NULL, purpose TEXT NOT NULL, expected_evidence TEXT NOT NULL,
 citation_id TEXT, status TEXT NOT NULL DEFAULT 'pending', outcome TEXT,
 observation TEXT, technician TEXT, completed_at TEXT,
 UNIQUE(session_id, ordinal)
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
    app = FastAPI(title="AI Service Desk Copilot", version="0.3.0")
    try:
        verified_cost_report = load_verified_report()
        cost_evidence_status = "verified"
    except (OSError, ValueError, json.JSONDecodeError):
        verified_cost_report = None
        cost_evidence_status = "unavailable"

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

    def human_actor(name: str):
        if name.lower() in {"ai", "ai copilot", "copilot", "system"}:
            raise HTTPException(
                403, "AI/system identities cannot record or approve troubleshooting"
            )

    def troubleshooting_workspace(conn: sqlite3.Connection, session_id: int) -> dict:
        session = conn.execute(
            "SELECT * FROM troubleshooting_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Troubleshooting session not found")
        data = dict(session)
        steps = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM troubleshooting_steps WHERE session_id=? ORDER BY ordinal",
                (session_id,),
            )
        ]
        completed = sum(step["status"] == "completed" for step in steps)
        data["steps"] = steps
        data["progress_label"] = f"{completed} of {len(steps)} evidence steps completed"
        data["next_step"] = next(
            (step for step in steps if step["status"] == "pending"), None
        )
        data["escalation_package"] = {
            "ticket_id": data["ticket_id"],
            "hypothesis": data["hypothesis"],
            "evidence": [
                {
                    "step": step["ordinal"],
                    "outcome": step["outcome"],
                    "observation": step["observation"],
                }
                for step in steps
                if step["status"] == "completed"
            ],
            "missing_evidence": [
                step["expected_evidence"]
                for step in steps
                if step["status"] == "pending"
            ],
            "mode": data["mode"],
        }
        return data

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
        return {
            "status": "ok",
            "mode": "synthetic-demo",
            "human_approval_required": True,
            "cost_benchmark": "deterministic-replay-v1",
            "cost_evidence_status": cost_evidence_status,
        }

    @app.get("/api/benchmarks/cost")
    def cost_benchmark():
        if verified_cost_report is None:
            raise HTTPException(503, "Checked-in cost benchmark evidence failed verification")
        return verified_cost_report

    @app.post("/api/demo/reset")
    def reset_demo():
        with db() as conn:
            conn.execute("DELETE FROM troubleshooting_steps")
            conn.execute("DELETE FROM troubleshooting_sessions")
            conn.execute("DELETE FROM audit")
            conn.execute("DELETE FROM tickets")
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('tickets','audit','troubleshooting_sessions','troubleshooting_steps')"
            )
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
        human_actor(body.technician)
        with db() as conn:
            get_ticket(conn, ticket_id)
            conn.execute("UPDATE tickets SET status=? WHERE id=?", (body.status, ticket_id))
            audit(conn, ticket_id, "status_changed", body.technician, f"Status set to {body.status}")
            return get_ticket(conn, ticket_id)

    @app.post("/api/tickets/{ticket_id}/troubleshooting/start")
    def start_troubleshooting(ticket_id: int):
        with db() as conn:
            ticket = get_ticket(conn, ticket_id)
            if not ticket["analysis"]:
                raise HTTPException(409, "Analyze the ticket before starting troubleshooting")
            existing = conn.execute(
                "SELECT id FROM troubleshooting_sessions WHERE ticket_id=? ORDER BY id DESC LIMIT 1",
                (ticket_id,),
            ).fetchone()
            if existing:
                return troubleshooting_workspace(conn, existing["id"])

            plan = build_troubleshooting_plan(ticket["analysis"])
            now = _now().isoformat()
            cur = conn.execute(
                "INSERT INTO troubleshooting_sessions"
                "(ticket_id,mode,status,current_step,hypothesis,confidence,stop_condition,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    ticket_id,
                    plan["mode"],
                    "in_progress",
                    1,
                    plan["hypothesis"],
                    plan["confidence"],
                    plan["stop_condition"],
                    now,
                    now,
                ),
            )
            session_id = cur.lastrowid
            for ordinal, step in enumerate(plan["steps"], 1):
                conn.execute(
                    "INSERT INTO troubleshooting_steps"
                    "(session_id,ordinal,instruction,purpose,expected_evidence,citation_id) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        session_id,
                        ordinal,
                        step["instruction"],
                        step["purpose"],
                        step["expected_evidence"],
                        step["citation_id"],
                    ),
                )
            audit(
                conn,
                ticket_id,
                "troubleshooting_started",
                "Demo Analyst",
                f"Started {plan['mode']} evidence workflow; no action executed",
            )
            return troubleshooting_workspace(conn, session_id)

    @app.get("/api/tickets/{ticket_id}/troubleshooting")
    def ticket_troubleshooting(ticket_id: int):
        with db() as conn:
            get_ticket(conn, ticket_id)
            session = conn.execute(
                "SELECT id FROM troubleshooting_sessions WHERE ticket_id=? ORDER BY id DESC LIMIT 1",
                (ticket_id,),
            ).fetchone()
            return troubleshooting_workspace(conn, session["id"]) if session else None

    @app.post("/api/troubleshooting/{session_id}/steps/{ordinal}/result")
    def record_troubleshooting_result(
        session_id: int, ordinal: int, body: TroubleshootingResult
    ):
        human_actor(body.technician)
        with db() as conn:
            workspace = troubleshooting_workspace(conn, session_id)
            if workspace["status"] != "in_progress":
                raise HTTPException(409, "This troubleshooting session is not accepting evidence")
            if ordinal != workspace["current_step"]:
                raise HTTPException(409, "Complete the current evidence step first")
            step = conn.execute(
                "SELECT * FROM troubleshooting_steps WHERE session_id=? AND ordinal=?",
                (session_id, ordinal),
            ).fetchone()
            if not step:
                raise HTTPException(404, "Troubleshooting step not found")

            safe_observation, findings = redact_sensitive_text(body.observation)
            now = _now().isoformat()
            conn.execute(
                "UPDATE troubleshooting_steps SET status='completed',outcome=?,observation=?,"
                "technician=?,completed_at=? WHERE id=?",
                (body.outcome, safe_observation, body.technician, now, step["id"]),
            )
            total = len(workspace["steps"])
            if body.outcome == "confirmed":
                hypothesis = f"Evidence continues to support: {workspace['hypothesis']}"
            elif body.outcome == "not_found":
                hypothesis = "Current hypothesis weakened; review remaining evidence or escalate."
            else:
                hypothesis = "Evidence remains inconclusive; continue the bounded workflow."
            if ordinal == total:
                status = (
                    "escalation_ready"
                    if workspace["mode"] == "escalation_only"
                    else "awaiting_verification"
                )
                next_step = total + 1
            else:
                status = "in_progress"
                next_step = ordinal + 1
            conn.execute(
                "UPDATE troubleshooting_sessions SET status=?,current_step=?,hypothesis=?,"
                "updated_at=? WHERE id=?",
                (status, next_step, hypothesis, now, session_id),
            )
            detail = f"Step {ordinal}: {body.outcome}; no action executed"
            if findings:
                detail += "; sensitive pattern redacted"
            audit(
                conn,
                workspace["ticket_id"],
                "troubleshooting_evidence_recorded",
                body.technician,
                detail,
            )
            return troubleshooting_workspace(conn, session_id)

    @app.post("/api/troubleshooting/{session_id}/verify")
    def verify_troubleshooting(session_id: int, body: VerificationResult):
        human_actor(body.technician)
        with db() as conn:
            workspace = troubleshooting_workspace(conn, session_id)
            if workspace["mode"] != "guided" or workspace["status"] != "awaiting_verification":
                raise HTTPException(409, "Complete guided evidence steps before verification")
            safe_evidence, findings = redact_sensitive_text(body.evidence)
            status = "verified" if body.restored else "escalation_ready"
            conn.execute(
                "UPDATE troubleshooting_sessions SET status=?,updated_at=? WHERE id=?",
                (status, _now().isoformat(), session_id),
            )
            if body.restored:
                conn.execute(
                    "UPDATE tickets SET status='resolved' WHERE id=?",
                    (workspace["ticket_id"],),
                )
            detail = f"Service restored={body.restored}; evidence: {safe_evidence}"
            if findings:
                detail += "; sensitive pattern redacted"
            audit(
                conn,
                workspace["ticket_id"],
                "troubleshooting_verified" if body.restored else "troubleshooting_escalated",
                body.technician,
                detail,
            )
            return troubleshooting_workspace(conn, session_id)

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
