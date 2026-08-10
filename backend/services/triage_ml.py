"""ML-powered triage refinement — 4-model stacked ensemble.

Architecture (ported from triagegeist-clinical-ai-pipeline notebook):
  Level-1: LightGBM + XGBoost + CatBoost + MLP (5-fold each)
  Level-2: Logistic Regression meta-learner on 20-dim stacked probs
  Post-hoc: Ordinal threshold optimization (Nelder-Mead on expected values)
  Uncertainty: Split conformal prediction sets (Angelopoulos & Bates 2021)

Falls back to LightGBM-only if full artifacts aren't present, or None if
no artifacts exist at all.
"""
from __future__ import annotations

import logging
import pickle
import re
from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
LAMBDA_CACHE = Path("/tmp/solace_models")


def _fetch_fold_model(fold: int, model_type: str, target: Path) -> bool:
    """Fetch a fold model file. Local first, then S3 for Lambda."""
    import os

    s3_bucket = os.environ.get("SOLACE_MODELS_BUCKET")
    filename = f"{model_type}_fold{fold}.txt"

    if not s3_bucket:
        src = MODELS_DIR / filename
        if src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
            return True
        return False

    import gzip as _gz
    import boto3

    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    target.parent.mkdir(parents=True, exist_ok=True)
    key = f"models/{filename}.gz"
    tmp_gz = target.with_suffix(".txt.gz")
    try:
        s3.download_file(s3_bucket, key, str(tmp_gz))
        with _gz.open(tmp_gz, "rb") as g, target.open("wb") as out:
            out.write(g.read())
        tmp_gz.unlink(missing_ok=True)
        return True
    except Exception as e:
        log.warning("triage_ml: failed to fetch %s: %s", key, e)
        return False


def _resolve_model_path(fold: int, model_type: str) -> Path | None:
    filename = f"{model_type}_fold{fold}.txt"
    local = MODELS_DIR / filename
    cached = LAMBDA_CACHE / filename
    if local.exists():
        return local
    if cached.exists():
        return cached
    if _fetch_fold_model(fold, model_type, cached):
        return cached
    return None


@lru_cache(maxsize=1)
def _load() -> dict | None:
    """Load all artifacts once per cold start."""
    art_path = MODELS_DIR / "artifacts.pkl"
    if not art_path.exists():
        log.warning("triage_ml: artifacts.pkl not present at %s", art_path)
        return None

    with art_path.open("rb") as f:
        art = pickle.load(f)

    n_folds = art["n_folds"]

    # Load LightGBM boosters
    try:
        import lightgbm as lgb
        boosters = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "lgbm")
            if path is None:
                log.warning("triage_ml: could not load lgbm fold %d", i)
                return None
            boosters.append(lgb.Booster(model_file=str(path)))
        art["boosters"] = boosters
    except ImportError:
        log.warning("triage_ml: lightgbm not installed")
        return None

    # Load XGBoost models
    try:
        import xgboost as xgb
        xgb_models = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "xgb")
            if path is None:
                log.info("triage_ml: xgb fold %d not found, stacking disabled", i)
                art["xgb_models"] = None
                break
            m = xgb.Booster()
            m.load_model(str(path))
            xgb_models.append(m)
        else:
            art["xgb_models"] = xgb_models
    except ImportError:
        log.info("triage_ml: xgboost not installed, stacking disabled")
        art["xgb_models"] = None

    # Load CatBoost models
    try:
        from catboost import CatBoostClassifier
        cat_models = []
        for i in range(n_folds):
            path = _resolve_model_path(i, "cat")
            if path is None:
                log.info("triage_ml: catboost fold %d not found, stacking disabled", i)
                art["cat_models"] = None
                break
            m = CatBoostClassifier()
            m.load_model(str(path))
            cat_models.append(m)
        else:
            art["cat_models"] = cat_models
    except ImportError:
        log.info("triage_ml: catboost not installed, stacking disabled")
        art["cat_models"] = None

    # MLP models + scalers are stored in the pickle directly
    art.setdefault("mlp_models", None)
    art.setdefault("mlp_scalers", None)
    art.setdefault("meta_learner", None)
    art.setdefault("opt_thresholds", None)

    # Determine ensemble mode
    has_full_stack = all([
        art.get("xgb_models"),
        art.get("cat_models"),
        art.get("mlp_models"),
        art.get("mlp_scalers"),
        art.get("meta_learner"),
    ])
    art["_stacking_enabled"] = has_full_stack

    mode = "stacked_ensemble" if has_full_stack else "lgbm_only"
    log.info(
        "triage_ml: loaded %d folds, %d features, mode=%s",
        n_folds, len(art["feature_names"]), mode,
    )
    return art


