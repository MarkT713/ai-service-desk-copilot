# Security policy

Use only synthetic data. Do not enter employer, client, employee, credential, endpoint, IP-address, or production-ticket information. Report vulnerabilities privately through GitHub security advisories. This portfolio demo is not a production ITSM, SOC, identity, or endpoint-management system.

## Cost-aware workflow controls

- Classification, priority, assignment, security escalation, and approval remain deterministic.
- Security-sensitive tickets stop before model-assisted drafting.
- Generated benchmark reports contain token counts and content hashes rather than prompts or ticket bodies. The separately published synthetic fixture corpus intentionally contains fictional ticket text and test canaries.
- The synthetic secret-marker regression must remain absent from report output.
- Replay cache keys include an unverified scope label, policy/schema/model versions, redacted input, and evidence fingerprints.
- The scope-keyed replay cache is not authorization evidence. Production cache scope must come from validated server-side identity claims, include tenant boundaries, reauthorize reads, and support revocation/invalidation.

See [`docs/COST_EFFICIENCY.md`](docs/COST_EFFICIENCY.md) for the cost-claim boundary, benchmark integrity controls, cache threat model, and production requirements.
