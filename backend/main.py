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
from routers import admin, auth, ehr, insurance, intake, notes, pain_flag, patients, prescriptions, public, transcribe, triage, voice

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to Amplify domain before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.solace_mode,
        "services": {
            "openai": bool(settings.openai_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "elevenlabs": bool(settings.elevenlabs_api_key),
            "triage": "trained_ensemble" if _triage_models_present() else "clinical_simulation",
        },
    }


def _triage_models_present() -> bool:
    model_dir = Path(__file__).parent / "models"
    needed = ["lgbm_model.pkl", "xgb_model.pkl", "catboost_model.cbm"]
    return all((model_dir / f).exists() for f in needed)


# Serve local media (audio + photos) in local mode. On AWS, S3 serves via pre-signed URLs.
if settings.solace_mode == "local":
    media_dir = Path(settings.local_media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")

# Routers — each is mounted at /api/{hospital_id}/...
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
app.include_router(public.router, prefix="/api/{hospital_id}", tags=["public"])
app.include_router(ehr.router, prefix="/api/{hospital_id}", tags=["ehr"])
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
