"""Deferred-work dispatch for the intake fast-path.

The intake endpoint must return well under API Gateway's 30s hard integration
timeout, but the clinician-only artifacts (prebrief, scribe, differential,
workup, disposition) need ~6 sequential Bedrock/Claude calls that overflow that
budget. We split them off: intake returns the patient-facing result fast, then
fires a *separate* asynchronous Lambda self-invocation that regenerates those
artifacts out-of-band and patches them onto the stored patient record.

AWS mode  → boto3 `invoke(InvocationType='Event')` against THIS function
            (name read from the AWS_LAMBDA_FUNCTION_NAME runtime env var). The
            actual boto3 client lives in db.storage (ARCH-002); this module only
            decides *whether/how* to dispatch.
Local mode → no Lambda exists, so we run the generation inline in a daemon thread
            (mirrors services.workflows.engine.fire) so local dev + tests still
            produce artifacts without blocking the response.

Never raises into the caller — intake has already returned the patient-facing
result by the time this runs; a dispatch failure must not surface to the patient.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from lib.config import settings

log = logging.getLogger(__name__)

# The async-invoke event marker that main.handler() branches on.
DEFERRED_ARTIFACTS_EVENT = "deferred_artifacts"


def dispatch_deferred_artifacts(hospital_id: str, patient_id: str) -> str:
    """Schedule clinician-artifact generation for a freshly-persisted patient.

    Returns the dispatch mode actually used ("lambda", "thread", or "inline")
    so callers/tests can assert behavior. Failure-safe: any error is logged
    (NON-PHI: hospital_id + dispatch mode only, never patient_id) and degraded
    to an inline run so artifacts are still produced.
    """
    payload = {
        DEFERRED_ARTIFACTS_EVENT: True,
        "hospital_id": hospital_id,
        "patient_id": patient_id,
    }

    if settings.solace_mode == "aws":
        function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        if function_name:
            try:
                from db import storage  # noqa: PLC0415 — avoid import cycle at module load

                storage.invoke_lambda_async(function_name, payload)
                return "lambda"
            except Exception as e:  # noqa: BLE001
                # SEC-002: log the failure + hospital_id, never the patient_id/payload.
                log.warning(
                    "deferred-artifacts self-invoke failed for hospital=%s, "
                    "falling back to thread: %s",
                    hospital_id, e,
                )
        else:
            log.warning(
                "AWS_LAMBDA_FUNCTION_NAME unset in AWS mode — cannot self-invoke; "
                "running deferred artifacts in a thread for hospital=%s",
                hospital_id,
            )
        # AWS-mode fallback: run in a background thread so we still patch the record.
        return _run_in_thread(hospital_id, patient_id)

    # Local / test mode — no Lambda. Run in a daemon thread so the response is not
    # blocked, matching the workflow engine's fire-and-forget pattern.
    return _run_in_thread(hospital_id, patient_id)


def _run_in_thread(hospital_id: str, patient_id: str) -> str:
    """Run artifact generation in a daemon thread (local mode / AWS fallback)."""
    threading.Thread(
        target=_generate_safe,
        args=(hospital_id, patient_id),
        daemon=True,
    ).start()
    return "thread"


def _generate_safe(hospital_id: str, patient_id: str) -> None:
    """Thread target — import the service lazily and never raise out of the thread."""
    try:
        from services import intake_artifacts  # noqa: PLC0415

        intake_artifacts.generate_clinician_artifacts(hospital_id, patient_id)
    except Exception as e:  # noqa: BLE001
        log.exception("deferred-artifacts thread failed for hospital=%s: %s", hospital_id, e)


def run_inline(hospital_id: str, patient_id: str) -> dict[str, Any]:
    """Synchronously run artifact generation (used by tests + as a last-resort path).

    Returns the artifact dict for direct assertion. Raises are NOT swallowed here —
    callers that need failure-safety should use dispatch_deferred_artifacts().
    """
    from services import intake_artifacts  # noqa: PLC0415

    return intake_artifacts.generate_clinician_artifacts(hospital_id, patient_id)