def _safe_encode(le, value: Any, modal_fallback: str | None = None) -> int:
    v = str(value) if value is not None else "unknown"
    if v in le.classes_:
        return int(le.transform([v])[0])
    if modal_fallback is not None and modal_fallback in le.classes_:
        return int(le.transform([modal_fallback])[0])
    return 0


def _apply_clinical_features(df: pd.DataFrame, keywords: dict[str, str]) -> pd.DataFrame:
    import numpy as np
    import pandas as pd
    df = df.copy()
    for col in ["systolic_bp", "diastolic_bp", "respiratory_rate", "temperature_c", "spo2"]:
        df[f"miss_{col}"] = df[col].isnull().astype(np.int8)
    df["miss_pain"] = (df["pain_score"] == -1).astype(np.int8)
    df["pain_score"] = df["pain_score"].replace(-1, np.nan)
    df["total_missing"] = df[[c for c in df.columns if c.startswith("miss_")]].sum(axis=1)

    df["flag_hypotension"] = (df["systolic_bp"] < 90).astype(np.int8)
    df["flag_hypertensive"] = (df["systolic_bp"] >= 180).astype(np.int8)
    df["flag_tachycardia"] = (df["heart_rate"] > 100).astype(np.int8)
    df["flag_bradycardia"] = (df["heart_rate"] < 50).astype(np.int8)
    df["flag_hypoxia"] = (df["spo2"] < 94).astype(np.int8)
    df["flag_severe_hypoxia"] = (df["spo2"] < 88).astype(np.int8)
    df["flag_tachypnea"] = (df["respiratory_rate"] > 20).astype(np.int8)
    df["flag_fever"] = (df["temperature_c"] > 38.0).astype(np.int8)
    df["flag_hypothermia"] = (df["temperature_c"] < 36.0).astype(np.int8)
    df["flag_severe_gcs"] = (df["gcs_total"] <= 8).astype(np.int8)
    df["flag_altered_mental"] = df["mental_status_triage"].isin(
        ["confused", "drowsy", "agitated", "unresponsive"]
    ).astype(np.int8)
    df["flag_shock_idx"] = (df["shock_index"] > 1.0).astype(np.int8)
    df["flag_severe_tachycardia"] = (df["heart_rate"] > 130).astype(np.int8)
    df["flag_severe_hypotension"] = (df["systolic_bp"] < 70).astype(np.int8)

    hx_cols = [c for c in df.columns if c.startswith("hx_")]
    df["comorbidity_burden"] = df[hx_cols].sum(axis=1) if hx_cols else 0
    df["high_comorbidity"] = (df["comorbidity_burden"] >= 3).astype(np.int8)

    df["qsofa"] = (
        (df["systolic_bp"] <= 100).astype(int)
        + (df["respiratory_rate"] >= 22).astype(int)
        + (df["gcs_total"] < 15).astype(int)
    )
    df["sirs"] = (
        ((df["temperature_c"] > 38.3) | (df["temperature_c"] < 36)).astype(int)
        + (df["heart_rate"] > 90).astype(int)
        + (df["respiratory_rate"] > 20).astype(int)
    ).astype(np.int8)
    df["cv_risk_composite"] = (
        (df["systolic_bp"] < 90).astype(int)
        + (df["heart_rate"] > 100).astype(int)
        + (df["shock_index"] > 1.0).astype(int)
        + (df["spo2"] < 94).astype(int)
    ).astype(np.int8)

    df["is_night"] = ((df["arrival_hour"] >= 22) | (df["arrival_hour"] <= 6)).astype(np.int8)
    df["is_weekend"] = df["arrival_day"].isin(["Saturday", "Sunday"]).astype(np.int8)
    df["hour_sin"] = np.sin(2 * np.pi * df["arrival_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["arrival_hour"] / 24)

    df["age_x_gcs"] = df["age"] * df["gcs_total"]
    df["age_x_news2"] = df["age"] * df["news2_score"]
    df["age_x_shock_idx"] = df["age"] * df["shock_index"]
    df["age_x_hr"] = df["age"] * df["heart_rate"]

    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    df["num_abnormal_vitals"] = df[flag_cols].sum(axis=1).astype(np.int8)

    cc_lower = df["chief_complaint_raw"].fillna("").str.lower()
    for col, pat in keywords.items():
        df[col] = cc_lower.str.contains(pat, regex=True).astype(np.int8)
    df["kw_total"] = df[list(keywords.keys())].sum(axis=1)
    return df


_HX_MAP = {
    r"hypertens|high.?blood.?pressure|\bhtn\b|elevated.?bp": "hx_hypertension",
    r"(type.?2.?diab|t2dm|dm.?2\b|diabetes mellitus type 2|non.?insulin.?dep)": "hx_diabetes_type2",
    r"(type.?1.?diab|t1dm|dm.?1\b|juvenile.?diabetes|insulin.?dep.?diab)": "hx_diabetes_type1",
    r"asthma|reactive.?airway": "hx_asthma",
    r"copd|emphysema|chronic.?bronchitis|pulmonary.?disease": "hx_copd",
    r"(heart.?failure|\bchf\b|hfref|hfpef|cardiomyopathy)": "hx_heart_failure",
    r"(atrial.?fib|\bafib\b|a.?fib|arrhythm)": "hx_atrial_fibrillation",
    r"(\bckd\b|chronic.?kidney|renal.?failure|dialysis|esrd)": "hx_ckd",
    r"(liver|cirrhosis|hepatitis|hepatic|fatty.?liver)": "hx_liver_disease",
    r"(cancer|malignan|tumor|oncolog|carcinoma|sarcoma|lymphoma|leukemia|chemotherap)": "hx_malignancy",
    r"(obesity|obese|morbid.?obes|bmi.?[>\s]3[0-9]|overweight)": "hx_obesity",
    r"(depress|\bmdd\b|mood.?disorder|dysthymi)": "hx_depression",
    r"(anxiety|\bgad\b|panic|ptsd|post.?trauma)": "hx_anxiety",
    r"(dementia|alzheimer|cognitive.?decline|memory.?loss)": "hx_dementia",
    r"(epileps|seizure.?disorder|convulsive)": "hx_epilepsy",
    r"hypothyroid|low.?thyroid|hashimoto": "hx_hypothyroidism",
    r"hyperthyroid|graves|overactive.?thyroid": "hx_hyperthyroidism",
    r"(\bhiv\b|\baids\b|immunodefic)": "hx_hiv",
    r"(coagulopath|warfarin|coumadin|eliquis|apixaban|rivaroxaban|xarelto|anticoag|blood.?thinner|factor.?v|bleeding.?disorder)": "hx_coagulopathy",
    r"(immunosuppress|transplant|prednisone|steroid|chemo|biologic|rheumatoid.?arthritis.*infliximab)": "hx_immunosuppressed",
    r"(pregnan|gestation|gravid|1st.?trimester|2nd.?trimester|3rd.?trimester)": "hx_pregnant",
    r"(substance|alcohol.?use|opioid|heroin|cocaine|amphetamine|meth|addiction|iv.?drug)": "hx_substance_use_disorder",
    r"(\bcad\b|coronary|angina|stent|cabg|\bmi\b|myocardial|heart.?attack)": "hx_coronary_artery_disease",
    r"(stroke|\bcva\b|\btia\b|cerebrovascular|brain.?bleed)": "hx_stroke_prior",
    r"(\bpvd\b|peripheral.?vascular|claudication|limb.?ischemia)": "hx_peripheral_vascular_disease",
}
_ALL_HX = [
    "hx_hypertension", "hx_diabetes_type2", "hx_diabetes_type1", "hx_asthma", "hx_copd",
    "hx_heart_failure", "hx_atrial_fibrillation", "hx_ckd", "hx_liver_disease", "hx_malignancy",
    "hx_obesity", "hx_depression", "hx_anxiety", "hx_dementia", "hx_epilepsy",
    "hx_hypothyroidism", "hx_hyperthyroidism", "hx_hiv", "hx_coagulopathy",
    "hx_immunosuppressed", "hx_pregnant", "hx_substance_use_disorder",
    "hx_coronary_artery_disease", "hx_stroke_prior", "hx_peripheral_vascular_disease",
]


def _derive_hx(conditions: list[str]) -> dict[str, int]:
    flags = {h: 0 for h in _ALL_HX}
    text = " ".join(str(c).lower() for c in (conditions or []))
    for pat, flag in _HX_MAP.items():
        if re.search(pat, text):
            flags[flag] = 1
    return flags


def build_row(patient: dict, vitals: dict) -> dict:
    """Build a single-row dict matching the training schema."""
    info = patient.get("medical_info") or {}
    if isinstance(info, str):
        import json as _j
        try:
            info = _j.loads(info)
        except Exception:
            info = {}
    conditions = info.get("conditions") or []
    hx_flags = _derive_hx(conditions)

    sbp = vitals.get("systolic_bp")
    dbp = vitals.get("diastolic_bp")
    hr = vitals.get("heart_rate")
    map_val = vitals.get("mean_arterial_pressure")
    if map_val is None and sbp is not None and dbp is not None:
        map_val = (sbp + 2 * dbp) / 3
    pp = vitals.get("pulse_pressure")
    if pp is None and sbp is not None and dbp is not None:
        pp = sbp - dbp
    shock = vitals.get("shock_index")
    if shock is None and hr is not None and sbp not in (None, 0):
        shock = hr / sbp
    news2 = vitals.get("news2_score", 0)

    row = {
        "patient_id": patient.get("patient_id", "unknown"),
        "chief_complaint_raw": patient.get("transcript", ""),
        "age": float(info.get("age") or 35),
        "sex": info.get("sex") or "unknown",
        "language": patient.get("language") or "en",
        "insurance_type": "unknown",
        "age_group": "unknown",
        "arrival_mode": "self",
        "mental_status_triage": vitals.get("mental_status") or "alert",
        "arrival_day": "Monday",
        "arrival_season": "winter",
        "shift": "day",
        "transport_origin": "home",
        "pain_location": info.get("pain_location") or "unknown",
        "chief_complaint_system": "unspecified",
        "triage_nurse_id": "unknown",
        "site_id": "demo",
        "arrival_hour": 12,
        "arrival_month": 1,
        "num_prior_ed_visits_12m": 0,
        "num_prior_admissions_12m": 0,
        "num_active_medications": len(info.get("medications") or []),
        "num_comorbidities": sum(hx_flags.values()),
        "systolic_bp": sbp,
        "diastolic_bp": dbp,
        "mean_arterial_pressure": map_val,
        "pulse_pressure": pp,
        "heart_rate": hr,
        "respiratory_rate": vitals.get("respiratory_rate"),
        "temperature_c": vitals.get("temperature_c"),
        "spo2": vitals.get("spo2"),
        "gcs_total": vitals.get("gcs_total") or 15,
        "pain_score": vitals.get("pain_score") if vitals.get("pain_score") is not None else -1,
        "weight_kg": vitals.get("weight_kg") or 70,
        "height_cm": vitals.get("height_cm") or 170,
        "bmi": vitals.get("bmi") or 24,
        "shock_index": shock if shock is not None else 0.8,
        "news2_score": news2,
        **hx_flags,
    }
    return row


def _build_feature_matrix(art: dict, patient: dict, vitals: dict) -> pd.DataFrame:
    """Shared feature construction for all model types."""
    import numpy as np
    import pandas as pd
    from scipy.sparse import hstack as sp_hstack
    row = build_row(patient, vitals)
    df = pd.DataFrame([row])

    for col, med in art["imputation_medians"].items():
        if col in df.columns:
            df[col] = df[col].fillna(med)

    df = _apply_clinical_features(df, art["keywords"])

    modal = art.get("modal_defaults", {})
    for col, le in art["label_encoders"].items():
        if col in df.columns:
            df[col + "_le"] = _safe_encode(le, df[col].iloc[0], modal_fallback=modal.get(col))

    cc = df["chief_complaint_raw"].fillna("unknown").iloc[0:1]
    tw = art["tfidf_word"].transform(cc)
    tc = art["tfidf_char"].transform(cc)
    tfidf_arr = sp_hstack([tw, tc]).toarray()
    tfidf_df = pd.DataFrame(tfidf_arr, columns=art["tfidf_names"]).astype(np.float32)

    struct_cols = art["struct_cols"]
    for c in struct_cols:
        if c not in df.columns:
            df[c] = 0.0
    X_struct = df[struct_cols].astype(np.float32).reset_index(drop=True)
    X = pd.concat([X_struct, tfidf_df.reset_index(drop=True)], axis=1)

    for c in X.columns:
        if X[c].isnull().any():
            X[c] = X[c].fillna(art["imputation_medians"].get(c, 0.0))

    X = X[art["feature_names"]]
    return X


def _predict_lgb(art: dict, X: pd.DataFrame) -> np.ndarray:
    import numpy as np
    import pandas as pd
    return np.mean([b.predict(X) for b in art["boosters"]], axis=0)


def _predict_xgb(art: dict, X: pd.DataFrame) -> np.ndarray:
    import numpy as np
    import pandas as pd
    import xgboost as xgb
    dmat = xgb.DMatrix(X)
    preds = [m.predict(dmat).reshape(-1, 5) for m in art["xgb_models"]]
    return np.mean(preds, axis=0)


def _predict_cat(art: dict, X: pd.DataFrame) -> np.ndarray:
    import numpy as np
    import pandas as pd
    preds = [m.predict_proba(X) for m in art["cat_models"]]
    return np.mean(preds, axis=0)


def _predict_mlp(art: dict, X: pd.DataFrame) -> np.ndarray:
    import numpy as np
    import pandas as pd
    preds = []
    for model, scaler in zip(art["mlp_models"], art["mlp_scalers"]):
        X_scaled = scaler.transform(X.fillna(0))
        preds.append(model.predict_proba(X_scaled))
    return np.mean(preds, axis=0)


def _stacked_predict(art: dict, X: pd.DataFrame) -> np.ndarray:
    """Full stacked ensemble: 4 base models → meta-learner → threshold opt."""
    import numpy as np
    import pandas as pd
    lgb_p = _predict_lgb(art, X)
    xgb_p = _predict_xgb(art, X)
    cat_p = _predict_cat(art, X)
    mlp_p = _predict_mlp(art, X)

    # QWK-weighted average as fallback
    weights = art.get("ensemble_weights")
    if weights is None:
        weights = [0.25, 0.25, 0.25, 0.25]
    wavg_p = (
        weights[0] * lgb_p
        + weights[1] * xgb_p
        + weights[2] * cat_p
        + weights[3] * mlp_p
    )

    # Meta-learner stacking
    meta_learner = art.get("meta_learner")
    if meta_learner is not None:
        meta_features = np.hstack([lgb_p, xgb_p, cat_p, mlp_p])
        probs = meta_learner.predict_proba(meta_features)
    else:
        probs = wavg_p

    return probs


def _apply_threshold_opt(art: dict, probs: np.ndarray) -> tuple[int, float]:
    """Apply ordinal threshold optimization if available."""
    import numpy as np
    opt_thresh = art.get("opt_thresholds")
    if opt_thresh is not None:
        ev = probs @ np.arange(1, 6)
        esi_level = int(np.digitize(ev, sorted(opt_thresh)) + 1)
        esi_level = max(1, min(5, esi_level))
        confidence = float(probs[esi_level - 1])
    else:
        pred_idx = int(np.argmax(probs))
        esi_level = pred_idx + 1
        confidence = float(probs[pred_idx])
    return esi_level, confidence


# Coverage a conformal set is assumed to hold at when the artifacts do not record
# the calibration target. Retraining should write `conformal_coverage` into
# artifacts.pkl so this is never used; until then, every output that falls back
# to it says so in `conformal_coverage_source`.
DEFAULT_CONFORMAL_COVERAGE = 0.90


@lru_cache(maxsize=1)
def model_version() -> tuple[str, str]:
    """Which model produced a score. Returns (version, how_it_was_derived).

    The ledger refuses an entry that cannot name its model, and wiring triage
    into it found that nothing here had a version: not artifacts.pkl, not
    predict()'s output, nowhere. For a shadow programme that is not a formality.
    The week-14 claim is a comparison between what Solace said and what the team
    did, and if a retrain lands mid-programme with no entry recording which model
    was speaking, the report averages two systems and presents one number.

    A content hash rather than a hand-maintained string, because a version
    somebody has to remember to bump is a version that eventually lies. A digest
    of the bytes that produced the score cannot: retrain and forget, and the
    identity changes anyway.

    A version the artifacts declare for themselves wins, because "v7-sepsis-recal"
    means something to a person and "sha256:4f2a..." does not. Which of the two
    it got is returned alongside, so nobody has to work it out later.
    """
    art = _load()
    if art is None:
        return "no-artifacts", "absent"
    declared = art.get("model_version") if isinstance(art, dict) else None
    if declared:
        return str(declared), "declared"

    path = MODELS_DIR / "artifacts.pkl"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        # Loaded from somewhere else (the /tmp cache, or an in-test stub). The
        # score is still real, so say what is true rather than inventing a
        # version or refusing to record it.
        return "unhashable-artifacts", "absent"
    return f"sha256:{digest}", "content_hash"


def predict(patient: dict, vitals: dict) -> dict[str, Any] | None:
    art = _load()
    if art is None:
        return None
    try:
        X = _build_feature_matrix(art, patient, vitals)

        if art["_stacking_enabled"]:
            probs_2d = _stacked_predict(art, X)
            probs = probs_2d[0] if probs_2d.ndim == 2 else probs_2d
            source = "stacked_ensemble_v1"
        else:
            probs_2d = _predict_lgb(art, X)
            probs = probs_2d[0] if probs_2d.ndim == 2 else probs_2d
            source = "lgbm_5fold_v2"

        esi_level, confidence = _apply_threshold_opt(art, probs)

        # Conformal prediction set
        q_hat = float(art.get("conformal_q_hat_noisy", art.get("conformal_q_hat", 0.5)))
        # What coverage level was this set calibrated to hold at?
        #
        # The artifacts store q_hat and not the alpha it was calibrated against,
        # so for existing artifacts that number is genuinely unknown here. A
        # prediction set is only a claim if it says what it claims, so rather
        # than quietly asserting 90%, the output carries where the figure came
        # from. `declared_default` means nobody wrote the calibration target
        # down; it is a placeholder, not a measurement, and anything reading it
        # should treat it as such.
        coverage = art.get("conformal_coverage")
        coverage_source = "calibrated_artifact" if coverage is not None else "declared_default"
        coverage = float(coverage) if coverage is not None else DEFAULT_CONFORMAL_COVERAGE
        conformal_set = [int(i + 1) for i, p in enumerate(probs) if (1 - p) <= q_hat]
        if not conformal_set:
            conformal_set = [esi_level]

        # SHAP explanations from LightGBM (representative, fast)
        top_features = _shap_top_features(
            art["boosters"], X, esi_level - 1, art["feature_names"], art=art
        )

        return {
            "esi_level": esi_level,
            "confidence": confidence,
            "probabilities": {str(i + 1): float(p) for i, p in enumerate(probs)},
            "conformal_set": conformal_set,
            "conformal_q_hat": q_hat,
            "conformal_coverage": coverage,
            "conformal_coverage_source": coverage_source,
            "top_features": top_features,
            "source": source,
            "model_metrics": {
                "oof_qwk": art.get("oof_qwk"),
                "oof_accuracy": art.get("oof_accuracy"),
            },
            "dataset": art.get("dataset", "Kaggle Triagegeist (80k synthetic ED encounters)"),
        }
    except Exception as e:
        log.exception("triage_ml predict failed: %s", e)
        return None


def _shap_top_features(
    boosters: list, X: pd.DataFrame, pred_class: int, feature_names: list[str],
    k: int = 5, art: dict | None = None,
) -> list[dict]:
    """Per-patient SHAP via LightGBM pred_contrib."""
    import numpy as np
    import pandas as pd
    n_features = len(feature_names)
    n_classes = 5
    b = boosters[0]
    raw = b.predict(X, pred_contrib=True)
    arr = np.asarray(raw).reshape(1, n_features + 1, n_classes)
    shap_values = arr[0, :-1, pred_class]

    order = np.argsort(np.abs(shap_values))[::-1]
    clinical_idx = [i for i in order if not feature_names[i].startswith("tfidf_")]
    text_idx = [i for i in order if feature_names[i].startswith("tfidf_")]

    picked: list[int] = []
    n_clinical = min(len(clinical_idx), max(k - 1, 0))
    picked.extend(clinical_idx[:n_clinical])
    picked.extend(text_idx[: k - len(picked)])
    picked.extend(clinical_idx[n_clinical: k - len(picked)])
    picked = picked[:k]

    row = X.iloc[0]
    return [
        {
            "feature": _display_name(feature_names[i], art),
            "value": float(row.iloc[i]),
            "shap": float(shap_values[i]),
            "direction": "increases" if shap_values[i] > 0 else "decreases",
        }
        for i in picked
    ]


def _display_name(raw: str, art: dict | None) -> str:
    if art is None:
        return raw
    m = re.match(r"tfidf_w(\d+)$", raw)
    if m and "tfidf_word" in art:
        idx = int(m.group(1))
        vocab = art["tfidf_word"].get_feature_names_out()
        if idx < len(vocab):
            return f'text·"{vocab[idx]}"'
    m = re.match(r"tfidf_c(\d+)$", raw)
    if m and "tfidf_char" in art:
        idx = int(m.group(1))
        vocab = art["tfidf_char"].get_feature_names_out()
        if idx < len(vocab):
            return f'ngram·"{vocab[idx]}"'
    return raw
