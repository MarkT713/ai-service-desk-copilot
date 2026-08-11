from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class KnowledgeArticle:
    id: str
    title: str
    summary: str
    steps: tuple[str, ...]


@dataclass
class CopilotAnalysis:
    category: str
    priority: str
    assignment_group: str
    summary: str
    rationale: list[str]
    suggested_steps: list[str]
    draft_response: str
    citations: list[dict]
    requires_escalation: bool = False
    major_incident_candidate: bool = False
    autonomous_action_allowed: bool = False
    sla_due_hours: int = 24
    analyzed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


ARTICLES = {
    "KB-SEC-001": KnowledgeArticle("KB-SEC-001", "Suspicious PowerShell triage", "Preserve evidence and escalate suspicious script execution.", ("Do not run or decode the command on a production endpoint.", "Isolate the endpoint if authorized by incident policy.", "Capture Defender alert ID, user, host, and timestamp.", "Escalate to Security Operations.")),
    "KB-APP-014": KnowledgeArticle("KB-APP-014", "Business application outage", "Separate workstation faults from server or network outages.", ("Confirm scope across users and locations.", "Check application server and dependent services.", "Record first-seen time and business impact.", "Open a major-incident bridge when threshold is met.")),
    "KB-IAM-003": KnowledgeArticle("KB-IAM-003", "Account lockout and MFA recovery", "Verify identity before account or MFA changes.", ("Verify the requester using the approved identity process.", "Review lockout source and authentication logs.", "Unlock or reset only under technician authorization.", "Require fresh MFA registration when policy calls for it.")),
    "KB-NET-009": KnowledgeArticle("KB-NET-009", "DNS and connectivity isolation", "Use layered tests to isolate name-resolution failures.", ("Record IP configuration and DNS servers.", "Compare name lookup with direct IP connectivity.", "Flush local cache only after preserving relevant evidence.", "Escalate widespread failures to Infrastructure.")),
    "KB-VPN-006": KnowledgeArticle("KB-VPN-006", "VPN authentication troubleshooting", "Distinguish credential, MFA, client, and gateway failures.", ("Confirm account state and MFA enrollment.", "Capture the exact client error and timestamp.", "Compare with VPN gateway health and peer reports.", "Do not request passwords or MFA codes.")),
    "KB-PRN-005": KnowledgeArticle("KB-PRN-005", "Printer unavailable after address change", "Validate DHCP reservation, port, and queue configuration.", ("Print a configuration page and record the current IP.", "Compare the queue port with the device address.", "Check reservation and lease history.", "Update the queue only with technician approval.")),
    "KB-END-011": KnowledgeArticle("KB-END-011", "Low disk space response", "Restore safe capacity and identify abnormal growth.", ("Identify the largest approved data categories.", "Clear only approved temporary locations.", "Check update caches, logs, and profile growth.", "Escalate unexplained rapid growth or security indicators.")),
    "KB-M365-008": KnowledgeArticle("KB-M365-008", "Outlook profile corruption", "Test service health before rebuilding a local profile.", ("Check Microsoft 365 service health and web access.", "Start Outlook in safe mode and capture errors.", "Create a new profile only after preserving required settings.", "Do not delete the old profile until validation succeeds.")),
}

TOKEN_RE = re.compile(r"[a-z0-9]+")
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|api[_ -]?key|token|mfa code)\s*[:=]\s*\S+"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
)


def redact_sensitive_text(text: str) -> tuple[str, list[str]]:
    """Redact common secret/identifier shapes before summaries or audit-safe output."""
    redacted = text
    findings: list[str] = []
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(redacted):
            findings.append("sensitive_pattern_redacted")
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted, findings


def _tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "after", "user", "issue", "cannot", "fails"}
    return {x for x in TOKEN_RE.findall(text.lower()) if len(x) > 2 and x not in stop}


def detect_duplicates(text: str, tickets: list[dict]) -> list[dict]:
    query = _tokens(text)
    results = []
    for ticket in tickets:
        terms = _tokens(f"{ticket.get('title', '')} {ticket.get('description', '')}")
        shared = sorted(query & terms)
        # Containment is easier to explain than a black-box similarity score:
        # what fraction of the shorter ticket's meaningful terms are shared?
        denominator = min(len(query), len(terms))
        score = len(shared) / denominator if denominator else 0.0
        if score >= 0.25:
            results.append({"ticket_id": ticket["id"], "score": round(score, 2), "shared_terms": shared})
    return sorted(results, key=lambda x: (-x["score"], x["ticket_id"]))[:3]


