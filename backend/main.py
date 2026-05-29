"""FastAPI entrypoint. Runs locally via uvicorn; deploys to Lambda via Mangum."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mangum import Mangum

from lib.config import hydrate_from_secrets_manager, settings
from db import storage
from routers import (
    admin, appointments, auth, care_ops, cds_hooks_router, clinical_ai, ehr, ehr_auth,
    ehr_copilot, governance, hospitals, identity, insurance, intake, notes, onboarding,
    pain_flag, patients, prescriptions, public, sms as sms_router, transcribe, triage,
    voice, wave4, workflows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Install log redaction BEFORE any other module gets a logger — UUIDs + Bearer
# tokens in uvicorn/FastAPI access logs would otherwise leak into CloudWatch.
from lib import log_redaction  # noqa: E402

log_redaction.install()

log = logging.getLogger("solace")

# Hydrate secrets at import time so cold-start Lambda invocations have keys.
# In local mode this is a no-op. Safe to run multiple times.
log.info("Solace starting in %s mode", settings.solace_mode)
hydrate_from_secrets_manager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Only used in uvicorn dev — Mangum skips lifespan. Seed hospital for fresh local runs.
    storage.seed_demo_hospital()
    yield


app = FastAPI(title="Solace API", version="0.1.0", lifespan=lifespan)

# CORS — locked to known production origins. Local dev uses permissive localhost.
# HIPAA §164.312(e): restrict cross-origin access to authorized frontends only.
# Add additional origins via SOLACE_CORS_ORIGINS env var (comma-separated).
import os as _os  # noqa: E402

_PRODUCTION_ORIGINS = [
    "https://solaceaidemo.vercel.app",
    "https://solace-page.vercel.app",
    # Amplify deployments (app + landing). Keep until the Vercel cutover is done.
    "https://solace.d2gsbjipp9quan.amplifyapp.com",
    "https://main.d23unqhwfmphf2.amplifyapp.com",
]
_LOCAL_ORIGINS = [
    "http://localhost:5173",      # Vite dev server
    "http://localhost:3000",      # fallback dev port
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

def _build_cors_origins() -> list[str]:
    """Build CORS allow-list. Production = explicit domains only. Local = dev ports."""
    origins = list(_PRODUCTION_ORIGINS)
    if settings.solace_mode == "local":
        origins.extend(_LOCAL_ORIGINS)
    # Allow overrides via env var for staging/preview deployments
    extra = _os.environ.get("SOLACE_CORS_ORIGINS", "")
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_build_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.solace_mode,
        "triage": "trained_ensemble" if _triage_models_present() else "clinical_simulation",
    }


def _triage_models_present() -> bool:
    """True only if the trained ensemble actually loads via the real loader.

    Previously checked legacy filenames (lgbm_model.pkl/xgb_model.pkl/
    catboost_model.cbm) that the pipeline never produced, so /health reported
    clinical_simulation even when the trained artifacts were present. Now we ask
    the loader itself, so the status reflects reality (and the same lru_cache'd
    load the predictor uses — no extra cold-start cost).
    """
    try:
        from services import triage_ml  # noqa: PLC0415 — heavy import, only on demand
        return triage_ml._load() is not None
    except Exception:  # noqa: BLE001 — health must never raise
        return False


# Serve local media (audio + photos) in local mode. On AWS, S3 serves via pre-signed URLs.
if settings.solace_mode == "local":
    media_dir = Path(settings.local_media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

# Routers — each is mounted at /api/{hospital_id}/...
# EHR sign-in (SMART-on-FHIR) is registered FIRST so its fixed `/api/auth/ehr/...`
# paths win over the parameterized `/api/{hospital_id}/ehr/{mrn}` route that
# would otherwise match (with hospital_id="auth", mrn="vendors") and require auth.
app.include_router(ehr_auth.router)
app.include_router(identity.router, prefix="/api/{hospital_id}", tags=["identity"])
app.include_router(appointments.router, prefix="/api/{hospital_id}", tags=["appointments"])
app.include_router(sms_router.router, prefix="/api/{hospital_id}", tags=["sms"])
app.include_router(transcribe.router, prefix="/api/{hospital_id}", tags=["transcribe"])
app.include_router(intake.router, prefix="/api/{hospital_id}", tags=["intake"])
app.include_router(insurance.router, prefix="/api/{hospital_id}", tags=["insurance"])
app.include_router(pain_flag.router, prefix="/api/{hospital_id}", tags=["pain-flag"])
app.include_router(patients.router, prefix="/api/{hospital_id}", tags=["patients"])
app.include_router(prescriptions.router, prefix="/api/{hospital_id}", tags=["prescriptions"])
app.include_router(notes.router, prefix="/api/{hospital_id}", tags=["notes"])
app.include_router(triage.router, prefix="/api/{hospital_id}", tags=["triage"])
app.include_router(admin.router, prefix="/api/{hospital_id}", tags=["admin"])
app.include_router(auth.router, prefix="/api/{hospital_id}", tags=["auth"])
app.include_router(onboarding.router, prefix="/api/{hospital_id}", tags=["onboarding"])
app.include_router(public.router, prefix="/api/{hospital_id}", tags=["public"])
app.include_router(ehr.router, prefix="/api/{hospital_id}", tags=["ehr"])
app.include_router(workflows.router, prefix="/api/{hospital_id}", tags=["workflows"])
# Wave 1+2 — clinician AI surface (scribe, ddx v2, calculators, screeners,
# letters, coding, inbox drafts, refills, PA packets, drug check, discharge plan,
# specialty packs, override audit log).
app.include_router(clinical_ai.router, prefix="/api/{hospital_id}", tags=["clinical-ai"])
app.include_router(ehr_copilot.router, prefix="/api/{hospital_id}", tags=["ehr-copilot"])
# Care operations (eligibility, no-show, HEDIS, SDoH, FHIR write-back).
app.include_router(care_ops.router, prefix="/api/{hospital_id}", tags=["care-ops"])
# Wave 4 — HL7 v2 emit, multi-encounter, fax intake, sepsis bundle, cohort export,
# OCR-to-eligibility chain, MedicationStatement write, style learning, patient
# portal messages, nurse triage protocols, TEFCA QHIN stub, telehealth helpers.
app.include_router(wave4.router, prefix="/api/{hospital_id}", tags=["wave4"])
# Public CDS Hooks service — spec-required base path /cds-services.
app.include_router(cds_hooks_router.router)
# Public governance / model cards (no auth — for procurement teams + auditors).
app.include_router(governance.router)
# Hospital workspace provisioning — public onboarding. Mounted at the fixed
# `/hospitals/...` base (NOT per-hospital) because it CREATES the hospital_id.
app.include_router(hospitals.router, tags=["hospitals"])
# Voice agent — uses its own /api/voice prefix (NOT per-hospital path) because Twilio
# webhooks arrive at a fixed URL and route by the dialed number, not a URL path.
app.include_router(voice.router)


# Lambda handler (used only when deployed via Mangum)
_mangum = Mangum(app, lifespan="off")


def handler(event, context):
    """Lambda entry point. Warm pings pre-load the ML model AND run a dry prediction
    so the code path is fully JIT-warmed — first real user gets pure compute time.
    The warmup response reports whether the ML path succeeded, which our deploy smoke
    test checks so broken imports / missing artifacts fail the deploy."""
    if isinstance(event, dict) and (event.get("warmup") or event.get("source") == "aws.events"):
        ml_ok = False
        ml_error: str | None = None
        try:
            from services import triage_ml  # noqa: PLC0415

            art = triage_ml._load()
            if art is None:
                ml_error = "artifacts_missing"
            else:
                dry_patient = {
                    "patient_id": "warm",
                    "transcript": "chest pain",
                    "medical_info": {"age": 40, "sex": "male", "conditions": ["Hypertension"]},
                    "language": "en",
                }
                dry_vitals = {
                    "systolic_bp": 120, "diastolic_bp": 80, "heart_rate": 80,
                    "respiratory_rate": 16, "temperature_c": 37.0, "spo2": 98,
                    "gcs_total": 15, "pain_score": 3, "mental_status": "alert",
                }
                result = triage_ml.predict(dry_patient, dry_vitals)
                ml_ok = result is not None and result.get("esi_level") in {1, 2, 3, 4, 5}
                if not ml_ok:
                    ml_error = "predict_returned_invalid"
        except Exception as e:  # noqa: BLE001
            ml_error = f"{type(e).__name__}: {e}"
        import json as _json  # noqa: PLC0415

        return {
            "statusCode": 200,
            "body": _json.dumps({"warm": True, "ml_ok": ml_ok, "ml_error": ml_error}),
        }
    return _mangum(event, context)
