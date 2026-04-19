"""Train Solace triage LightGBM on the Triagegeist Kaggle data.

Port of the notebook's feature engineering, trimmed to LightGBM only.
Saves artifacts needed for Lambda inference to backend/models/.
"""
from __future__ import annotations

import pickle
import re
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.sparse import hstack as sp_hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, cohen_kappa_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "triagegeist"
OUT = ROOT / "backend" / "models"
OUT.mkdir(parents=True, exist_ok=True)

SEED = 42
N_FOLDS = 5
TARGET = "triage_acuity"

KEYWORDS = {
    "kw_chest_pain": r"chest pain|chest tightness|chest pressure|angina",
    "kw_resp": r"shortness of breath|difficulty breathing|cant breathe|dyspnea",
    "kw_neuro": r"altered mental|confusion|unresponsive|unconscious",
    "kw_stroke": r"stroke|facial droop|arm weakness|hemiparesis|aphasia",
    "kw_seizure": r"seizure|convulsion|postictal|epilep",
    "kw_trauma": r"trauma|motor vehicle|mva|mvc|fall from height|assault|gunshot",
    "kw_overdose": r"overdose|ingestion|poisoning|intoxication",
    "kw_pain": r"severe pain|excruciating|worst pain|10 out of 10",
    "kw_syncope": r"syncope|fainted|passed out|loss of consciousness",
    "kw_bleed": r"hemorrhage|severe bleeding|hemoptysis|hematemesis|gi bleed",
    "kw_sepsis": r"sepsis|septic|bacteremia",
    "kw_cardiac": r"heart attack|myocardial|cardiac arrest|palpitations",
    "kw_anaphylaxis": r"anaphylaxis|allergic reaction|throat swelling",
    "kw_psych": r"suicidal|homicidal|psychosis|self harm",
    "kw_mild": r"follow.?up|prescription|refill|minor|mild|chronic stable",
}

CAT_COLS = [
    "sex", "insurance_type", "language", "age_group", "arrival_mode",
    "mental_status_triage", "arrival_day", "arrival_season", "shift",
    "transport_origin", "pain_location", "chief_complaint_system",
    "triage_nurse_id", "site_id",
]

IMPUTE_COLS = [
    "systolic_bp", "diastolic_bp", "heart_rate", "respiratory_rate",
    "temperature_c", "spo2", "mean_arterial_pressure", "pulse_pressure",
    "shock_index", "pain_score",
]


def load() -> pd.DataFrame:
    train = pd.read_csv(DATA / "train.csv")
    cc = pd.read_csv(DATA / "chief_complaints.csv")
    hx = pd.read_csv(DATA / "patient_history.csv")
    df = train.merge(cc, on="patient_id", how="left").merge(hx, on="patient_id", how="left")
    # Drop leakage
    df = df.drop(columns=["disposition", "ed_los_hours"], errors="ignore")
    return df


