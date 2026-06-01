"""Tests for the AI-BOM, attestation pack, and RFP-export public surfaces.

These extend the Trust Report into procurement/RFP-grade artifacts. They are
PUBLIC-FACING, so the same two hard constraints apply as for the Trust Report:

  1. NO PHI / per-record data ever reaches the payload — no patient_id,
     clinician_id, free-text notes, or raw override entries, at any depth.
  2. HONEST LABELING — AI-BOM facts match real config/code (no invented model
     IDs or benchmarks); attestation maturity labels do not overclaim.

Plus a fail-closed check: when the recursive PHI guard trips, the endpoint
returns 500 rather than shipping anything.
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lib import claude, content_guard  # noqa: E402
from lib.config import settings  # noqa: E402
from main import app  # noqa: E402
from services import model_cards  # noqa: E402

_FORBIDDEN_KEYS = {"patient_id", "clinician_id", "notes", "entries", "diff_chars"}


@pytest.fixture
def client():
    return TestClient(app)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


# --------------------------------------------------------------------------
# AI-BOM
# --------------------------------------------------------------------------
def test_ai_bom_returns_aggregate_shape(client):
    resp = client.get("/api/governance/ai-bom")
    assert resp.status_code == 200
    body = resp.json()

    assert body["artifact"] == "AI Bill-of-Materials (AI-BOM)"
    assert isinstance(body["components"], list) and len(body["components"]) >= 1
    assert "data_handling_controls" in body
    assert "resolved_models" in body

    for comp in body["components"]:
        # Every component declares provider + BAA posture + purpose + evidence.
        assert "component_id" in comp
        assert "provider" in comp and "baa_covered" in comp["provider"]
        assert comp["purpose"]
        assert isinstance(comp["evidence"], list) and comp["evidence"]


def test_ai_bom_facts_match_real_config(client):
    """The AI-BOM must cite the REAL configured models + Bedrock profile IDs,
    not invented ones."""
    body = client.get("/api/governance/ai-bom").json()
    by_id = {c["component_id"]: c for c in body["components"]}

    clinical = by_id["claude_clinical"]
    assert clinical["configured_model"] == settings.model_clinical
    expected_profile = claude._BEDROCK_MODEL_MAP.get(
        settings.model_clinical, settings.model_clinical
    )
    assert clinical["bedrock_inference_profile"] == expected_profile

    utility = by_id["claude_utility"]
    assert utility["configured_model"] == settings.model_utility

    # resolved_models block mirrors live config too.
    rm = body["resolved_models"]
    assert rm["model_clinical"]["configured"] == settings.model_clinical
    assert rm["model_clinical"]["bedrock_inference_profile"] == expected_profile


def test_ai_bom_redaction_families_match_content_guard(client):
    """The HIPAA Safe Harbor redaction families must be read from the live
    content_guard redaction set, not a stale hand-copy."""
    body = client.get("/api/governance/ai-bom").json()
    families = body["data_handling_controls"]["hipaa_safe_harbor_redaction"]["families_redacted"]

    # Derive the live set the same way the source does.
    live = []
    for _pattern, replacement in content_guard._PII_REDACTIONS:
        tag = replacement.strip("[]").split(":", 1)[-1]
        if tag and tag not in live:
            live.append(tag)
    assert families == live
    assert len(families) >= 15  # all 15+ HIPAA identifier families covered


def test_ai_bom_no_phi_keys(client):
    body = client.get("/api/governance/ai-bom").json()
    leaked = _FORBIDDEN_KEYS & set(_walk_keys(body))
    assert not leaked, f"PHI keys leaked into AI-BOM: {sorted(leaked)}"


# --------------------------------------------------------------------------
# Attestation pack
# --------------------------------------------------------------------------
def test_attestation_pack_shape_and_evidence(client):
    resp = client.get("/api/governance/attestation-pack")
    assert resp.status_code == 200
    body = resp.json()

    assert body["control_count"] == len(body["controls"])
    assert body["controls"]
    for c in body["controls"]:
        assert c["control_id"]
        assert c["statement"]
        assert c["mitigates_threat"]
        assert c["maturity"] in body["maturity_legend"]
        assert isinstance(c["evidence"], list) and c["evidence"]


def test_attestation_pack_is_honest_about_synthetic_calibration(client):
    """The calibration control must be labeled synthetic, not real-world, and
    carry an honest caveat — same discipline as the Trust Report."""
    body = client.get("/api/governance/attestation-pack").json()
    by_id = {c["control_id"]: c for c in body["controls"]}

    cal = by_id["AISC-03"]
    assert cal["maturity"] == "implemented_synthetic_validation"
    assert "synthetic" in cal["honest_caveat"].lower()
    # Must not claim real-world clinical validation as fact.
    assert "synthetic" in cal["statement"].lower()


def test_attestation_pack_no_phi_keys(client):
    body = client.get("/api/governance/attestation-pack").json()
    leaked = _FORBIDDEN_KEYS & set(_walk_keys(body))
    assert not leaked, f"PHI keys leaked into attestation pack: {sorted(leaked)}"


# --------------------------------------------------------------------------
# RFP export bundle
# --------------------------------------------------------------------------
def test_rfp_export_bundles_all_three(client):
    resp = client.get("/api/governance/rfp-export")
    assert resp.status_code == 200
    body = resp.json()

    for key in ("trust_report", "ai_bom", "attestation_pack"):
        assert key in body, f"missing bundled artifact: {key}"
    assert body["preliminary"] is True
    assert "synthetic" in body["disclaimer"].lower()
    # The bundled trust report carries the new AI-BOM + attestation sections.
    assert "ai_bom" in body["trust_report"]
    assert "attestation_pack" in body["trust_report"]


def test_rfp_export_no_phi_keys_even_after_override(client):
    """Recording an override with PHI-ish values must not leak into the bundle."""
    from lib import provenance  # noqa: PLC0415

    provenance.record_override(
        purpose="scribe",
        model_name="claude-haiku-4-5",
        decision="edited",
        clinician_id="dr-rfp-canary",
        patient_id="patient-rfp-canary",
        hospital_id="demo",
        diff_chars=7,
        notes="rfp-canary-free-text-phi",
    )
    raw = client.get("/api/governance/rfp-export").text
    for canary in ("dr-rfp-canary", "patient-rfp-canary", "rfp-canary-free-text-phi"):
        assert canary not in raw, f"per-record value leaked into RFP export: {canary}"

    leaked = _FORBIDDEN_KEYS & set(_walk_keys(client.get("/api/governance/rfp-export").json()))
    assert not leaked


# --------------------------------------------------------------------------
# Trust Report integration + fail-closed guard
# --------------------------------------------------------------------------
def test_trust_report_now_links_ai_bom_and_attestation(client):
    body = client.get("/api/governance/trust-report").json()
    assert "ai_bom" in body
    assert "attestation_pack" in body
    assert body["endpoints"]["ai_bom"] == "/api/governance/ai-bom"
    assert body["endpoints"]["attestation_pack"] == "/api/governance/attestation-pack"
    assert body["endpoints"]["rfp_export"] == "/api/governance/rfp-export"


def test_ai_bom_fails_closed_on_phi_leak(client, monkeypatch):
    """If a regression ever injects a PHI key, the endpoint must fail closed
    (500) rather than ship the payload."""
    real_ai_bom = model_cards.ai_bom

    def _leaky():
        bom = real_ai_bom()
        bom["__leak__"] = {"patient_id": "should-never-ship"}
        return bom

    monkeypatch.setattr(model_cards, "ai_bom", _leaky)
    resp = client.get("/api/governance/ai-bom")
    assert resp.status_code == 500
    assert "patient_id" not in resp.text


def test_rfp_export_fails_closed_on_phi_leak(client, monkeypatch):
    real_attestation = model_cards.attestation_pack

    def _leaky():
        pack = real_attestation()
        pack["__leak__"] = {"notes": "should-never-ship"}
        return pack

    monkeypatch.setattr(model_cards, "attestation_pack", _leaky)
    resp = client.get("/api/governance/rfp-export")
    assert resp.status_code == 500
    assert "should-never-ship" not in resp.text
