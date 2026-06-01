"""Usage metering — one billable event per triage encounter (Bet #1).

The calibrated triage ensemble runs in prod but nothing meters billable usage.
This module records a NON-PHI billing event per encounter and aggregates usage
into an ROI/value summary for a billing panel.

Design mirrors lib.provenance / lib.label_store:
  - an in-memory list is authoritative in local/test mode and a warm-container
    cache in AWS mode;
  - in AWS mode the durable copy lives in DynamoDB (CMK, ~18-month TTL) via
    db.storage.put_billing_event;
  - everything is FAILURE-SAFE: a metering error must NEVER break the triage
    request that triggered it. The caller wraps record_encounter, and this module
    also swallows its own durable-write errors.

NON-PHI by construction (SEC-002 / COMP-001): a billable event carries only
hospital_id, encounter_type, model_source, billable flag, an optional CPT hint,
an opaque event id, and a timestamp. It NEVER carries patient names, free-text
notes, vitals, or a patient UUID used as an aggregate key. The opaque id exists
only to de-duplicate within a warm container and is not patient-derived.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)


# In-memory log — authoritative in local/test mode, a warm-container cache in AWS mode
# (the durable cross-container view lives in DynamoDB via db.storage).
_EVENTS: list[dict[str, Any]] = []

# Recognized periods for usage_summary, mapped to a lookback window in milliseconds.
# None == "all time" (no since cutoff).
_PERIOD_WINDOWS_MS: dict[str, int | None] = {
    "day": 24 * 3600 * 1000,
    "week": 7 * 24 * 3600 * 1000,
    "month": 30 * 24 * 3600 * 1000,
    "quarter": 90 * 24 * 3600 * 1000,
    "year": 365 * 24 * 3600 * 1000,
    "all": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def record_encounter(
    *,
    hospital_id: str,
    encounter_type: str,
    model_source: str,
    billable: bool = True,
    cpt_hint: str | None = None,
) -> dict[str, Any]:
    """Record ONE billable usage event for a triage encounter.

    Builds a NON-PHI event and persists it (in-memory always; DynamoDB in AWS mode).
    Returns the event dict. This function is failure-safe at the durable-write
    boundary, but callers in routers should STILL wrap it (the request must never
    fail because of metering — see routers/triage.py).
    """
    event = {
        "ts": _now_iso(),
        "hospital_id": hospital_id or "_",
        "encounter_type": encounter_type,
        "model_source": model_source,
        "billable": bool(billable),
        # Opaque, non-patient-derived event id — only for warm-container de-dup.
        "event_id": uuid.uuid4().hex[:12],
    }
    if cpt_hint:
        event["cpt_hint"] = cpt_hint

    # Warm-container / local cache.
    _EVENTS.append(event)

    # Durable, cross-container persistence in AWS mode. storage.put_billing_event is
    # itself failure-safe, but guard the import/call too so metering can never raise.
    if settings.solace_mode == "aws":
        try:
            from db import storage  # noqa: PLC0415

            storage.put_billing_event(event)
        except Exception as e:  # noqa: BLE001
            # SEC-002: log hospital_id + type only, never patient-identifying fields.
            log.warning(
                "billing_event durable write failed for hospital=%s type=%s: %s",
                event["hospital_id"], encounter_type, e,
            )

    # SEC-002: breadcrumb logs only hospital_id + the non-sensitive event shape.
    log.info(
        "billing_event hospital=%s type=%s model=%s billable=%s",
        event["hospital_id"], encounter_type, model_source, event["billable"],
    )
    return event


def _events_for(hospital_id: str, *, since_ms: int | None) -> list[dict[str, Any]]:
    """Return events for a hospital within the window.

    AWS mode reads the durable, cross-container view from DynamoDB; on read failure
    or in local mode it falls back to the in-memory list (filtered the same way).
    """
    if settings.solace_mode == "aws":
        try:
            from db import storage  # noqa: PLC0415

            rows = storage.list_billing_events(hospital_id, since_ms=since_ms)
            if rows:
                return rows
        except Exception as e:  # noqa: BLE001
            log.warning("billing_event durable read failed for hospital=%s: %s", hospital_id, e)

    rows = [e for e in _EVENTS if e.get("hospital_id") == hospital_id]
    if since_ms is not None:
        cutoff = since_ms / 1000.0
        rows = [
            e for e in rows
            if _ts_to_epoch(e.get("ts", "")) >= cutoff
        ]
    return rows


def _ts_to_epoch(ts_iso: str) -> float:
    """Parse an ISO-8601 'Z' timestamp into an epoch-seconds float; 0.0 on failure."""
    try:
        return datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def usage_summary(hospital_id: str, *, period: str = "month") -> dict[str, Any]:
    """Aggregate billable usage for one hospital over `period` into a NON-PHI summary.

    Returns counts + an estimated dollar value (billable_encounters * configurable
    per-encounter rate). Aggregate-only: no event ids or per-encounter detail leak.
    Unknown periods fall back to "month".
    """
    period = period if period in _PERIOD_WINDOWS_MS else "month"
    window_ms = _PERIOD_WINDOWS_MS[period]
    since_ms = int(time.time() * 1000) - window_ms if window_ms is not None else None

    rows = _events_for(hospital_id, since_ms=since_ms)
    billable = [r for r in rows if r.get("billable", True)]

    by_type: dict[str, int] = {}
    by_model: dict[str, int] = {}
    cpt_hints: dict[str, int] = {}
    for r in billable:
        et = r.get("encounter_type", "unknown")
        ms = r.get("model_source", "unknown")
        by_type[et] = by_type.get(et, 0) + 1
        by_model[ms] = by_model.get(ms, 0) + 1
        hint = r.get("cpt_hint")
        if hint:
            cpt_hints[hint] = cpt_hints.get(hint, 0) + 1

    rate = float(settings.billing_rate_per_encounter_usd)
    billable_count = len(billable)
    return {
        "hospital_id": hospital_id,
        "period": period,
        "billable_encounters": billable_count,
        "total_events": len(rows),
        "by_encounter_type": by_type,
        "by_model_source": by_model,
        "cpt_hints": cpt_hints,
        "rate_per_encounter_usd": round(rate, 2),
        "estimated_value_usd": round(billable_count * rate, 2),
        "currency": "USD",
        "generated_at": _now_iso(),
    }


def _reset_for_tests() -> None:
    _EVENTS.clear()
