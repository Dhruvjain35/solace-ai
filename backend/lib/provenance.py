"""FHIR Provenance helper + AI override audit log.

Every AI-authored write to the patient chart should be wrapped with a Provenance
resource (per HTI-1 DSI transparency). This module generates the resource and
appends the override-decision (accepted / edited / rejected by clinician) to a
small in-memory + DDB-backed log so we can publish accept-rate metrics per model.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


_OVERRIDES: list[dict[str, Any]] = []  # in-memory; DDB later


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_provenance(
    *,
    target_resource: str,            # e.g. "DocumentReference/abc"
    model_name: str,                 # e.g. "claude-sonnet-4-5"
    model_version: str,              # e.g. "20251001"
    purpose: str,                    # "scribe" | "ddx" | "coding" | ...
    clinician_id: str,
    clinician_name: str,
    hospital_id: str,
    activity_code: str = "AI_GENERATE",
) -> dict[str, Any]:
    return {
        "resourceType": "Provenance",
        "id": str(uuid.uuid4()),
        "target": [{"reference": target_resource}],
        "recorded": _now_iso(),
        "activity": {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation",
                "code": activity_code,
            }],
        },
        "agent": [
            {
                "type": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    "code": "author",
                }]},
                "who": {
                    "display": f"Solace AI {purpose} — {model_name}@{model_version}",
                    "identifier": {"system": "urn:solace:ai-model", "value": f"{model_name}:{model_version}:{purpose}"},
                },
            },
            {
                "type": {"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                    "code": "verifier",
                }]},
                "who": {
                    "display": clinician_name,
                    "identifier": {"system": "urn:solace:clinician", "value": clinician_id},
                },
            },
        ],
        "extension": [
            {"url": "http://solace.health/fhir/Extension/hospital-id", "valueString": hospital_id},
        ],
    }


def record_override(
    *,
    purpose: str,
    model_name: str,
    decision: str,                   # "accepted" | "edited" | "rejected"
    clinician_id: str,
    patient_id: str,
    hospital_id: str,
    diff_chars: int = 0,
    notes: str = "",
) -> None:
    entry = {
        "ts": _now_iso(),
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "purpose": purpose,
        "model": model_name,
        "decision": decision,
        "diff_chars": diff_chars,
        "notes": notes,
    }
    _OVERRIDES.append(entry)
    log.info("ai_override %s", entry)


def overrides(hospital_id: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    items = _OVERRIDES if hospital_id is None else [o for o in _OVERRIDES if o["hospital_id"] == hospital_id]
    return items[-limit:]


def metrics(hospital_id: str | None = None) -> dict[str, Any]:
    items = overrides(hospital_id, limit=10000)
    by_purpose: dict[str, dict[str, int]] = {}
    for o in items:
        bp = by_purpose.setdefault(o["purpose"], {"accepted": 0, "edited": 0, "rejected": 0, "total": 0})
        bp[o["decision"]] = bp.get(o["decision"], 0) + 1
        bp["total"] += 1
    summary = {}
    for p, counts in by_purpose.items():
        total = max(1, counts["total"])
        summary[p] = {
            "total": counts["total"],
            "accept_rate": round(counts.get("accepted", 0) / total, 3),
            "edit_rate": round(counts.get("edited", 0) / total, 3),
            "reject_rate": round(counts.get("rejected", 0) / total, 3),
        }
    return summary
