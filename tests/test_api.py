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


def test_guided_troubleshooting_records_evidence_and_advances(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    ticket = next(t for t in api.get("/api/tickets").json() if "DNS" in t["title"])
    api.post(f"/api/tickets/{ticket['id']}/analyze")

    started = api.post(f"/api/tickets/{ticket['id']}/troubleshooting/start")
    assert started.status_code == 200
    workspace = started.json()
    assert workspace["mode"] == "guided"
    assert workspace["status"] == "in_progress"
    assert workspace["current_step"] == 1
    assert workspace["steps"][0]["status"] == "pending"
    assert workspace["steps"][0]["citation_id"] == "KB-NET-009"

    repeated = api.post(f"/api/tickets/{ticket['id']}/troubleshooting/start").json()
    assert repeated["id"] == workspace["id"]

    result = api.post(
        f"/api/troubleshooting/{workspace['id']}/steps/1/result",
        json={
            "outcome": "confirmed",
            "observation": "Only one synthetic workstation is affected; gateway ping succeeds.",
            "technician": "Demo Analyst",
        },
    )
    assert result.status_code == 200
    updated = result.json()
    assert updated["current_step"] == 2
    assert updated["steps"][0]["status"] == "completed"
    assert updated["steps"][0]["outcome"] == "confirmed"
    assert "1 of" in updated["progress_label"]

    audit = api.get(f"/api/tickets/{ticket['id']}/audit").json()
    assert any(item["action"] == "troubleshooting_evidence_recorded" for item in audit)


def test_security_workspace_is_escalation_only_and_preserves_evidence(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    ticket = next(t for t in api.get("/api/tickets").json() if "PowerShell" in t["title"])
    api.post(f"/api/tickets/{ticket['id']}/analyze")
    workspace = api.post(f"/api/tickets/{ticket['id']}/troubleshooting/start").json()

    assert workspace["mode"] == "escalation_only"
    instructions = " ".join(step["instruction"].lower() for step in workspace["steps"])
    assert "preserve" in instructions or "capture" in instructions
    assert "decode the command" not in instructions
    assert workspace["stop_condition"]

    blocked = api.post(
        f"/api/troubleshooting/{workspace['id']}/steps/1/result",
        json={"outcome": "confirmed", "observation": "Alert captured", "technician": "AI Copilot"},
    )
    assert blocked.status_code == 403


def test_troubleshooting_requires_analysis(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    ticket = api.get("/api/tickets").json()[-1]
    response = api.post(f"/api/tickets/{ticket['id']}/troubleshooting/start")
    assert response.status_code == 409


def test_completed_guided_workflow_requires_human_verification(tmp_path):
    api = client(tmp_path)
    api.post("/api/demo/reset")
    ticket = next(t for t in api.get("/api/tickets").json() if "printer" in t["title"].lower())
    api.post(f"/api/tickets/{ticket['id']}/analyze")
    workspace = api.post(f"/api/tickets/{ticket['id']}/troubleshooting/start").json()

    for step in workspace["steps"]:
        workspace = api.post(
            f"/api/troubleshooting/{workspace['id']}/steps/{step['ordinal']}/result",
            json={
                "outcome": "confirmed",
                "observation": f"Synthetic evidence recorded for step {step['ordinal']}",
                "technician": "Demo Analyst",
            },
        ).json()

    assert workspace["status"] == "awaiting_verification"
    ticket_before = api.get(f"/api/tickets/{ticket['id']}").json()
    assert ticket_before["status"] != "resolved"

    verified = api.post(
        f"/api/troubleshooting/{workspace['id']}/verify",
        json={
            "restored": True,
            "evidence": "Synthetic print test completed successfully",
            "technician": "Demo Analyst",
        },
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert api.get(f"/api/tickets/{ticket['id']}").json()["status"] == "resolved"
