from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import tiktoken

from .copilot import ARTICLES, CopilotAnalysis, analyze_ticket, redact_sensitive_text

ROOT = Path(__file__).resolve().parent.parent
TOKENIZER_NAME = "o200k_base"
POLICY_VERSION = "service-desk-policy-v2"
PROMPT_VERSION = "cost-aware-draft-v1"
OUTPUT_SCHEMA_VERSION = 1
AUTHORIZATION_POLICY_VERSION = "synthetic-no-auth-v1"


@dataclass(frozen=True)
class PriceCard:
    """Versioned illustrative rates used for comparable offline estimates."""

    version: str = "illustrative-usd-2026-08-v1"
    large_input_per_million: float = 10.0
    large_output_per_million: float = 30.0
    small_input_per_million: float = 0.3
    small_output_per_million: float = 1.2

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("Price-card version is required")
        for field_name in (
            "large_input_per_million",
            "large_output_per_million",
            "small_input_per_million",
            "small_output_per_million",
        ):
            value = getattr(self, field_name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")
        if self.large_input_per_million + self.large_output_per_million <= 0:
            raise ValueError("At least one baseline large-model rate must be positive")

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts must be non-negative")
        if model == "large-general-v1":
            input_rate = self.large_input_per_million
            output_rate = self.large_output_per_million
        elif model == "small-draft-v1":
            input_rate = self.small_input_per_million
            output_rate = self.small_output_per_million
        else:
            raise ValueError(f"Unknown benchmark model: {model}")
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@dataclass(frozen=True)
class CallTrace:
    model: str
    purpose: str
    prompt: str
    completion: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    def to_report(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "purpose": self.purpose,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 8),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest(),
            "completion_sha256": hashlib.sha256(self.completion.encode()).hexdigest(),
        }