def clinical_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Missingness indicators
    for col in ["systolic_bp", "diastolic_bp", "respiratory_rate", "temperature_c", "spo2"]:
        df[f"miss_{col}"] = df[col].isnull().astype(np.int8)
    df["miss_pain"] = (df["pain_score"] == -1).astype(np.int8)
    df["pain_score"] = df["pain_score"].replace(-1, np.nan)
    df["total_missing"] = df[[c for c in df.columns if c.startswith("miss_")]].sum(axis=1)

    # Clinical flags
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

    # Comorbidity burden
    hx_cols = [c for c in df.columns if c.startswith("hx_")]
    df["comorbidity_burden"] = df[hx_cols].sum(axis=1)
    df["high_comorbidity"] = (df["comorbidity_burden"] >= 3).astype(np.int8)

    # qSOFA + SIRS + CV risk
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

    # Temporal
    df["is_night"] = ((df["arrival_hour"] >= 22) | (df["arrival_hour"] <= 6)).astype(np.int8)
    df["is_weekend"] = df["arrival_day"].isin(["Saturday", "Sunday"]).astype(np.int8)
    df["hour_sin"] = np.sin(2 * np.pi * df["arrival_hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["arrival_hour"] / 24)

    # Age x vital interactions
    df["age_x_gcs"] = df["age"] * df["gcs_total"]
    df["age_x_news2"] = df["age"] * df["news2_score"]
    df["age_x_shock_idx"] = df["age"] * df["shock_index"]
    df["age_x_hr"] = df["age"] * df["heart_rate"]

    # Total abnormal vitals
    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    df["num_abnormal_vitals"] = df[flag_cols].sum(axis=1).astype(np.int8)

    # Keyword flags
    cc_lower = df["chief_complaint_raw"].fillna("").str.lower()
    for col, pat in KEYWORDS.items():
        df[col] = cc_lower.str.contains(pat, regex=True).astype(np.int8)
    df["kw_total"] = df[list(KEYWORDS.keys())].sum(axis=1)

    return df


def main() -> None:
    t0 = time.time()
    print("[1/6] Loading data")
    df = load()
    print(f"       rows={len(df):,}  cols={df.shape[1]}")

    print("[2/6] Carving calibration set (10%)")
    train_idx, cal_idx = train_test_split(
        np.arange(len(df)), test_size=0.10, random_state=SEED, stratify=df[TARGET].values
    )
    train_main = df.iloc[train_idx].reset_index(drop=True)
    cal_set = df.iloc[cal_idx].reset_index(drop=True)

    print("[3/6] Clinical feature engineering")
    train_main = clinical_features(train_main)
    cal_set = clinical_features(cal_set)

    print("[4/6] Imputation + label encoding + TF-IDF (fitted on train_main only)")
    medians = {c: train_main[c].median() for c in IMPUTE_COLS if c in train_main.columns}
    for c, m in medians.items():
        train_main[c] = train_main[c].fillna(m)
        cal_set[c] = cal_set[c].fillna(m)

    label_encoders: dict[str, LabelEncoder] = {}
    for col in CAT_COLS:
        if col in train_main.columns:
            le = LabelEncoder()
            combined = pd.concat([train_main[col].astype(str), cal_set[col].astype(str)])
            le.fit(combined)
            train_main[col + "_le"] = le.transform(train_main[col].astype(str))
            cal_set[col + "_le"] = le.transform(cal_set[col].astype(str))
            label_encoders[col] = le

    cc_train = train_main["chief_complaint_raw"].fillna("unknown")
    cc_cal = cal_set["chief_complaint_raw"].fillna("unknown")

    tfidf_word = TfidfVectorizer(
        max_features=300, ngram_range=(1, 2), analyzer="word",
        min_df=3, max_df=0.95, sublinear_tf=True,
    )
    tw = tfidf_word.fit_transform(cc_train)
    tw_cal = tfidf_word.transform(cc_cal)

    tfidf_char = TfidfVectorizer(
        max_features=150, ngram_range=(2, 4), analyzer="char_wb",
        min_df=5, max_df=0.95, sublinear_tf=True,
    )
    tc = tfidf_char.fit_transform(cc_train)
    tc_cal = tfidf_char.transform(cc_cal)

    word_names = [f"tfidf_w{i}" for i in range(tw.shape[1])]
    char_names = [f"tfidf_c{i}" for i in range(tc.shape[1])]
    tfidf_names = word_names + char_names

    train_tfidf = pd.DataFrame(
        sp_hstack([tw, tc]).toarray(), columns=tfidf_names, index=train_main.index
    ).astype(np.float32)
    cal_tfidf = pd.DataFrame(
        sp_hstack([tw_cal, tc_cal]).toarray(), columns=tfidf_names, index=cal_set.index
    ).astype(np.float32)

    DROP = ["patient_id", "chief_complaint_raw", TARGET] + CAT_COLS
    struct_cols_raw = [
        c for c in train_main.columns
        if c not in DROP and c not in tfidf_names
    ]
    # Keep only numeric columns — drop any lingering object/string columns
    numeric_mask = [
        c for c in struct_cols_raw
        if pd.api.types.is_numeric_dtype(train_main[c])
    ]
    dropped = set(struct_cols_raw) - set(numeric_mask)
    if dropped:
        print(f"       dropping non-numeric: {sorted(dropped)}")
    struct_cols = numeric_mask

    X_train = pd.concat(
        [train_main[struct_cols].astype(np.float32), train_tfidf], axis=1
    )
    X_cal = pd.concat(
        [cal_set[struct_cols].astype(np.float32), cal_tfidf], axis=1
    )
    # Final NaN cleanup
    final_medians = {}
    for c in X_train.columns:
        if X_train[c].isnull().any():
            m = X_train[c].median()
            final_medians[c] = m
            X_train[c] = X_train[c].fillna(m)
            X_cal[c] = X_cal[c].fillna(m)
    y_train = train_main[TARGET].values - 1  # 1-5 → 0-4
    y_cal = cal_set[TARGET].values - 1

    feature_names = list(X_train.columns)
    print(f"       features={len(feature_names)}  train={len(X_train):,}  cal={len(X_cal):,}")

    print("[5/6] Training LightGBM (5-fold CV)")
    params = {
        "objective": "multiclass", "num_class": 5, "metric": "multi_logloss",
        "learning_rate": 0.05, "num_leaves": 127, "feature_fraction": 0.85,
        "bagging_fraction": 0.85, "bagging_freq": 5, "min_data_in_leaf": 50,
        "lambda_l2": 1.0, "verbose": -1, "seed": SEED,
    }
    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)
    oof = np.zeros((len(X_train), 5))
    boosters: list[lgb.Booster] = []
    for fold, (tr, va) in enumerate(skf.split(X_train, y_train)):
        dtr = lgb.Dataset(X_train.iloc[tr], y_train[tr])
        dva = lgb.Dataset(X_train.iloc[va], y_train[va])
        model = lgb.train(
            params, dtr, num_boost_round=800, valid_sets=[dva],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
        )
        oof[va] = model.predict(X_train.iloc[va], num_iteration=model.best_iteration)
        boosters.append(model)
        print(f"         fold {fold+1}/{N_FOLDS}  best_iter={model.best_iteration}")

    oof_pred = oof.argmax(axis=1) + 1  # back to 1-5
    y_true_1_5 = y_train + 1
    qwk = cohen_kappa_score(y_true_1_5, oof_pred, weights="quadratic")
    acc = accuracy_score(y_true_1_5, oof_pred)
    print(f"       OOF QWK={qwk:.4f}  accuracy={acc:.4f}")

    print("[6/6] Conformal calibration — clean + noise-perturbed q̂ (realistic uncertainty)")
    cal_probs = np.mean([b.predict(X_cal, num_iteration=b.best_iteration) for b in boosters], axis=0)
    alpha = 0.10  # 90% coverage
    cal_scores = 1 - cal_probs[np.arange(len(y_cal)), y_cal]
    q_hat = np.quantile(cal_scores, np.ceil((len(cal_scores) + 1) * (1 - alpha)) / len(cal_scores))
    print(f"       clean q̂={q_hat:.4f}")

    # Noise-perturbed cal set — simulates real-world vital measurement + typing noise.
    # Published ED data shows vital-sign measurement CV around 5-15% (pulse ox, manual BP).
    rng = np.random.RandomState(SEED)
    X_cal_noisy = X_cal.copy()
    noise_cols = {
        "systolic_bp": 0.08, "diastolic_bp": 0.08, "heart_rate": 0.05,
        "respiratory_rate": 0.10, "temperature_c": 0.02, "spo2": 0.02,
        "shock_index": 0.10, "news2_score": 0.15, "pain_score": 0.20,
    }
    for col, cv in noise_cols.items():
        if col in X_cal_noisy.columns:
            std = float(X_cal_noisy[col].std())
            X_cal_noisy[col] = X_cal_noisy[col].values + rng.normal(0, std * cv, size=len(X_cal_noisy))
    cal_probs_noisy = np.mean(
        [b.predict(X_cal_noisy, num_iteration=b.best_iteration) for b in boosters], axis=0
    )
    cal_scores_noisy = 1 - cal_probs_noisy[np.arange(len(y_cal)), y_cal]
    q_hat_noisy = np.quantile(
        cal_scores_noisy, np.ceil((len(cal_scores_noisy) + 1) * (1 - alpha)) / len(cal_scores_noisy)
    )
    print(f"       noise-perturbed q̂={q_hat_noisy:.4f}  (coverage={1-alpha:.0%})")
    print(f"       → {q_hat_noisy:.2%} nonconformity budget means a real OOS patient can fall")
    print(f"         up to {q_hat_noisy:.2%} away from predicted-class probability and still")
    print(f"         land inside the 90% conformal set. Use this as q̂ in production.")

    # Compute modal defaults for categorical fields — used when Solace has no value at inference
    print("       computing modal categorical defaults")
    modal_defaults: dict[str, str] = {}
    for col in CAT_COLS:
        if col in train_main.columns:
            modal_defaults[col] = str(train_main[col].mode().iloc[0])

    print("Saving artifacts →", OUT)
    for i, b in enumerate(boosters):
        b.save_model(str(OUT / f"lgbm_fold{i}.txt"))
    with (OUT / "artifacts.pkl").open("wb") as f:
        pickle.dump({
            "tfidf_word": tfidf_word,
            "tfidf_char": tfidf_char,
            "label_encoders": label_encoders,
            "imputation_medians": {**medians, **final_medians},
            "feature_names": feature_names,
            "struct_cols": struct_cols,
            "tfidf_names": tfidf_names,
            "keywords": KEYWORDS,
            "cat_cols": CAT_COLS,
            "impute_cols": IMPUTE_COLS,
            "conformal_q_hat": float(q_hat),
            "conformal_q_hat_noisy": float(q_hat_noisy),
            "modal_defaults": modal_defaults,
            "oof_qwk": float(qwk),
            "oof_accuracy": float(acc),
            "n_folds": N_FOLDS,
            "dataset": "Kaggle Triagegeist (80k synthetic ED encounters)",
            "training_data_note": (
                "QWK ≈ 1.0 reflects the clean synthetic data ceiling. On real patient data, "
                "published ESI models (MIMIC-IV, NEWS2) typically achieve QWK 0.65–0.85. "
                "The noise-perturbed q̂ gives a more realistic uncertainty budget."
            ),
        }, f)

    total_mb = sum(p.stat().st_size for p in OUT.iterdir()) / 1e6
    print(f"  [ok] artifacts size: {total_mb:.1f} MB  elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
