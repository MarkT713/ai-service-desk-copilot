# Cost-efficiency methodology and threat model

## Claim boundary

This repository demonstrates an architecture-level cost replay, not production model savings.

- No model-provider API is called.
- The existing deterministic service-desk analysis produces the replay completion.
- Prompt and completion content are counted with pinned `tiktoken` and `o200k_base`.
- Provider-specific chat-message overhead is excluded.
- Estimated USD values use a versioned illustrative price card checked into source.
- Cache-hit rate and large-model escalation rate are measured from replay routes.
- Latency, provider billing, and probabilistic model quality are not measured.

The defensible result is:

> Under the checked-in fixtures, tokenizer boundary, and illustrative price card, the optimized execution plan uses fewer modeled calls and less prompt/completion content while passing the same absolute deterministic fixture-conformance and fixture-defined safety gates.

The 100/100 values score the shared deterministic analyzer plus route-specific modeled-output schema, policy-alignment, reviewability, and privacy checks. They do not compare independent model completions or predict live-model quality.

## Compared execution plans

### Baseline

Every ticket is sent to the illustrative large-model path with the complete synthetic knowledge base. The baseline intentionally represents a common but inefficient integration pattern.

### Optimized

1. Redact common sensitive patterns.
2. Apply deterministic category, priority, assignment, escalation, and safety policy.
3. Stop security-sensitive cases at a deterministic escalation gate.
4. Select only the synthetic article already chosen by deterministic routing policy.
5. Use the lower-cost draft path for routine tickets.
6. Use the large exception path for major-incident candidates and unsupported cases.
7. Reuse modeled draft results only through a scope-keyed replay cache.
8. Keep final ticket changes behind named technician approval.

## Cache boundary

The replay cache is in-memory and stores only the redacted deterministic completion. Its canonical JSON SHA-256 key includes:

- an unverified synthetic scope label;
- authorization-policy and deterministic workflow-policy versions;
- prompt version;
- output-schema version;
- selected modeled path;
- redacted ticket text; and
- selected evidence IDs, versions, and content hashes.

The portfolio demo does not implement authentication, authorization, or permission revocation. The scope label demonstrates cache-key separation only; it is not authorization evidence. A production integration must construct tenant and subject scope from validated identity claims, reauthorize cache reads, invalidate on permission or evidence changes, and test tenant separation.

## Benchmark integrity controls

- Fixtures are versioned in `benchmarks/cases.json`.
- The report records the fixture and benchmark-engine SHA-256 values, tokenizer package version, policy version, and prompt version.
- Prompt and completion bodies are not published; only token counts and hashes are retained.
- A redaction regression verifies the synthetic secret marker is absent from report output.
- Fixture conformance checks exact category, priority, assignment, citation, and escalation fields plus route-specific modeled-output schema, policy alignment, reviewability, and privacy.
- Fixture-defined security cases must use the deterministic gate, require escalation, and make zero modeled calls; fixture-defined forbidden markers are checked across analysis, prompts, completions, and cached/model outputs.
- CI regenerates the report and fails if checked-in JSON or Markdown differs.
- CI requires 100/100 baseline and optimized fixture conformance, every case/check passing, at least 10 unique ticket texts, at least 50% token and modeled-cost reduction, and zero fixture-defined safety failures.

## Threats and mitigations

| Threat | Control | Remaining limitation |
|---|---|---|
| Inflate savings with an unrealistic baseline | Baseline is explicit, inspectable, and labeled intentionally expensive | It does not represent every real deployment |
| Present estimated prices as vendor billing | Versioned illustrative price card and adjacent disclaimer | Real pricing must be supplied for deployment analysis |
| Reduce cost by degrading conformance | Absolute baseline and optimized fixture-conformance floors plus every-case gate | Deterministic fixtures do not predict live-model behavior |
| Bypass fixture-defined safety to save calls | Security route requires deterministic escalation and zero fixture-defined failures | Organization-specific policy still requires validation |
| Cross-scope replay reuse | Canonical key includes scope label, policy/schema/model versions, redacted input, and evidence fingerprints | Demo has no authentication, authorization, revocation feed, or distributed cache |
| Leak ticket text through evidence artifacts | Reports publish counts and hashes, not prompts; secret-marker test | Runtime tickets must still follow retention and logging policy |
| Non-reproducible token totals | Pinned tokenizer package, named encoding, fixture hash | Provider-specific message overhead is excluded |
| Optimize only the hand-picked corpus | Cases cover routine, security, major incident, abstention, redaction, repetition, and scope changes | Larger adversarial and live-provider suites are future work |

## Production validation still required

A real deployment needs provider invoice reconciliation, live-model quality comparisons, latency distributions, cache invalidation tests, validated identity and tenant boundaries, organization-approved ticket policy, privacy review, observability, and rollback controls.
