from __future__ import annotations


def build_troubleshooting_plan(analysis: dict) -> dict:
    """Create a bounded, evidence-collection plan from a reviewed analysis."""
    category = analysis["category"]
    citation_id = analysis.get("citations", [{}])[0].get("id") if analysis.get("citations") else None

    if analysis.get("requires_escalation") or category == "security_incident":
        steps = [
            {
                "instruction": "Capture and preserve the original alert ID, hostname, user, and timestamp.",
                "purpose": "Preserve the minimum evidence Security Operations needs.",
                "expected_evidence": "Alert identifier and affected synthetic asset context",
            },
            {
                "instruction": "Confirm whether the suspicious activity is still occurring without modifying the endpoint.",
                "purpose": "Establish current risk while avoiding evidence destruction.",
                "expected_evidence": "Current alert state and last-seen timestamp",
            },
            {
                "instruction": "Record relevant related alerts and recent approved changes.",
                "purpose": "Provide context for SOC correlation.",
                "expected_evidence": "Related alert IDs or an explicit none-found result",
            },
            {
                "instruction": "Prepare the evidence package for Security Operations and stop routine remediation.",
                "purpose": "Respect the service-desk-to-SOC authority boundary.",
                "expected_evidence": "Complete escalation handoff",
            },
        ]
        return {
            "mode": "escalation_only",
            "hypothesis": "Potential security incident requiring evidence preservation and SOC review.",
            "confidence": "high",
            "stop_condition": "Do not perform routine remediation; stop after evidence collection and escalate.",
            "steps": [{**step, "citation_id": citation_id} for step in steps],
        }

    source_steps = analysis.get("suggested_steps") or [
        "Confirm the affected service, device, users, and exact error.",
        "Record when the issue started and whether a workaround exists.",
        "Route to manual triage until supporting evidence is available.",
    ]
    steps = []
    for instruction in source_steps:
        steps.append(
            {
                "instruction": instruction,
                "purpose": "Collect evidence to confirm or reject the current hypothesis.",
                "expected_evidence": "A concise observed result from the synthetic environment",
                "citation_id": citation_id,
            }
        )
    return {
        "mode": "guided",
        "hypothesis": f"Current evidence suggests {category.replace('_', ' ')}.",
        "confidence": "medium" if citation_id else "low",
        "stop_condition": "Stop and escalate if security indicators, unexpected data exposure, or broader impact appears.",
        "steps": steps,
    }
