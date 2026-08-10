# AI Service Desk Copilot

A public, fully synthetic ServiceNow-style portfolio demo showing how an AI copilot can assist—but not control—enterprise support operations.

> **Safety boundary:** Use synthetic data only. The copilot generates reviewable suggestions. It cannot close tickets, make endpoint changes, reset accounts, isolate devices, or authorize its own recommendations.

## Why this is more than a chatbot

- Deterministic ticket classification, priority, and assignment-group recommendations
- Security indicators override routine wording
- Multi-user correlation and major-incident candidates
- Explainable duplicate detection with shared terms and scores
- Troubleshooting steps grounded in cited, versioned knowledge articles
- Honest abstention and manual triage when KB evidence is insufficient
- Common secret/identifier-pattern redaction before summaries
- SLA targets based on suggested priority
- Draft requester responses
- Explicit technician accept/reject workflow
- Immutable-style audit history of analysis and technician decisions
- Synthetic ServiceNow-style incident queue and technician workspace
- Regression evaluations, API tests, Docker, and CI

## Demonstrated scenarios

Suspicious PowerShell, Eaglesoft office outage, VPN/MFA failure, account lockout, printer/DHCP mismatch, DNS failure, low disk space, Outlook profile corruption, duplicate incidents, and access requests.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
uvicorn service_desk.app:app --reload
```

Open <http://127.0.0.1:8000>, click **Reset demo**, select a ticket, and request an analysis.

## Verify

```bash
pytest -q
ruff check .
python scripts/run_evals.py
docker compose config
docker build -t ai-service-desk-copilot .
```

## Architecture

```text
Synthetic ticket → deterministic copilot → cited KB + duplicate evidence
                                           ↓
Technician review → accept/reject → controlled ticket update → audit event
```

The initial release deliberately uses deterministic rules and lexical retrieval so every recommendation is inspectable and reproducible. A future optional LLM adapter can draft language, but deterministic security escalation and authorization boundaries must remain authoritative.

## Honest limitations

This is not connected to ServiceNow, Microsoft Entra ID, an EDR, RMM, SIEM, email, production endpoints, or a real employer environment. The built-in knowledge base and tickets are fictional. Priority logic is illustrative and must be replaced with an organization's approved impact/urgency matrix before real use. Authentication, named-user RBAC, tenant isolation, enterprise secrets, retention, and integration-specific controls are required for production.

## Planned next increments

- Named-user viewer/technician/manager RBAC
- Permission-aware vector retrieval and document-version conflict warnings
- Incident clustering over time windows
- Model-provider adapter for response drafting with deterministic policy reapplication
- Precision/recall metrics and adversarial ticket corpus
- Exportable evaluation and audit reports

## License

MIT © 2026 Mark Testa. See [`LICENSE`](LICENSE).