@dataclass(frozen=True)
class WorkflowResult:
    analysis: CopilotAnalysis
    route: str
    calls: list[CallTrace]
    model_output: dict[str, Any] | None = None
    cache_hit: bool = False

    @property
    def input_tokens(self) -> int:
        return sum(call.input_tokens for call in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(call.output_tokens for call in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        return sum(call.estimated_cost_usd for call in self.calls)


class CostAwareWorkflow:
    """Offline replay of baseline and optimized service-desk execution paths."""

    def __init__(self, price_card: PriceCard | None = None):
        self.price_card = price_card or PriceCard()
        self._encoding = tiktoken.get_encoding(TOKENIZER_NAME)
        self._cache: dict[str, str] = {}

    def run(
        self,
        ticket_text: str,
        *,
        strategy: Literal["baseline", "optimized"],
        principal_scope: str,
    ) -> WorkflowResult:
        if not principal_scope.strip():
            raise ValueError("principal_scope is required for scoped caching")
        safe_text, _findings = redact_sensitive_text(ticket_text)
        analysis = analyze_ticket(safe_text)
        if strategy == "baseline":
            return self._baseline(safe_text, analysis)
        if strategy != "optimized":
            raise ValueError(f"Unknown strategy: {strategy}")
        return self._optimized(safe_text, analysis, principal_scope)

    def _baseline(self, safe_text: str, analysis: CopilotAnalysis) -> WorkflowResult:
        knowledge = "\n\n".join(
            f"{article.id} | {article.title}\n{article.summary}\n" + "\n".join(article.steps)
            for article in ARTICLES.values()
        )
        prompt = (
            "You are a service-desk agent. Classify, prioritize, route, retrieve evidence, "
            "and draft a response. Review the entire knowledge base.\n\n"
            f"TICKET\n{safe_text}\n\nFULL KNOWLEDGE BASE\n{knowledge}"
        )
        completion_payload = analysis.to_dict()
        completion_payload.pop("analyzed_at", None)
        completion = json.dumps(completion_payload, sort_keys=True, separators=(",", ":"))
        call = self._trace("large-general-v1", "full_workflow", prompt, completion)
        return WorkflowResult(
            analysis, "large_full_context", [call], model_output=completion_payload
        )

    def _optimized(
        self,
        safe_text: str,
        analysis: CopilotAnalysis,
        principal_scope: str,
    ) -> WorkflowResult:
        if analysis.category == "security_incident":
            return WorkflowResult(analysis, "deterministic_security_gate", [])

        if analysis.major_incident_candidate or analysis.category == "general_request":
            model = "large-general-v1"
            route = "large_exception_path"
        else:
            model = "small-draft-v1"
            route = "small_grounded_draft"

        evidence_fingerprint = []
        for citation in analysis.citations:
            article = ARTICLES[citation["id"]]
            article_payload = json.dumps(asdict(article), sort_keys=True, separators=(",", ":"))
            evidence_fingerprint.append(
                {
                    "id": citation["id"],
                    "version": citation["version"],
                    "content_sha256": hashlib.sha256(article_payload.encode()).hexdigest(),
                }
            )
        cache_payload = {
            "scope_label": principal_scope,
            "authorization_policy_version": AUTHORIZATION_POLICY_VERSION,
            "workflow_policy_version": POLICY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "model": model,
            "redacted_ticket": safe_text,
            "evidence": evidence_fingerprint,
        }
        cache_key = hashlib.sha256(
            json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if cache_key in self._cache:
            return WorkflowResult(
                analysis,
                "scope_keyed_replay_cache",
                [],
                model_output=json.loads(self._cache[cache_key]),
                cache_hit=True,
            )

        evidence = "No matching knowledge article; manual triage required."
        if analysis.citations:
            article = ARTICLES[analysis.citations[0]["id"]]
            evidence = f"{article.id} | {article.title}\n{article.summary}\n" + "\n".join(
                article.steps
            )
        prompt = (
            "Draft concise technician-reviewable language. Deterministic policy already set category, "
            "priority, assignment, and escalation; do not change those fields.\n\n"
            f"REDACTED TICKET\n{safe_text}\n\nAUTHORIZED MINIMUM EVIDENCE\n{evidence}"
        )
        completion_payload = {
            "draft_response": analysis.draft_response,
            "summary": analysis.summary,
        }
        completion = json.dumps(
            completion_payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        call = self._trace(model, "bounded_response_draft", prompt, completion)
        self._cache[cache_key] = completion
        return WorkflowResult(analysis, route, [call], model_output=completion_payload)

    def _trace(self, model: str, purpose: str, prompt: str, completion: str) -> CallTrace:
        input_tokens = len(self._encoding.encode(prompt))
        output_tokens = len(self._encoding.encode(completion))
        return CallTrace(
            model=model,
            purpose=purpose,
            prompt=prompt,
            completion=completion,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=self.price_card.estimate(model, input_tokens, output_tokens),
        )


def _quality(result: WorkflowResult, expected: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    actual_citations = [citation["id"] for citation in result.analysis.citations]
    deterministic_gate = result.route == "deterministic_security_gate"
    output = result.model_output
    output_dict = output if isinstance(output, dict) else {}
    if deterministic_gate:
        output_schema_valid = output is None
        output_aligned = output is None
        output_reviewable = True
        output_private = True
    elif result.route == "large_full_context":
        required = {
            "category",
            "priority",
            "assignment_group",
            "summary",
            "draft_response",
            "citations",
            "requires_escalation",
        }
        output_schema_valid = isinstance(output, dict) and required <= set(output)
        output_aligned = bool(
            output_schema_valid
            and output_dict["category"] == result.analysis.category
            and output_dict["priority"] == result.analysis.priority
            and output_dict["assignment_group"] == result.analysis.assignment_group
            and output_dict["summary"] == result.analysis.summary
            and output_dict["draft_response"] == result.analysis.draft_response
            and output_dict["citations"] == result.analysis.citations
            and output_dict["requires_escalation"] == result.analysis.requires_escalation
        )
        output_reviewable = bool(
            output_schema_valid
            and isinstance(output_dict["draft_response"], str)
            and 20 <= len(output_dict["draft_response"]) <= 1000
        )
        serialized_output = json.dumps(output, sort_keys=True) if output_schema_valid else ""
        output_private = bool(
            output_schema_valid
            and "never-log-this" not in serialized_output
            and not redact_sensitive_text(serialized_output)[1]
        )
    else:
        output_schema_valid = isinstance(output, dict) and set(output) == {
            "draft_response",
            "summary",
        }
        output_aligned = bool(
            output_schema_valid
            and output_dict["draft_response"] == result.analysis.draft_response
            and output_dict["summary"] == result.analysis.summary
        )
        output_reviewable = bool(
            output_schema_valid
            and isinstance(output_dict["draft_response"], str)
            and 20 <= len(output_dict["draft_response"]) <= 1000
        )
        serialized_output = json.dumps(output, sort_keys=True) if output_schema_valid else ""
        output_private = bool(
            output_schema_valid
            and "never-log-this" not in serialized_output
            and not redact_sensitive_text(serialized_output)[1]
        )

    checks = [
        {"name": "category", "passed": result.analysis.category == expected["category"]},
        {"name": "priority", "passed": result.analysis.priority == expected["priority"]},
        {
            "name": "assignment_group",
            "passed": result.analysis.assignment_group == expected["assignment_group"],
        },
        {"name": "citations", "passed": actual_citations == expected["citation_ids"]},
        {
            "name": "requires_escalation",
            "passed": result.analysis.requires_escalation == expected["requires_escalation"],
        },
        {"name": "modeled_output_schema", "passed": output_schema_valid},
        {"name": "modeled_output_policy_alignment", "passed": output_aligned},
        {"name": "modeled_output_reviewability", "passed": output_reviewable},
        {"name": "modeled_output_privacy", "passed": output_private},
    ]
    return all(check["passed"] for check in checks), checks


def _strategy_report(result: WorkflowResult, expected: dict[str, Any]) -> dict[str, Any]:
    conformance_passed, conformance_checks = _quality(result, expected)
    return {
        "route": result.route,
        "cache_hit": result.cache_hit,
        "model_calls": len(result.calls),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "estimated_cost_usd": round(result.estimated_cost_usd, 8),
        "conformance_passed": conformance_passed,
        "conformance_checks": conformance_checks,
        "calls": [call.to_report() for call in result.calls],
    }


def _validate_cases(cases: Any) -> int:
    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark fixtures must be a non-empty JSON array")
    required_case_keys = {
        "id",
        "ticket",
        "principal_scope",
        "security_gate_required",
        "forbidden_markers",
        "expected",
    }
    required_expected_keys = {
        "category",
        "priority",
        "assignment_group",
        "citation_ids",
        "requires_escalation",
    }
    ids: set[str] = set()
    ticket_texts: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not required_case_keys <= set(case):
            raise ValueError(f"Benchmark case {index} is missing required fields")
        for field_name in ("id", "ticket", "principal_scope"):
            if not isinstance(case[field_name], str) or not case[field_name].strip():
                raise ValueError(f"Benchmark case {index} has invalid {field_name}")
        if case["id"] in ids:
            raise ValueError(f"Duplicate benchmark case id: {case['id']}")
        ids.add(case["id"])
        ticket_texts.add(case["ticket"])
        if not isinstance(case["security_gate_required"], bool):
            raise TypeError(f"Benchmark case {case['id']} has invalid security_gate_required")
        if not isinstance(case["forbidden_markers"], list) or not all(
            isinstance(marker, str) and marker for marker in case["forbidden_markers"]
        ):
            raise ValueError(f"Benchmark case {case['id']} has invalid forbidden_markers")
        expected = case["expected"]
        if not isinstance(expected, dict) or not required_expected_keys <= set(expected):
            raise ValueError(f"Benchmark case {case['id']} has invalid expected fields")
        if not all(
            isinstance(expected[field_name], str) and expected[field_name]
            for field_name in ("category", "priority", "assignment_group")
        ):
            raise ValueError(f"Benchmark case {case['id']} has invalid expected strings")
        if not isinstance(expected["citation_ids"], list) or not all(
            isinstance(citation_id, str) and citation_id for citation_id in expected["citation_ids"]
        ):
            raise ValueError(f"Benchmark case {case['id']} has invalid citation_ids")
        if not isinstance(expected["requires_escalation"], bool):
            raise TypeError(f"Benchmark case {case['id']} has invalid requires_escalation")
    return len(ticket_texts)


def run_benchmark(
    cases_path: str | Path | None = None,
    price_card: PriceCard | None = None,
) -> dict[str, Any]:
    path = Path(cases_path) if cases_path else ROOT / "benchmarks" / "cases.json"
    cases = json.loads(path.read_text())
    unique_ticket_text_count = _validate_cases(cases)
    card = price_card or PriceCard()
    baseline_workflow = CostAwareWorkflow(card)
    optimized_workflow = CostAwareWorkflow(card)
    results: list[dict[str, Any]] = []
    check_totals = {"baseline": [0, 0], "optimized": [0, 0]}
    raw_cost_totals = {"baseline": 0.0, "optimized": 0.0}
    fixture_defined_safety_failures = 0

    for case in cases:
        baseline = baseline_workflow.run(
            case["ticket"],
            strategy="baseline",
            principal_scope=case["principal_scope"],
        )
        optimized = optimized_workflow.run(
            case["ticket"],
            strategy="optimized",
            principal_scope=case["principal_scope"],
        )
        raw_cost_totals["baseline"] += baseline.estimated_cost_usd
        raw_cost_totals["optimized"] += optimized.estimated_cost_usd
        baseline_report = _strategy_report(baseline, case["expected"])
        optimized_report = _strategy_report(optimized, case["expected"])
        for strategy, item in (("baseline", baseline_report), ("optimized", optimized_report)):
            checks = item["conformance_checks"]
            check_totals[strategy][0] += sum(check["passed"] for check in checks)
            check_totals[strategy][1] += len(checks)

        baseline_surface = json.dumps(
            {
                "analysis": baseline.analysis.to_dict(),
                "model_output": baseline.model_output,
                "prompts": [call.prompt for call in baseline.calls],
                "completions": [call.completion for call in baseline.calls],
            },
            sort_keys=True,
        )
        optimized_surface = json.dumps(
            {
                "analysis": optimized.analysis.to_dict(),
                "model_output": optimized.model_output,
                "prompts": [call.prompt for call in optimized.calls],
                "completions": [call.completion for call in optimized.calls],
            },
            sort_keys=True,
        )
        forbidden_marker_leaked = any(
            marker in baseline_surface or marker in optimized_surface
            for marker in case["forbidden_markers"]
        )
        security_gate_failed = case["security_gate_required"] and (
            optimized.route != "deterministic_security_gate"
            or optimized.calls
            or not optimized.analysis.requires_escalation
        )
        if forbidden_marker_leaked or security_gate_failed:
            fixture_defined_safety_failures += 1
        results.append(
            {
                "id": case["id"],
                "principal_scope": case["principal_scope"],
                "baseline": baseline_report,
                "optimized": optimized_report,
                "safety_passed": not forbidden_marker_leaked and not security_gate_failed,
            }
        )

    def aggregate(strategy: str, field: str) -> float:
        return sum(float(case[strategy][field]) for case in results)

    baseline_tokens = int(aggregate("baseline", "total_tokens"))
    optimized_tokens = int(aggregate("optimized", "total_tokens"))
    baseline_cost = raw_cost_totals["baseline"]
    optimized_cost = raw_cost_totals["optimized"]
    baseline_conformance = 100 * check_totals["baseline"][0] / check_totals["baseline"][1]
    optimized_conformance = 100 * check_totals["optimized"][0] / check_totals["optimized"][1]
    optimized_model_calls = int(aggregate("optimized", "model_calls"))
    optimized_large_calls = sum(
        call["model"] == "large-general-v1"
        for case in results
        for call in case["optimized"]["calls"]
    )
    optimized_small_calls = sum(
        call["model"] == "small-draft-v1" for case in results for call in case["optimized"]["calls"]
    )
    optimized_cache_hits = sum(case["optimized"]["cache_hit"] for case in results)
    cache_eligible_cases = sum(
        case["optimized"]["route"] != "deterministic_security_gate" for case in results
    )
    cache_hit_rate = (
        100 * optimized_cache_hits / cache_eligible_cases if cache_eligible_cases else 0.0
    )
    large_model_escalation_rate = (
        100 * optimized_large_calls / optimized_model_calls if optimized_model_calls else 0.0
    )
    token_reduction = 100 * (baseline_tokens - optimized_tokens) / baseline_tokens
    cost_reduction = 100 * (baseline_cost - optimized_cost) / baseline_cost
    conformance_delta = optimized_conformance - baseline_conformance
    every_case_conforms = all(
        case["baseline"]["conformance_passed"] and case["optimized"]["conformance_passed"]
        for case in results
    )
    thresholds = {
        "minimum_cost_reduction_pct": 50.0,
        "minimum_token_reduction_pct": 50.0,
        "minimum_baseline_fixture_conformance_score": 100.0,
        "minimum_optimized_fixture_conformance_score": 100.0,
        "maximum_conformance_drop_points": 0.0,
        "minimum_unique_ticket_text_count": 10,
        "maximum_fixture_defined_safety_failures": 0,
    }
    gates_passed = (
        cost_reduction >= thresholds["minimum_cost_reduction_pct"]
        and token_reduction >= thresholds["minimum_token_reduction_pct"]
        and baseline_conformance >= thresholds["minimum_baseline_fixture_conformance_score"]
        and optimized_conformance >= thresholds["minimum_optimized_fixture_conformance_score"]
        and conformance_delta >= -thresholds["maximum_conformance_drop_points"]
        and unique_ticket_text_count >= thresholds["minimum_unique_ticket_text_count"]
        and fixture_defined_safety_failures <= thresholds["maximum_fixture_defined_safety_failures"]
        and every_case_conforms
    )
    fixture_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    engine_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "schema_version": 2,
        "benchmark": "service-desk-cost-efficiency-replay-v1",
        "methodology": {
            "execution": "deterministic replay; no provider API called",
            "tokenizer": TOKENIZER_NAME,
            "tokenizer_package_version": version("tiktoken"),
            "token_count_boundary": "prompt and completion content; provider-specific message overhead excluded",
            "policy_version": POLICY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "output_schema_version": OUTPUT_SCHEMA_VERSION,
            "authorization_policy_version": AUTHORIZATION_POLICY_VERSION,
            "pricing": asdict(card),
            "pricing_disclaimer": "Illustrative versioned rates, not a claim about current vendor pricing.",
            "fixture_conformance": "Shared deterministic analysis plus route-specific modeled-output schema, alignment, reviewability, and privacy checks. This is not independent live-model quality evidence.",
            "fixture_sha256": fixture_sha,
            "engine_sha256": engine_sha,
        },
        "summary": {
            "case_count": len(results),
            "unique_ticket_text_count": unique_ticket_text_count,
            "baseline_model_calls": int(aggregate("baseline", "model_calls")),
            "optimized_model_calls": optimized_model_calls,
            "optimized_large_model_calls": optimized_large_calls,
            "optimized_small_model_calls": optimized_small_calls,
            "baseline_total_tokens": baseline_tokens,
            "optimized_total_tokens": optimized_tokens,
            "token_reduction_pct": round(token_reduction, 2),
            "baseline_estimated_cost_usd": round(baseline_cost, 8),
            "optimized_estimated_cost_usd": round(optimized_cost, 8),
            "cost_reduction_pct": round(cost_reduction, 2),
            "baseline_fixture_conformance_score": round(baseline_conformance, 2),
            "optimized_fixture_conformance_score": round(optimized_conformance, 2),
            "fixture_conformance_delta_points": round(conformance_delta, 2),
            "optimized_cache_hits": optimized_cache_hits,
            "optimized_cache_eligible_cases": cache_eligible_cases,
            "optimized_cache_hit_rate_pct": round(cache_hit_rate, 2),
            "optimized_large_model_escalation_rate_pct": round(large_model_escalation_rate, 2),
            "latency": "not measured; no provider API called",
            "fixture_defined_safety_failures": fixture_defined_safety_failures,
        },
        "gates": {"thresholds": thresholds, "passed": gates_passed},
        "cases": results,
    }


def load_verified_report(report_path: str | Path | None = None) -> dict[str, Any]:
    """Load checked-in evidence only when a fresh replay matches it exactly."""

    path = Path(report_path) if report_path else ROOT / "benchmarks" / "latest-report.json"
    checked_in = json.loads(path.read_text())
    fresh = run_benchmark()
    if checked_in != fresh:
        raise ValueError("Checked-in cost evidence failed integrity verification")
    return checked_in
