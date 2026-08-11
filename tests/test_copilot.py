from service_desk.copilot import ARTICLES, analyze_ticket, detect_duplicates


def test_security_signal_overrides_routine_language():
    result = analyze_ticket(
        "One user reports a routine issue, but PowerShell launched an encoded command "
        "and Defender raised an alert."
    )
    assert result.category == "security_incident"
    assert result.priority == "P1"
    assert result.assignment_group == "Security Operations"
    assert result.requires_escalation is True
    assert result.autonomous_action_allowed is False
    assert result.citations


def test_multi_user_outage_is_p1_infrastructure_incident():
    result = analyze_ticket(
        "All 14 front desk workstations cannot reach Eaglesoft. Server is unreachable."
    )
    assert result.category == "application_outage"
    assert result.priority == "P1"
    assert result.assignment_group == "Infrastructure"
    assert result.major_incident_candidate is True


def test_error_code_is_not_mistaken_for_affected_user_count():
    result = analyze_ticket("VPN fails after MFA with error 720 for one remote employee.")

    assert result.category == "remote_access"
    assert result.priority == "P2"
    assert result.major_incident_candidate is False


def test_account_lockout_routes_identity_and_access():
    result = analyze_ticket("Single user is locked out after too many password attempts.")
    assert result.category == "account_access"
    assert result.priority == "P3"
    assert result.assignment_group == "Identity & Access"


def test_duplicate_detection_explains_match():
    candidates = [
        {"id": 8, "title": "VPN authentication failure", "description": "Remote staff cannot authenticate to VPN after MFA reset"},
        {"id": 9, "title": "Printer offline", "description": "Reception printer unavailable after DHCP change"},
    ]
    matches = detect_duplicates("VPN login fails after MFA reset", candidates)
    assert matches[0]["ticket_id"] == 8
    assert matches[0]["score"] >= 0.4
    assert "mfa" in matches[0]["shared_terms"]


def test_ambiguous_ticket_abstains_without_fake_citation():
    result = analyze_ticket("Something unusual happened; please look into it")
    assert result.category == "general_request"
    assert result.assignment_group == "Service Desk – Manual Triage"
    assert result.citations == []
    assert "Insufficient KB evidence" in " ".join(result.rationale)


def test_citations_resolve_to_stored_synthetic_articles():
    result = analyze_ticket("Outlook profile cannot load but webmail works")
    assert result.citations
    assert all(citation["id"] in ARTICLES for citation in result.citations)
    assert all(citation["version"] == 1 for citation in result.citations)


def test_sensitive_values_are_redacted_before_summary():
    result = analyze_ticket("VPN fails. password=Winter2026! and SSN 123-45-6789")
    assert "Winter2026" not in result.summary
    assert "123-45-6789" not in result.summary
    assert result.summary.count("[REDACTED]") == 2