def analyze_ticket(text: str) -> CopilotAnalysis:
    safe_text, privacy_findings = redact_sensitive_text(text)
    value = safe_text.lower()
    count_match = re.search(
        r"\b(\d{1,3})\s+(?:users?|workstations?|devices?|endpoints?|people|employees?)\b",
        value,
    )
    reported_count = int(count_match.group(1)) if count_match else 1
    widespread = reported_count >= 3 or any(p in value for p in ("all users", "multiple users", "entire office", "front desk workstations", "company-wide", "server is unreachable"))

    security = any(p in value for p in ("powershell", "encoded command", "defender alert", "malware", "phishing", "ransomware", "suspicious login"))
    app_outage = any(p in value for p in ("eaglesoft", "dentrix", "application outage", "server is unreachable")) and widespread
    account = any(p in value for p in ("locked out", "account lockout", "password attempts", "mfa reset"))
    vpn = "vpn" in value
    dns = any(p in value for p in ("dns", "name resolution", "resolve host"))
    printer = any(p in value for p in ("printer", "print queue", "dhcp"))
    disk = any(p in value for p in ("disk space", "disk full", "low storage"))
    outlook = any(p in value for p in ("outlook", "mail profile"))

    if security:
        category, priority, group, article = "security_incident", "P1", "Security Operations", ARTICLES["KB-SEC-001"]
        escalation, major, due = True, False, 1
        rationale = ["Security indicators override routine-language classification.", "Potential endpoint compromise requires evidence preservation and SOC review."]
    elif app_outage:
        category, priority, group, article = "application_outage", "P1", "Infrastructure", ARTICLES["KB-APP-014"]
        escalation, major, due = True, True, 1
        rationale = ["The report affects multiple workstations or a shared server.", "Business-critical application impact meets the synthetic major-incident threshold."]
    elif widespread and (dns or vpn):
        category, priority, group = "network_outage", "P1", "Infrastructure"
        article = ARTICLES["KB-NET-009"] if dns else ARTICLES["KB-VPN-006"]
        escalation, major, due = True, True, 1
        rationale = ["Multiple users share the same connectivity symptom.", "Correlated reports may indicate a service outage rather than an endpoint fault."]
    elif account:
        category, priority, group, article = "account_access", "P3", "Identity & Access", ARTICLES["KB-IAM-003"]
        escalation, major, due = False, False, 8
        rationale = ["Single-user authentication failure matches identity and access support."]
    elif vpn:
        category, priority, group, article = "remote_access", "P2", "Network Operations", ARTICLES["KB-VPN-006"]
        escalation, major, due = False, False, 4
        rationale = ["Remote-access failure requires account, MFA, client, and gateway isolation."]
    elif dns:
        category, priority, group, article = "network_connectivity", "P2", "Network Operations", ARTICLES["KB-NET-009"]
        escalation, major, due = False, False, 4
        rationale = ["Symptoms explicitly indicate name-resolution failure."]
    elif printer:
        category, priority, group, article = "printing", "P3", "Endpoint Support", ARTICLES["KB-PRN-005"]
        escalation, major, due = False, False, 8
        rationale = ["Printer and address-change terms suggest a queue-to-device mismatch."]
    elif disk:
        category, priority, group, article = "endpoint_health", "P3", "Endpoint Support", ARTICLES["KB-END-011"]
        escalation, major, due = False, False, 8
        rationale = ["Low storage is an endpoint-health issue unless correlated security signals exist."]
    elif outlook:
        category, priority, group, article = "productivity_application", "P3", "Endpoint Support", ARTICLES["KB-M365-008"]
        escalation, major, due = False, False, 8
        rationale = ["Outlook-specific symptoms route to endpoint productivity support."]
    else:
        category, priority, group, article = "general_request", "P4", "Service Desk – Manual Triage", None
        escalation, major, due = False, False, 24
        rationale = ["No high-confidence specialized or safety-critical pattern was found.", "Insufficient KB evidence: gather more information instead of proposing a fix."]

    rationale.extend(privacy_findings)
    summary = re.sub(r"\s+", " ", safe_text).strip()[:220]
    steps = list(article.steps) if article else [
        "Confirm the affected service, device, users, and exact error.",
        "Record when the issue started and whether a workaround exists.",
        "Route to manual triage until supporting evidence is available.",
    ]
    citations = (
        [{"id": article.id, "title": article.title, "summary": article.summary, "version": 1}]
        if article
        else []
    )
    return CopilotAnalysis(
        category=category,
        priority=priority,
        assignment_group=group,
        summary=summary,
        rationale=rationale,
        suggested_steps=steps,
        draft_response=(
            f"We reviewed your synthetic support request and routed it to {group}. "
            "A technician will verify the issue and follow the cited procedure before making changes."
            if article
            else "We need more information before recommending a procedure. A technician will verify the affected service, scope, exact error, and available workaround."
        ),
        citations=citations,
        requires_escalation=escalation,
        major_incident_candidate=major,
        sla_due_hours=due,
        analyzed_at=datetime.now(UTC).isoformat(),
    )
