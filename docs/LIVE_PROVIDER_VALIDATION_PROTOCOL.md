# Capped live-provider validation protocol

## Status

**Protocol only — not executed.** The published v0.3.0 evidence remains a deterministic synthetic modeled replay. No provider API was called, no provider invoice was inspected, and no live latency or probabilistic model quality was measured.

This protocol defines the minimum controls for a future optional live run without weakening the deterministic security gate or technician approval boundary.

## Preconditions

A live run may start only when all of the following are true:

1. The benchmark commit, 12-case synthetic corpus, prompt version, policy version, output schema, and model identifiers are frozen and recorded.
2. Provider credentials are supplied through a local environment variable or approved secret manager. Credentials must never be committed, printed, placed in a report, or exchanged in chat.
3. The operator explicitly approves a maximum spend and confirms the provider account's own usage limit. The default portfolio experiment ceiling is **USD $2.00**.
4. The adapter has hard limits of **12 cases, one trial per path, 150,000 total provider-reported tokens, and 15 minutes wall-clock time**. The first reached limit stops the run.
5. Only the checked-in synthetic tickets and knowledge articles are used. No employer, customer, patient, credential, or production ticket data is permitted.
6. The deterministic security escalation gate and final technician approval requirement remain authoritative. A provider completion cannot authorize or execute an action.

## Frozen comparison

Run the same ordered cases through both declared execution plans:

- **Baseline:** the documented full-context, large-route plan.
- **Optimized:** deterministic routing, bounded evidence, declared small/large model routes, security no-call gate, and no cross-case cache reuse during the primary comparison.

Record the exact provider, model or deployment identifiers, model snapshot/version when available, request parameters, region, and execution timestamp. If provider behavior is nondeterministic, a later multi-trial study must be labeled separately; one capped portfolio run is not a quality benchmark.

## Hard-stop behavior

Before each request, estimate the worst-case next-request spend using the approved price card and remaining token allowance. Do not send the request if it could exceed any cap. Stop immediately on:

- projected or observed cost above the approved budget;
- provider-reported token use above 150,000;
- more than 24 total requests;
- 15 minutes elapsed;
- a credential, privacy, safety-gate, or schema-validation failure; or
- provider usage fields that cannot be reconciled.

A stopped run is retained as a failed or incomplete run, never silently retried into a passing report.

## Evidence to capture

For every request, retain only redacted metadata and hashes—not raw prompts or credentials:

- run ID, case ID, path, route, provider, and immutable model/deployment identifier;
- request/response timestamps and observed latency;
- provider-reported input, cached-input, reasoning, and output tokens when supplied;
- actual billed or price-card-derived cost, with the source and calculation identified;
- HTTP/request attempt count, timeout, rate-limit, and retry outcomes;
- response-content SHA-256 and schema version;
- structured-output validity, deterministic fixture conformance, privacy checks, reviewability checks, and fixture-defined safety failures;
- abstention, deterministic escalation, and large-route outcomes.

The final report must include corpus, engine, prompt, policy, schema, adapter, and price-card hashes plus the source commit SHA.

## Release gates

A live report may be published only when an independent verifier recomputes its hashes and aggregates and all of these gates pass:

- all 12 cases executed in both paths unless a documented hard stop occurred;
- zero fixture-defined safety failures;
- every security case made zero provider calls;
- every completion passed schema, privacy, policy-alignment, and reviewability checks;
- optimized deterministic fixture conformance did not degrade from baseline;
- provider token totals reconcile to case-level records;
- observed cost reconciles to provider usage and a timestamped price source;
- p50 and p95 latency are computed from recorded request timings; and
- the report contains no prompt bodies, ticket bodies, secrets, or credential-like values.

## Allowed claims

A completed run may report only observations tied to its frozen configuration, for example:

> In one capped synthetic run on the named provider/model snapshots, the optimized path used X% fewer provider-reported tokens and Y% lower observed/price-derived cost, with Z/Z fixture conformance and zero fixture-defined safety failures.

It must not be described as production savings, independent model safety, general quality, SLA evidence, provider billing reconciliation unless an invoice was actually checked, or proof that cache keys provide authorization.

## Current decision

No safely configured provider credential and explicit experiment budget are available in this repository environment. Therefore the live run is intentionally deferred; the deterministic v0.3.0 replay remains the only published benchmark evidence.