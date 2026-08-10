import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from service_desk.copilot import analyze_ticket  # noqa: E402

cases = json.loads((root / "evals/cases.json").read_text())
results = []

for case in cases:
    actual = analyze_ticket(case["text"]).to_dict()
    checks = {key: actual[key] == expected for key, expected in case["expect"].items()}
    results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks})

report = {
    "suite": "synthetic deterministic routing regression",
    "passed": sum(item["passed"] for item in results),
    "total": len(results),
    "release_gate": all(item["passed"] for item in results),
    "results": results,
}
(root / "evals/latest-report.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["release_gate"] else 1)
