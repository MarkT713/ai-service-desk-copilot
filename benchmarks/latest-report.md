# Cost-Efficiency Replay Report

> Modeled synthetic replay using illustrative rates. No provider API was called; this is not provider billing, independent live-model quality, or production savings.

## Executive result

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Model calls | 12 | 9 | 3 fewer |
| Total content tokens | 8,134 | 1,355 | 83.34% reduction |
| Estimated cost | $0.125220 | $0.005257 | 95.80% reduction |
| Deterministic fixture conformance | 100.00 | 100.00 | +0.00 points |
| Fixture-defined safety failures | — | 0 | gate: 0 |
| Scope-keyed replay cache hits | 0 | 1 | not authorization evidence |
| Cache-hit rate | — | 10.00% | 10 eligible cases |
| Large-model escalation rate | 100.00% | 22.22% | bounded exceptions |

**Regression gates: PASS**

## What changed

- The baseline sends every ticket and the complete synthetic knowledge base to an illustrative large-model path.
- The optimized workflow keeps category, priority, assignment, and escalation in deterministic policy.
- Security signals stop at a deterministic escalation gate without a model call.
- Routine response drafting uses a lower-cost path with one selected article.
- Complex or unsupported cases use the large exception path with bounded context.
- Replay-cache keys include the unverified scope label, policy/schema versions, model, redacted input, and evidence fingerprints.

## Methodology boundary

- Tokenizer: `o200k_base`
- Tokenizer package: `tiktoken==0.13.0`
- Count boundary: prompt and completion content; provider-specific message overhead excluded
- Price-card version: `illustrative-usd-2026-08-v1`
- Fixture SHA-256: `7eaf2d89cd29ab4860303a8497d2f73cd157b64d79e6334c82f20b92488b869a`
- Benchmark-engine SHA-256: `be5f74387771225df8da7c0f9e2d8ba41ba2adead018b026e2b42e04b31f4fb0`
- Fixture conformance: Shared deterministic analysis plus route-specific modeled-output schema, alignment, reviewability, and privacy checks. This is not independent live-model quality evidence.
- The 100/100 values score a shared deterministic analyzer plus modeled-output envelopes; they do not compare independent model completions.
- This report estimates architecture-level token and cost differences. It is not a live-provider quality, latency, or billing benchmark.
- Latency: not measured; no provider API called

## Case routes

| Case | Baseline route | Optimized route | Cache | Conformance | Safety |
|---|---|---|---:|---:|---:|
| security-powershell | large_full_context | deterministic_security_gate | no | pass | pass |
| application-outage | large_full_context | large_exception_path | no | pass | pass |
| account-lockout | large_full_context | small_grounded_draft | no | pass | pass |
| vpn-routine | large_full_context | small_grounded_draft | no | pass | pass |
| dns-routine | large_full_context | small_grounded_draft | no | pass | pass |
| printer-routine | large_full_context | small_grounded_draft | no | pass | pass |
| disk-routine | large_full_context | small_grounded_draft | no | pass | pass |
| outlook-routine | large_full_context | small_grounded_draft | no | pass | pass |
| manual-triage-redaction | large_full_context | large_exception_path | no | pass | pass |
| vpn-scope-keyed-replay-repeat | large_full_context | scope_keyed_replay_cache | yes | pass | pass |
| printer-different-scope-no-cache | large_full_context | small_grounded_draft | no | pass | pass |
| security-phishing | large_full_context | deterministic_security_gate | no | pass | pass |
