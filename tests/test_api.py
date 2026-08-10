from fastapi.testclient import TestClient

from service_desk.app import create_app


def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "desk.db")))


def test_demo_seed_analysis_and_human_approval_boundary(tmp_path):
    api = client(tmp_path)
    assert api.post("/api/demo/reset").status_code == 200
    tickets = api.get("/api/tickets").json()
    assert len(tickets) >= 8

    security = next(t for t in tickets if "PowerShell" in t["title"])
    analysis = api.post(f"/api/tickets/{security['id']}/analyze").json()
    assert analysis["priority"] == "P1"
    assert analysis["requires_escalation"] is True

    current = api.get(f"/api/tickets/{security['id']}").json()
    assert current["status"] == "new"
    assert current["assignment_group"] == "Service Desk"

    applied = api.post(
        f"/api/tickets/{security['id']}/apply",
        json={"decision": "accept", "technician": "Demo Analyst"},
    )
    assert applied.status_code == 200
    assert applied.json()["assignment_group"] == "Security Operations"
    assert applied.json()["status"] == "escalated"

    audit = api.get(f"/api/tickets/{security['id']}/audit").json()
    assert any(item["action"] == "copilot_suggestion_accepted" for item in audit)


def test_copilot_cannot_close_ticket(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    ticket = api.get("/api/tickets").json()[0]
    api.post(f"/api/tickets/{ticket['id']}/analyze")
    response = api.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "closed", "technician": "AI Copilot"},
    )
    assert response.status_code == 403


def test_apply_requires_prior_analysis(tmp_path):
    api = client(tmp_path)
    created = api.post(
        "/api/tickets",
        json={"title": "Synthetic test", "description": "One user has an issue", "requester": "Demo User"},
    ).json()
    response = api.post(
        f"/api/tickets/{created['id']}/apply",
        json={"decision": "accept", "technician": "Demo Analyst"},
    )
    assert response.status_code == 409


def test_health_and_metrics_do_not_expose_ticket_text(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    assert api.get("/health").json()["status"] == "ok"
    metrics = api.get("/api/metrics").json()
    assert set(metrics) >= {"ticket_count", "open_count", "p1_count", "sla_at_risk_count"}
    assert "description" not in str(metrics).lower()
