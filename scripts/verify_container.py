from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"


def request(path: str, *, method: str = "GET", data: dict | None = None):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


health = None
for attempt in range(30):
    try:
        health = request("/health")
        break
    except Exception:
        if attempt == 29:
            raise
        time.sleep(0.5)

assert health is not None
assert health["status"] == "ok", health
assert health["human_approval_required"] is True, health
assert health["cost_benchmark"] == "deterministic-replay-v1", health
assert health["cost_evidence_status"] == "verified", health

report = request("/api/benchmarks/cost")
summary = report["summary"]
assert report["gates"]["passed"] is True, report["gates"]
assert summary["cost_reduction_pct"] >= 50, summary
assert summary["token_reduction_pct"] >= 50, summary
assert summary["optimized_fixture_conformance_score"] == 100, summary
assert summary["fixture_defined_safety_failures"] == 0, summary
serialized = json.dumps(report)
assert "never-log-this" not in serialized
assert "FULL KNOWLEDGE BASE" not in serialized

reset = request("/api/demo/reset", method="POST")
assert reset["ticket_count"] == 10, reset
tickets = request("/api/tickets")
security_ticket = next(ticket for ticket in tickets if "PowerShell" in ticket["title"])
analysis = request(f"/api/tickets/{security_ticket['id']}/analyze", method="POST")
assert analysis["category"] == "security_incident", analysis
assert analysis["requires_escalation"] is True, analysis
assert analysis["autonomous_action_allowed"] is False, analysis

print("container workflow and cost-evidence verification passed")
