from service_desk.copilot import analyze_ticket
from service_desk.troubleshooting import build_troubleshooting_plan


def test_routine_plan_is_cited_and_bounded():
    analysis = analyze_ticket("One workstation cannot resolve hostnames through DNS").to_dict()
    plan = build_troubleshooting_plan(analysis)
    assert plan["mode"] == "guided"
    assert 3 <= len(plan["steps"]) <= 5
    assert all(step["citation_id"] == "KB-NET-009" for step in plan["steps"])
    assert all(step["purpose"] and step["expected_evidence"] for step in plan["steps"])


def test_security_plan_collects_evidence_then_stops():
    analysis = analyze_ticket("Defender alert after suspicious PowerShell encoded command").to_dict()
    plan = build_troubleshooting_plan(analysis)
    text = " ".join(step["instruction"].lower() for step in plan["steps"])
    assert plan["mode"] == "escalation_only"
    stop = plan["stop_condition"].lower()
    assert "routine remediation" in stop and "escalate" in stop
    assert "preserve" in text or "capture" in text
    assert "delete" not in text
    assert "execute" not in text


def test_unsupported_plan_requests_evidence_without_fake_citation():
    analysis = analyze_ticket("Something unusual happened with no useful details").to_dict()
    plan = build_troubleshooting_plan(analysis)
    assert plan["confidence"] == "low"
    assert all(step["citation_id"] is None for step in plan["steps"])
    assert "manual triage" in " ".join(step["instruction"].lower() for step in plan["steps"])
