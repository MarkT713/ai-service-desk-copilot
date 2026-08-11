from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service_desk.app import create_app
from service_desk.cost_efficiency import (
    CostAwareWorkflow,
    PriceCard,
    _quality,
    load_verified_report,
    run_benchmark,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workflow():
    return CostAwareWorkflow()


def test_baseline_uses_one_large_full_context_call(workflow):
    result = workflow.run(
        "VPN fails after MFA with error 720 for one remote employee.",
        strategy="baseline",
        principal_scope="technician:general",
    )

    assert result.route == "large_full_context"
    assert result.cache_hit is False
    assert len(result.calls) == 1
    assert result.calls[0].model == "large-general-v1"
    assert result.calls[0].input_tokens > 0
    assert result.calls[0].output_tokens > 0
    assert "KB-SEC-001" in result.calls[0].prompt
    assert "KB-VPN-006" in result.calls[0].prompt


def test_security_ticket_is_stopped_by_deterministic_gate_without_model_call(workflow):
    result = workflow.run(
        "Defender alert reports encoded PowerShell on WS-44.",
        strategy="optimized",
        principal_scope="technician:general",
    )

    assert result.analysis.category == "security_incident"
    assert result.route == "deterministic_security_gate"
    assert result.analysis.requires_escalation is True
    assert result.calls == []
    assert result.estimated_cost_usd == 0


def test_routine_ticket_uses_small_model_and_less_context_than_baseline(workflow):
    text = "VPN fails after MFA with error 720 for one remote employee."
    baseline = workflow.run(text, strategy="baseline", principal_scope="technician:general")
    optimized = workflow.run(text, strategy="optimized", principal_scope="technician:general")

    assert optimized.route == "small_grounded_draft"
    assert len(optimized.calls) == 1
    assert optimized.calls[0].model == "small-draft-v1"
    assert optimized.input_tokens < baseline.input_tokens
    assert optimized.estimated_cost_usd < baseline.estimated_cost_usd
    assert [item["id"] for item in optimized.analysis.citations] == ["KB-VPN-006"]


def test_cache_key_includes_principal_scope_and_policy_versions(workflow):
    text = "Printer queue stopped after the DHCP address changed."
    first = workflow.run(text, strategy="optimized", principal_scope="technician:site-a")
    repeated = workflow.run(text, strategy="optimized", principal_scope="technician:site-a")
    other_scope = workflow.run(text, strategy="optimized", principal_scope="technician:site-b")

    assert first.cache_hit is False
    assert first.calls
    assert repeated.cache_hit is True
    assert repeated.calls == []
    assert repeated.model_output == first.model_output
    assert repeated.estimated_cost_usd == 0
    assert other_scope.cache_hit is False
    assert other_scope.calls


def test_price_card_cost_math_is_explicit_and_versioned():
    card = PriceCard(
        version="test-v1",
        large_input_per_million=10,
        large_output_per_million=30,
        small_input_per_million=0.3,
        small_output_per_million=1.2,
    )

    assert card.estimate("large-general-v1", 1_000, 200) == pytest.approx(0.016)
    assert card.estimate("small-draft-v1", 1_000, 200) == pytest.approx(0.00054)


def test_price_card_rejects_invalid_rates_and_token_counts():
    with pytest.raises(ValueError, match="finite and non-negative"):
        PriceCard(large_input_per_million=-1)
    with pytest.raises(ValueError, match="version"):
        PriceCard(version=" ")
    with pytest.raises(ValueError, match="Token counts"):
        PriceCard().estimate("large-general-v1", -1, 0)
    with pytest.raises(ValueError, match="baseline large-model rate"):
        PriceCard(
            large_input_per_million=0,
            large_output_per_million=0,
            small_input_per_million=0,
            small_output_per_million=0,
        )


def test_benchmark_models_cost_reduction_with_absolute_conformance_and_safety_gates():
    report = run_benchmark()

    assert report["methodology"]["execution"] == "deterministic replay; no provider API called"
    assert report["summary"]["case_count"] >= 10
    assert report["summary"]["unique_ticket_text_count"] == 10
    assert report["summary"]["baseline_fixture_conformance_score"] == 100.0
    assert report["summary"]["optimized_fixture_conformance_score"] == 100.0
    assert report["summary"]["fixture_conformance_delta_points"] == 0.0
    assert report["summary"]["optimized_cache_hit_rate_pct"] > 0
    assert 0 < report["summary"]["optimized_large_model_escalation_rate_pct"] < 100
    assert report["summary"]["latency"] == "not measured; no provider API called"
    assert report["summary"]["cost_reduction_pct"] >= 50.0
    assert report["summary"]["token_reduction_pct"] >= 50.0
    assert report["summary"]["fixture_defined_safety_failures"] == 0
    assert report["gates"]["passed"] is True
    assert all(case["baseline"]["conformance_passed"] for case in report["cases"])
    assert all(case["optimized"]["conformance_passed"] for case in report["cases"])


def test_modeled_and_cached_output_corruption_fails_conformance(workflow):
    expected = {
        "category": "remote_access",
        "priority": "P2",
        "assignment_group": "Network Operations",
        "citation_ids": ["KB-VPN-006"],
        "requires_escalation": False,
    }
    text = "VPN fails after MFA with error 720 for one remote employee."
    first = workflow.run(text, strategy="optimized", principal_scope="technician:general")
    corrupted = replace(
        first,
        model_output={"draft_response": "", "summary": "token: never-log-this"},
    )
    passed, checks = _quality(corrupted, expected)
    assert passed is False
    assert {check["name"] for check in checks if not check["passed"]} >= {
        "modeled_output_policy_alignment",
        "modeled_output_reviewability",
        "modeled_output_privacy",
    }

    workflow._cache[next(iter(workflow._cache))] = json.dumps(corrupted.model_output)
    cached = workflow.run(text, strategy="optimized", principal_scope="technician:general")
    cached_passed, _ = _quality(cached, expected)
    assert cached.cache_hit is True
    assert cached_passed is False


def test_cost_benchmark_api_serves_checked_in_evidence_without_raw_prompts(tmp_path):
    api = TestClient(create_app(str(tmp_path / "desk.db")))
    health = api.get("/health")
    response = api.get("/api/benchmarks/cost")

    assert health.status_code == 200
    assert health.json()["cost_evidence_status"] == "verified"
    assert response.status_code == 200
    report = response.json()
    assert report["gates"]["passed"] is True
    serialized = response.text
    assert "never-log-this" not in serialized
    assert "FULL KNOWLEDGE BASE" not in serialized


def test_security_only_and_empty_custom_fixture_suites_are_handled(tmp_path):
    security_path = tmp_path / "security.json"
    security_path.write_text(
        json.dumps(
            [
                {
                    "id": "security-only",
                    "ticket": "Defender reports encoded PowerShell activity.",
                    "principal_scope": "technician:general",
                    "security_gate_required": True,
                    "forbidden_markers": [],
                    "expected": {
                        "category": "security_incident",
                        "priority": "P1",
                        "assignment_group": "Security Operations",
                        "citation_ids": ["KB-SEC-001"],
                        "requires_escalation": True,
                    },
                }
            ]
        )
    )
    report = run_benchmark(security_path)
    assert report["summary"]["optimized_model_calls"] == 0
    assert report["summary"]["optimized_large_model_escalation_rate_pct"] == 0.0
    assert report["summary"]["optimized_cache_hit_rate_pct"] == 0.0

    empty_path = tmp_path / "empty.json"
    empty_path.write_text("[]")
    with pytest.raises(ValueError, match="non-empty JSON array"):
        run_benchmark(empty_path)


def test_absolute_conformance_gate_rejects_equally_wrong_strategies(tmp_path):
    cases = json.loads((ROOT / "benchmarks" / "cases.json").read_text())
    cases[0]["expected"]["priority"] = "P4"
    path = tmp_path / "wrong-expectation.json"
    path.write_text(json.dumps(cases))

    report = run_benchmark(path)
    assert report["summary"]["baseline_fixture_conformance_score"] < 100
    assert report["summary"]["optimized_fixture_conformance_score"] < 100
    assert report["gates"]["passed"] is False


def test_fixture_schema_rejects_duplicate_ids_and_missing_fields(tmp_path):
    cases = json.loads((ROOT / "benchmarks" / "cases.json").read_text())
    cases[1]["id"] = cases[0]["id"]
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(cases))
    with pytest.raises(ValueError, match="Duplicate benchmark case id"):
        run_benchmark(duplicate_path)

    del cases[1]["ticket"]
    cases[1]["id"] = "restored-unique-id"
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text(json.dumps(cases))
    with pytest.raises(ValueError, match="missing required fields"):
        run_benchmark(malformed_path)


def test_checked_in_report_integrity_rejects_tampering(tmp_path):
    report = json.loads((ROOT / "benchmarks" / "latest-report.json").read_text())
    report["summary"]["cost_reduction_pct"] = 99.99
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="integrity verification"):
        load_verified_report(tampered)
