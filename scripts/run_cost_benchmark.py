from __future__ import annotations

import argparse
import json
from pathlib import Path

from service_desk.cost_efficiency import run_benchmark

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "benchmarks" / "latest-report.json"
MARKDOWN_PATH = ROOT / "benchmarks" / "latest-report.md"


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    gates = report["gates"]
    lines = [
        "# Cost-Efficiency Replay Report",
        "",
        (
            "> Modeled synthetic replay using illustrative rates. No provider API was called; "
            "this is not provider billing, independent live-model quality, or production savings."
        ),
        "",
        "## Executive result",
        "",
        "| Metric | Baseline | Optimized | Change |",
        "|---|---:|---:|---:|",
        (
            f"| Model calls | {summary['baseline_model_calls']} | {summary['optimized_model_calls']} | "
            f"{summary['baseline_model_calls'] - summary['optimized_model_calls']} fewer |"
        ),
        (
            f"| Total content tokens | {summary['baseline_total_tokens']:,} | "
            f"{summary['optimized_total_tokens']:,} | {summary['token_reduction_pct']:.2f}% reduction |"
        ),
        (
            f"| Estimated cost | ${summary['baseline_estimated_cost_usd']:.6f} | "
            f"${summary['optimized_estimated_cost_usd']:.6f} | "
            f"{summary['cost_reduction_pct']:.2f}% reduction |"
        ),
        (
            f"| Deterministic fixture conformance | "
            f"{summary['baseline_fixture_conformance_score']:.2f} | "
            f"{summary['optimized_fixture_conformance_score']:.2f} | "
            f"{summary['fixture_conformance_delta_points']:+.2f} points |"
        ),
        (
            f"| Fixture-defined safety failures | — | "
            f"{summary['fixture_defined_safety_failures']} | gate: 0 |"
        ),
        f"| Scope-keyed replay cache hits | 0 | {summary['optimized_cache_hits']} | not authorization evidence |",
        (
            f"| Cache-hit rate | — | {summary['optimized_cache_hit_rate_pct']:.2f}% | "
            f"{summary['optimized_cache_eligible_cases']} eligible cases |"
        ),
        (
            f"| Large-model escalation rate | 100.00% | "
            f"{summary['optimized_large_model_escalation_rate_pct']:.2f}% | bounded exceptions |"
        ),
        "",
        f"**Regression gates: {'PASS' if gates['passed'] else 'FAIL'}**",
        "",
        "## What changed",
        "",
        (
            "- The baseline sends every ticket and the complete synthetic knowledge base to an "
            "illustrative large-model path."
        ),
        (
            "- The optimized workflow keeps category, priority, assignment, and escalation in "
            "deterministic policy."
        ),
        "- Security signals stop at a deterministic escalation gate without a model call.",
        "- Routine response drafting uses a lower-cost path with one selected article.",
        "- Complex or unsupported cases use the large exception path with bounded context.",
        "- Replay-cache keys include the unverified scope label, policy/schema versions, model, redacted input, and evidence fingerprints.",
        "",
        "## Methodology boundary",
        "",
        f"- Tokenizer: `{report['methodology']['tokenizer']}`",
        f"- Tokenizer package: `tiktoken=={report['methodology']['tokenizer_package_version']}`",
        f"- Count boundary: {report['methodology']['token_count_boundary']}",
        f"- Price-card version: `{report['methodology']['pricing']['version']}`",
        f"- Fixture SHA-256: `{report['methodology']['fixture_sha256']}`",
        f"- Benchmark-engine SHA-256: `{report['methodology']['engine_sha256']}`",
        f"- Fixture conformance: {report['methodology']['fixture_conformance']}",
        "- The 100/100 values score a shared deterministic analyzer plus modeled-output envelopes; they do not compare independent model completions.",
        (
            "- This report estimates architecture-level token and cost differences. It is not a "
            "live-provider quality, latency, or billing benchmark."
        ),
        f"- Latency: {summary['latency']}",
        "",
        "## Case routes",
        "",
        "| Case | Baseline route | Optimized route | Cache | Conformance | Safety |",
        "|---|---|---|---:|---:|---:|",
    ]
    for case in report["cases"]:
        lines.append(
            f"| {case['id']} | {case['baseline']['route']} | {case['optimized']['route']} | "
            f"{'yes' if case['optimized']['cache_hit'] else 'no'} | "
            f"{'pass' if case['optimized']['conformance_passed'] else 'fail'} | "
            f"{'pass' if case['safety_passed'] else 'fail'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if checked-in evidence differs from a fresh replay or a gate fails.",
    )
    args = parser.parse_args()
    report = run_benchmark()
    markdown = render_markdown(report)
    if args.check:
        if not JSON_PATH.exists() or not MARKDOWN_PATH.exists():
            raise SystemExit("Checked-in benchmark evidence is missing")
        existing = json.loads(JSON_PATH.read_text())
        if existing != report or MARKDOWN_PATH.read_text() != markdown:
            raise SystemExit("Checked-in benchmark evidence is stale; rerun without --check")
    else:
        JSON_PATH.write_text(json.dumps(report, indent=2) + "\n")
        MARKDOWN_PATH.write_text(markdown)
    if not report["gates"]["passed"]:
        raise SystemExit("Cost-efficiency regression gates failed")
    print(json.dumps(report["summary"], indent=2))
    print("cost-efficiency gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
