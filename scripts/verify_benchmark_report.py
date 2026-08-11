from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "benchmarks" / "latest-report.json"
FIXTURE_PATH = ROOT / "benchmarks" / "cases.json"
ENGINE_PATH = ROOT / "service_desk" / "cost_efficiency.py"

report = json.loads(REPORT_PATH.read_text())
fixtures = json.loads(FIXTURE_PATH.read_text())
summary = report["summary"]
thresholds = report["gates"]["thresholds"]
cases = report["cases"]

assert report["schema_version"] == 2
assert (
    report["methodology"]["fixture_sha256"] == hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
)
assert (
    report["methodology"]["engine_sha256"] == hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()
)
assert len(cases) == len(fixtures) == summary["case_count"]
assert len({case["id"] for case in cases}) == len(cases)
assert len({fixture["id"] for fixture in fixtures}) == len(fixtures)
assert len({fixture["ticket"] for fixture in fixtures}) == summary["unique_ticket_text_count"]


def total(strategy: str, field: str) -> int:
    return sum(int(case[strategy][field]) for case in cases)


assert total("baseline", "model_calls") == summary["baseline_model_calls"]
assert total("optimized", "model_calls") == summary["optimized_model_calls"]
assert total("baseline", "total_tokens") == summary["baseline_total_tokens"]
assert total("optimized", "total_tokens") == summary["optimized_total_tokens"]

scores = {}
for strategy in ("baseline", "optimized"):
    checks = [check for case in cases for check in case[strategy]["conformance_checks"]]
    scores[strategy] = Decimal(100) * sum(check["passed"] for check in checks) / len(checks)
    expected_key = f"{strategy}_fixture_conformance_score"
    assert scores[strategy] == Decimal(str(summary[expected_key]))
    assert all(case[strategy]["conformance_passed"] for case in cases) == all(
        check["passed"] for check in checks
    )

safety_failures = sum(not case["safety_passed"] for case in cases)
assert safety_failures == summary["fixture_defined_safety_failures"]

baseline_tokens = Decimal(summary["baseline_total_tokens"])
optimized_tokens = Decimal(summary["optimized_total_tokens"])
modeled_token_reduction = Decimal(100) * (baseline_tokens - optimized_tokens) / baseline_tokens
assert round(modeled_token_reduction, 2) == Decimal(str(summary["token_reduction_pct"]))

baseline_cost = Decimal(str(summary["baseline_estimated_cost_usd"]))
optimized_cost = Decimal(str(summary["optimized_estimated_cost_usd"]))
modeled_cost_reduction = Decimal(100) * (baseline_cost - optimized_cost) / baseline_cost
assert round(modeled_cost_reduction, 2) == Decimal(str(summary["cost_reduction_pct"]))

independent_gate = (
    summary["cost_reduction_pct"] >= thresholds["minimum_cost_reduction_pct"]
    and summary["token_reduction_pct"] >= thresholds["minimum_token_reduction_pct"]
    and summary["baseline_fixture_conformance_score"]
    >= thresholds["minimum_baseline_fixture_conformance_score"]
    and summary["optimized_fixture_conformance_score"]
    >= thresholds["minimum_optimized_fixture_conformance_score"]
    and summary["fixture_conformance_delta_points"]
    >= -thresholds["maximum_conformance_drop_points"]
    and summary["unique_ticket_text_count"] >= thresholds["minimum_unique_ticket_text_count"]
    and safety_failures <= thresholds["maximum_fixture_defined_safety_failures"]
    and all(
        case["baseline"]["conformance_passed"] and case["optimized"]["conformance_passed"]
        for case in cases
    )
)
assert independent_gate == report["gates"]["passed"]
assert independent_gate is True
serialized = REPORT_PATH.read_text()
assert "never-log-this" not in serialized
assert "FULL KNOWLEDGE BASE" not in serialized

print("independent benchmark schema, aggregate, hash, and gate verification passed")
