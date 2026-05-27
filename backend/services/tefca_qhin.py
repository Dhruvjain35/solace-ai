"""TEFCA QHIN connector — patient record query across the national network.

TEFCA (Trusted Exchange Framework and Common Agreement) is the federal
agreement that connects health systems via Qualified Health Information
Networks (QHINs). As of 2026 there are 7 designated QHINs (Epic Nexus,
eHealth Exchange, Health Gorilla, MedAllies, KONZA, CommonWell, Carequality).

Solace uses the QHIN to query for outside chart data when a patient checks
in. Read-only.

Exchange flow modelled here (IHE profiles that TEFCA QHINs implement):

  1. XCPD (Cross-Community Patient Discovery) — resolve the patient's
     demographics to a list of (home community, patient id) matches across
     the connected communities.
  2. XCA Query (Cross-Community Access, "ITI-38") — for each matched
     community, ask for the registry of available documents.
  3. XCA Retrieve (ITI-39) — pull the actual document content.

Production needs a designated participant agreement under one QHIN; until
then the module returns synthetic data (gated by `USE_REAL_TEFCA`) so the UI
demos end to end. Every real network call is timeout-bounded `httpx` and
routed per QHIN.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# QHIN routing table
# --------------------------------------------------------------------------
# Per-QHIN base endpoints. Real values come from the QHIN's designated
# participant onboarding packet; env overrides keep secrets out of source.
# Each entry: {xcpd: <patient discovery URL>, xca: <document query URL>}.
_QHIN_ROUTES: dict[str, dict[str, str]] = {
    "epic_nexus": {
        "xcpd": os.getenv("QHIN_EPIC_NEXUS_XCPD", ""),
        "xca": os.getenv("QHIN_EPIC_NEXUS_XCA", ""),
    },
    "ehealth_exchange": {
        "xcpd": os.getenv("QHIN_EHEALTH_XCPD", ""),
        "xca": os.getenv("QHIN_EHEALTH_XCA", ""),
    },
    "health_gorilla": {
        "xcpd": os.getenv("QHIN_HEALTH_GORILLA_XCPD", ""),
        "xca": os.getenv("QHIN_HEALTH_GORILLA_XCA", ""),
    },
    "medallies": {
        "xcpd": os.getenv("QHIN_MEDALLIES_XCPD", ""),
        "xca": os.getenv("QHIN_MEDALLIES_XCA", ""),
    },
    "konza": {
        "xcpd": os.getenv("QHIN_KONZA_XCPD", ""),
        "xca": os.getenv("QHIN_KONZA_XCA", ""),
    },
    "commonwell": {
        "xcpd": os.getenv("QHIN_COMMONWELL_XCPD", ""),
        "xca": os.getenv("QHIN_COMMONWELL_XCA", ""),
    },
    "carequality": {
        "xcpd": os.getenv("QHIN_CAREQUALITY_XCPD", ""),
        "xca": os.getenv("QHIN_CAREQUALITY_XCA", ""),
    },
}

# The QHIN Solace exchanges through as a designated participant. Discovery
# fans out from this one QHIN's broker; it brokers to the others.
_HOME_QHIN = os.getenv("TEFCA_HOME_QHIN", "ehealth_exchange").strip().lower()

# Timeout bounds — kept <= 30s per constitution SEC-010 / COMP-004.
_XCPD_TIMEOUT_S = float(os.getenv("TEFCA_XCPD_TIMEOUT_S", "12"))
_XCA_TIMEOUT_S = float(os.getenv("TEFCA_XCA_TIMEOUT_S", "20"))


class TefcaQueryError(Exception):
    """Raised when a TEFCA network exchange fails in a non-recoverable way."""

    def __init__(self, message: str, *, stage: str | None = None, qhin: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.qhin = qhin

    def __str__(self) -> str:
        bits = [self.message]
        if self.stage:
            bits.append(f"stage={self.stage}")
        if self.qhin:
            bits.append(f"qhin={self.qhin}")
        return " | ".join(bits)


SYNTHETIC_RECORDS = {
    "JANE_DOE_19850321": {
        "patient": {"name": "Jane Doe", "dob": "1985-03-21", "sex": "F"},
        "outside_facilities": [
            {"name": "Bay Health System", "city": "Oakland, CA", "qhin": "eHealth Exchange"},
            {"name": "Sutter Health", "city": "Sacramento, CA", "qhin": "Carequality"},
        ],
        "conditions": [
            {"icd10": "E11.9", "display": "T2DM", "first_documented": "2022-04-12"},
            {"icd10": "I10", "display": "Essential hypertension", "first_documented": "2020-09-03"},
        ],
        "medications": [
            {"name": "metformin 1000 mg PO BID", "last_filled": "2026-04-30"},
            {"name": "lisinopril 10 mg PO daily", "last_filled": "2026-04-30"},
        ],
        "allergies": [{"substance": "Penicillin", "reaction": "rash", "severity": "moderate"}],
        "recent_visits": [
            {"date": "2025-12-04", "type": "outpatient", "facility": "Bay Health System", "reason": "annual physical"},
            {"date": "2024-08-15", "type": "ED", "facility": "Sutter Health", "reason": "left flank pain → urolithiasis"},
        ],
        "immunizations": [
            {"name": "Influenza", "date": "2025-10-04"},
            {"name": "COVID-19 booster", "date": "2025-09-21"},
            {"name": "Tdap", "date": "2024-04-02"},
        ],
    },
}


def _key(name: str, dob: str) -> str:
    return f"{name.upper().replace(' ', '_')}_{(dob or '').replace('-', '')}"


def query(*, patient_name: str, patient_dob: str, consent_attestation: bool = False) -> dict[str, Any]:
    """Patient Discovery (XCPD) + Document Query (XCA) across QHINs.

    Synthetic in dev; live network exchange when `USE_REAL_TEFCA=1`.
    """
    if not consent_attestation:
        return {"error": "patient consent attestation required for IAS flow"}
    use_real = os.getenv("USE_REAL_TEFCA") == "1"
    if use_real:  # pragma: no cover (no live QHIN endpoint in CI)
        try:
            return _real_query(patient_name, patient_dob)
        except TefcaQueryError as e:
            log.warning("Real TEFCA query failed: %s", e)
        except Exception as e:  # noqa: BLE001 — never crash check-in on a network error
            log.warning("Real TEFCA query raised unexpectedly: %s", e)
    record = SYNTHETIC_RECORDS.get(_key(patient_name, patient_dob))
    if not record:
        return {"found": False, "reason": "no_matching_record_in_synthetic"}
    return {
        "found": True,
        "synthetic": True,
        "qhin_pathway": "Individual Access Services (IAS) demonstration",
        "record": record,
    }


# --------------------------------------------------------------------------
# Live exchange — XCPD discovery -> XCA document query
# --------------------------------------------------------------------------


def _http_post(url: str, payload: dict[str, Any], *, timeout_s: float, stage: str, qhin: str) -> dict[str, Any]:
    """Timeout-bounded JSON POST to a QHIN endpoint.

    QHIN gateways increasingly expose a JSON facade over the underlying
    SOAP/XCA transaction; this keeps the connector transport-simple. Swap the
    body for the QHIN's SDK call if it requires raw SOAP.
    """
    import httpx  # noqa: PLC0415

    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException as e:
        raise TefcaQueryError(f"{stage} timed out after {timeout_s}s", stage=stage, qhin=qhin) from e
    except httpx.HTTPStatusError as e:
        raise TefcaQueryError(
            f"{stage} returned HTTP {e.response.status_code}", stage=stage, qhin=qhin
        ) from e
    except Exception as e:  # noqa: BLE001 — transport / parse failure
        raise TefcaQueryError(f"{stage} transport error: {e}", stage=stage, qhin=qhin) from e


def _xcpd_discover(name: str, dob: str) -> list[dict[str, Any]]:
    """XCPD Cross-Community Patient Discovery via the home QHIN broker.

    Returns a list of community matches, each:
        {"qhin": <key>, "community_id": <oid>, "patient_id": <id>,
         "facility": <display>}
    """
    route = _QHIN_ROUTES.get(_HOME_QHIN, {})
    xcpd_url = route.get("xcpd")
    if not xcpd_url:
        raise TefcaQueryError(
            f"home QHIN '{_HOME_QHIN}' has no XCPD endpoint configured",
            stage="xcpd",
            qhin=_HOME_QHIN,
        )
    body = _http_post(
        xcpd_url,
        {"demographics": {"name": name, "dob": dob}, "purposeOfUse": "TREATMENT"},
        timeout_s=_XCPD_TIMEOUT_S,
        stage="xcpd",
        qhin=_HOME_QHIN,
    )
    matches = body.get("matches") or body.get("communities") or []
    out: list[dict[str, Any]] = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        out.append(
            {
                "qhin": str(m.get("qhin", "")).strip().lower(),
                "community_id": m.get("community_id") or m.get("homeCommunityId"),
                "patient_id": m.get("patient_id") or m.get("patientId"),
                "facility": m.get("facility") or m.get("facilityName") or "",
            }
        )
    return out


def _xca_document_query(match: dict[str, Any]) -> list[dict[str, Any]]:
    """XCA ITI-38 document registry query for a single community match.

    Routes to the QHIN that owns the matched community. A per-match failure
    is logged and skipped — one unreachable community must not abort the
    whole cross-network query.
    """
    qhin = match.get("qhin") or _HOME_QHIN
    route = _QHIN_ROUTES.get(qhin, {})
    xca_url = route.get("xca") or _QHIN_ROUTES.get(_HOME_QHIN, {}).get("xca")
    if not xca_url:
        log.warning("XCA query skipped — no endpoint for QHIN '%s'", qhin)
        return []
    body = _http_post(
        xca_url,
        {
            "homeCommunityId": match.get("community_id"),
            "patientId": match.get("patient_id"),
            "purposeOfUse": "TREATMENT",
        },
        timeout_s=_XCA_TIMEOUT_S,
        stage="xca",
        qhin=qhin,
    )
    docs = body.get("documents") or body.get("documentEntries") or []
    return [d for d in docs if isinstance(d, dict)]


def _real_query(name: str, dob: str) -> dict[str, Any]:  # pragma: no cover (no live QHIN in CI)
    """Production exchange: XCPD discovery, then per-QHIN XCA document query.

    Set `USE_REAL_TEFCA=1` only after a QHIN designated participant agreement
    and after `_QHIN_ROUTES` is populated with real endpoints.
    """
    matches = _xcpd_discover(name, dob)
    if not matches:
        return {"found": False, "reason": "no_match_in_xcpd_discovery"}

    documents: list[dict[str, Any]] = []
    facilities: list[dict[str, Any]] = []
    queried_qhins: set[str] = set()
    for match in matches:
        facilities.append(
            {"name": match.get("facility", ""), "qhin": match.get("qhin", ""), "community_id": match.get("community_id")}
        )
        try:
            docs = _xca_document_query(match)
        except TefcaQueryError as e:
            log.warning("XCA query failed for community %s: %s", match.get("community_id"), e)
            continue
        queried_qhins.add(match.get("qhin", ""))
        documents.extend(docs)

    return {
        "found": bool(documents) or bool(facilities),
        "synthetic": False,
        "qhin_pathway": "XCPD discovery + XCA document query",
        "queried_qhins": sorted(q for q in queried_qhins if q),
        "outside_facilities": facilities,
        "documents": documents,
    }
