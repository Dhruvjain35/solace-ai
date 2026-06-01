"""Tests for the deferred-intake-artifacts split.

The intake endpoint was overflowing API Gateway's 30s hard integration timeout
because ~6 sequential Bedrock/Claude calls ran synchronously. The fix keeps the
patient-critical path synchronous and defers the clinician-only artifacts
(prebrief, scribe, differential, workup, disposition) to an async Lambda
self-invoke (local mode: a thread / inline run).

These tests pin the new contract:
  * intake seeds artifacts_status="pending" + empty clinician-artifact placeholders
  * the deferred generation function populates the artifacts + flips to "ready"
  * local-mode dispatch still produces artifacts (no Lambda required)
  * the failure-safe path sets "failed" instead of crashing
  * the AWS self-invoke path uses the runtime function name + InvocationType=Event
  * no PHI is logged from the deferred path

They exercise the service + dispatch layers directly (the FastAPI endpoint itself
carries heavy nonce/quota/multipart machinery covered elsewhere); these layers
hold the load-bearing latency-split logic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `services.*` / `lib.*` / `db.*` importable exactly as the app does.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from db import storage  # noqa: E402
from lib import async_invoke  # noqa: E402
from lib.config import settings  # noqa: E402
from services import intake_artifacts  # noqa: E402


@pytest.fixture(autouse=True)
def _local_mode_clean_store(monkeypatch):
    """Force local mode and a clean in-memory store for every test.

    Also force the Claude adapter to report unavailable so the generation modules
    take their deterministic offline fallbacks instead of attempting (and slowly
    retrying) a real Bedrock call with no credentials — keeps the suite fast and
    network-free while still exercising the full deferred-artifact code path.
    """
    monkeypatch.setattr(settings, "solace_mode", "local", raising=False)
    from lib import claude  # noqa: PLC0415

    monkeypatch.setattr(claude, "available", lambda: False)
    storage._reset_for_tests()
    yield
    storage._reset_for_tests()


def _seed_pending_patient(patient_id: str = "p-1", hospital_id: str = "h-1") -> dict:
    """Persist a patient in the same 'pending' shape intake.py now writes."""
    patient = {
        "patient_id": patient_id,
        "hospital_id": hospital_id,
        "name": "Test Patient",
        "language": "en",
        "transcript": "chest pain and shortness of breath for two hours",
        "medical_info": json.dumps({"age": 58, "sex": "male", "conditions": ["Hypertension"]}),
        "followup_qa": json.dumps([{"q": "onset?", "a": "2 hours ago"}]),
        "photo_analysis": json.dumps({}),
        "esi_level": 2,
        # patient-facing fields would also be present; only the inputs matter here.
        **intake_artifacts.empty_artifacts(),
        "artifacts_status": intake_artifacts.STATUS_PENDING,
    }
    storage.put_patient(patient)
    return patient


# ---- placeholder / pending contract -------------------------------------------------
class TestPendingContract:
    def test_empty_artifacts_are_valid_json_placeholders(self):
        empty = intake_artifacts.empty_artifacts()
        assert empty["clinician_prebrief"] == ""
        assert empty["clinical_scribe_note"] == ""
        assert json.loads(empty["differential"]) == []
        assert json.loads(empty["workup_orders"]) == {}
        assert json.loads(empty["disposition"]) == {}
        # Patient-facing deferred artifacts are also seeded pending.
        assert json.loads(empty["comfort_protocol"]) == []
        assert empty["audio_url"] is None

    def test_seeded_patient_starts_pending(self):
        _seed_pending_patient()
        p = storage.get_patient("p-1")
        assert p["artifacts_status"] == intake_artifacts.STATUS_PENDING
        assert p["clinician_prebrief"] == ""
        assert json.loads(p["differential"]) == []


# ---- deferred generation populates + flips to ready ---------------------------------
class TestDeferredGeneration:
    def test_generation_populates_and_marks_ready(self):
        _seed_pending_patient()
        result = intake_artifacts.generate_clinician_artifacts("h-1", "p-1")

        assert result["artifacts_status"] == intake_artifacts.STATUS_READY
        # All five clinician artifacts written.
        for field in intake_artifacts.ARTIFACT_FIELDS:
            assert field in result

        p = storage.get_patient("p-1")
        assert p["artifacts_status"] == intake_artifacts.STATUS_READY
        # Prebrief + scribe become non-empty (Claude fallback text in local mode).
        assert p["clinician_prebrief"]
        assert p["clinical_scribe_note"]
        # differential / workup / disposition stay JSON-decodable.
        json.loads(p["differential"])
        json.loads(p["workup_orders"])
        json.loads(p["disposition"])
        # Patient-facing comfort_protocol is now generated in the deferred path
        # too (it left the synchronous intake path to fix the 30s 503). The
        # comfort fallback always returns a non-empty list of actions.
        comfort = json.loads(p["comfort_protocol"])
        assert isinstance(comfort, list) and len(comfort) > 0
        # audio_url key is present (may be None when TTS is unavailable locally).
        assert "audio_url" in p

    def test_generation_reconstructs_inputs_from_stored_record(self):
        # Even with native (already-decoded) dict/list fields (local in-memory path),
        # the _parse_json helper tolerates them.
        storage.put_patient({
            "patient_id": "p-native",
            "hospital_id": "h-1",
            "transcript": "ankle pain",
            "medical_info": {"age": 30},          # native dict, not a JSON string
            "followup_qa": [{"q": "a", "a": "b"}],  # native list
            "photo_analysis": {},
            "esi_level": 4,
            **intake_artifacts.empty_artifacts(),
            "artifacts_status": intake_artifacts.STATUS_PENDING,
        })
        result = intake_artifacts.generate_clinician_artifacts("h-1", "p-native")
        assert result["artifacts_status"] == intake_artifacts.STATUS_READY

    def test_cross_hospital_mismatch_does_not_generate(self):
        _seed_pending_patient(hospital_id="h-1")
        result = intake_artifacts.generate_clinician_artifacts("h-OTHER", "p-1")
        assert result["artifacts_status"] == intake_artifacts.STATUS_FAILED
        # Original record untouched (still pending).
        assert storage.get_patient("p-1")["artifacts_status"] == intake_artifacts.STATUS_PENDING

    def test_missing_patient_returns_failed_without_crash(self):
        result = intake_artifacts.generate_clinician_artifacts("h-1", "does-not-exist")
        assert result["artifacts_status"] == intake_artifacts.STATUS_FAILED


# ---- failure-safe path --------------------------------------------------------------
class TestFailureSafe:
    def test_generation_failure_marks_failed_not_crash(self, monkeypatch):
        _seed_pending_patient()

        def _boom(*a, **k):
            raise RuntimeError("bedrock exploded")

        # Force the first generation call to blow up.
        monkeypatch.setattr(intake_artifacts.prebrief, "generate", _boom)

        # Must NOT raise.
        result = intake_artifacts.generate_clinician_artifacts("h-1", "p-1")
        assert result["artifacts_status"] == intake_artifacts.STATUS_FAILED
        assert storage.get_patient("p-1")["artifacts_status"] == intake_artifacts.STATUS_FAILED

    def test_failure_log_contains_no_phi(self, monkeypatch, caplog):
        _seed_pending_patient()
        secret_transcript = "patient name John Q Public SSN 123-45-6789"
        storage.update_patient("p-1", {"transcript": secret_transcript})

        def _boom(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(intake_artifacts.prebrief, "generate", _boom)
        with caplog.at_level("WARNING"):
            intake_artifacts.generate_clinician_artifacts("h-1", "p-1")

        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "John Q Public" not in joined
        assert "123-45-6789" not in joined
        assert "p-1" not in joined  # patient_id never logged either


# ---- local-mode dispatch produces artifacts -----------------------------------------
class TestLocalDispatch:
    def test_dispatch_runs_in_thread_and_produces_artifacts(self):
        _seed_pending_patient()
        mode = async_invoke.dispatch_deferred_artifacts("h-1", "p-1")
        assert mode == "thread"

        # Thread is fire-and-forget; join via the run_inline equivalent for a
        # deterministic assertion that the SAME generation path produces ready.
        # (Re-running on the now-thread-populated record is idempotent.)
        result = async_invoke.run_inline("h-1", "p-1")
        assert result["artifacts_status"] == intake_artifacts.STATUS_READY
        assert storage.get_patient("p-1")["artifacts_status"] == intake_artifacts.STATUS_READY

    def test_run_inline_produces_ready(self):
        _seed_pending_patient()
        result = async_invoke.run_inline("h-1", "p-1")
        assert result["artifacts_status"] == intake_artifacts.STATUS_READY


# ---- AWS self-invoke mechanism ------------------------------------------------------
class TestAwsSelfInvoke:
    def test_aws_mode_uses_function_name_and_event_invocation(self, monkeypatch):
        monkeypatch.setattr(settings, "solace_mode", "aws", raising=False)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api-fn")

        captured = {}

        def _fake_invoke(function_name, payload):
            captured["fn"] = function_name
            captured["payload"] = payload

        monkeypatch.setattr(storage, "invoke_lambda_async", _fake_invoke)

        mode = async_invoke.dispatch_deferred_artifacts("h-1", "p-1")
        assert mode == "lambda"
        assert captured["fn"] == "solace-api-fn"
        assert captured["payload"]["deferred_artifacts"] is True
        assert captured["payload"]["hospital_id"] == "h-1"
        assert captured["payload"]["patient_id"] == "p-1"

    def test_aws_mode_missing_function_name_falls_back_to_thread(self, monkeypatch):
        monkeypatch.setattr(settings, "solace_mode", "aws", raising=False)
        monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
        # Should not call invoke_lambda_async at all.
        called = {"n": 0}
        monkeypatch.setattr(
            storage, "invoke_lambda_async",
            lambda *a, **k: called.__setitem__("n", called["n"] + 1),
        )
        mode = async_invoke.dispatch_deferred_artifacts("h-1", "p-1")
        assert mode == "thread"
        assert called["n"] == 0

    def test_aws_mode_invoke_error_falls_back_to_thread(self, monkeypatch):
        monkeypatch.setattr(settings, "solace_mode", "aws", raising=False)
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api-fn")

        def _boom(*a, **k):
            raise RuntimeError("AccessDeniedException: not authorized to invoke")

        monkeypatch.setattr(storage, "invoke_lambda_async", _boom)
        # Must degrade to thread, never raise.
        mode = async_invoke.dispatch_deferred_artifacts("h-1", "p-1")
        assert mode == "thread"


# ---- main.handler() deferred branch -------------------------------------------------
class TestHandlerDeferredBranch:
    def test_handler_branch_generates_and_reports_ready(self):
        import main  # noqa: PLC0415

        _seed_pending_patient()
        resp = main.handler(
            {"deferred_artifacts": True, "hospital_id": "h-1", "patient_id": "p-1"},
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["deferred"] is True
        assert body["artifacts_status"] == intake_artifacts.STATUS_READY
        assert storage.get_patient("p-1")["artifacts_status"] == intake_artifacts.STATUS_READY

    def test_handler_branch_missing_ids_returns_400(self):
        import main  # noqa: PLC0415

        resp = main.handler({"deferred_artifacts": True}, None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["deferred"] is False
