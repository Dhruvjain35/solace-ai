"""Active-learning LABEL STORE — the only real-clinician-label path off synthetic data.

When a clinician corrects or rejects the model's ESI assignment, that disagreement is
a gold-grade training signal: the model's own feature vector / class probabilities paired
with the clinician-confirmed ESI is exactly one labeled example. This module captures
those examples, persists them durably + tenant-scoped (DynamoDB + S3 CMK via db.storage),
and provides the path that maps accumulated labels back into
``triage_ml.recalibrate_from_outcomes`` so the conformal calibrator can be refit on real
outcomes instead of synthetic-only data.

Layering (ARCH-001/002): this lib calls ``db.storage`` for all persistence; it never
touches boto3 directly. ``triage_ml`` is imported lazily inside ``recalibrate`` to avoid
load-order / heavy-import coupling at module import time.

COMP-001: labels are training data. They are kept hospital_id-scoped and live only in the
CMK-encrypted store; nothing here is ever sent to an AI or external provider.

SEC-002: log lines emit ONLY hospital_id + counts/decision — never patient_id, clinician_id,
free-text notes, probabilities, or feature vectors (mirrors the breadcrumb in provenance.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)


# In-memory store — authoritative in local/test mode, lost on cold start in AWS mode.
# In AWS mode the durable copy lives in DynamoDB + S3 via db.storage (see capture_label).
_LABELS: list[dict[str, Any]] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def capture_label(
    *,
    hospital_id: str,
    patient_id: str,
    clinician_id: str,
    confirmed_esi: int,
    probabilities: dict[str, Any] | None = None,
    feature_vector: dict[str, Any] | list[Any] | None = None,
    model_source: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Capture one clinician-confirmed labeled training example.

    ``confirmed_esi`` is the clinician's corrected ESI (1..5). ``probabilities`` is the
    model's stored per-ESI class distribution ({"1": p1, ..., "5": p5}); ``feature_vector``
    is the input the model scored. Either is enough for downstream recalibration — but a
    label with neither is useless, so it is dropped (returns ``{"captured": False}``).

    Persists durably via ``storage.put_label`` in AWS mode; keeps the authoritative copy
    in the in-memory list in local mode. Failure of the durable write must never raise —
    this can be called from inside a clinician request path.
    """
    if confirmed_esi is None or not (1 <= int(confirmed_esi) <= 5):
        return {"captured": False, "reason": "invalid_confirmed_esi"}
    if probabilities is None and feature_vector is None:
        # Nothing to learn from — refuse to store an empty label.
        return {"captured": False, "reason": "no_features"}

    entry: dict[str, Any] = {
        "ts": _now_iso(),
        "hospital_id": hospital_id,
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "confirmed_esi": int(confirmed_esi),
        "probabilities": probabilities,
        "feature_vector": feature_vector,
        "model_source": model_source,
        "notes": notes,
    }

    # Keep the in-memory append for local/test mode and as a warm-container cache.
    _LABELS.append(entry)

    # In AWS mode also persist durably (DynamoDB + S3 CMK) so accumulated labels survive
    # Lambda cold starts and aren't fragmented across containers.
    if settings.solace_mode == "aws":
        try:
            from db import storage  # noqa: PLC0415

            storage.put_label(entry)
        except Exception as e:  # noqa: BLE001
            log.warning("ml_label durable write failed: %s", e)

    # SEC-002: log ONLY hospital_id + confirmed ESI level (a 1..5 code, not PHI). Never
    # patient_id / clinician_id / notes / probabilities / feature vectors.
    log.info("ml_label captured hospital=%s confirmed_esi=%s", hospital_id, int(confirmed_esi))
    return {"captured": True}


def list_labels(hospital_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    """Return captured labels for one hospital, oldest-first (matches local order).

    AWS mode reads the durable, cross-container view from DynamoDB; on empty/failure it
    falls back to the in-memory warm cache. Local mode uses the in-memory list.
    """
    if settings.solace_mode == "aws":
        try:
            from db import storage  # noqa: PLC0415

            rows = storage.list_labels(hospital_id, limit=limit)
            if rows:
                rows.sort(key=lambda r: r.get("ts", ""))  # oldest-first
                return rows
        except Exception as e:  # noqa: BLE001
            log.warning("ml_label durable read failed: %s", e)
    items = [r for r in _LABELS if r.get("hospital_id") == hospital_id]
    return items[-limit:]


def _to_outcome(label: dict[str, Any]) -> dict[str, Any] | None:
    """Map a stored label to the outcome shape triage_ml.recalibrate_from_outcomes expects.

    Prefers stored ``probabilities`` (no re-inference needed); otherwise passes the stored
    ``feature_vector`` through as ``patient`` so the model can re-score it. A label with a
    valid confirmed ESI but neither signal is unusable and returns None.
    """
    esi = label.get("confirmed_esi")
    if esi is None or not (1 <= int(esi) <= 5):
        return None
    probs = label.get("probabilities")
    if isinstance(probs, dict):
        return {"confirmed_esi": int(esi), "probabilities": probs}
    fv = label.get("feature_vector")
    if isinstance(fv, dict):
        return {"confirmed_esi": int(esi), "patient": fv}
    return None


def recalibrate(hospital_id: str, *, alpha: float = 0.10) -> dict[str, Any]:
    """Pull this hospital's accumulated labels and refit the conformal calibrator.

    Maps each stored label to the outcome shape and hands the batch to
    ``triage_ml.recalibrate_from_outcomes`` (imported lazily to avoid load-order coupling
    and the heavy ML import at module import time). ``recalibrate_from_outcomes`` no-ops
    gracefully when there are no usable outcomes, so this is safe to call before any labels
    exist. Returns the triage_ml summary plus the count of labels considered.
    """
    labels = list_labels(hospital_id)
    outcomes = [oc for oc in (_to_outcome(l) for l in labels) if oc is not None]

    from services import triage_ml  # noqa: PLC0415

    result = triage_ml.recalibrate_from_outcomes(outcomes, alpha=alpha)

    summary: dict[str, Any] = dict(result) if isinstance(result, dict) else {"result": result}
    summary["n_labels"] = len(labels)
    summary["n_outcomes_mapped"] = len(outcomes)

    # SEC-002: log only hospital_id + counts — never label contents.
    log.info(
        "ml_label recalibrate hospital=%s n_labels=%d n_outcomes=%d updated=%s",
        hospital_id, len(labels), len(outcomes), summary.get("updated"),
    )
    return summary
