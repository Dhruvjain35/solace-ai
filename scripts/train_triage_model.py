"""Train Solace triage stacked ensemble on the Triagegeist Kaggle data.

Full pipeline (ported from triagegeist-clinical-ai-pipeline notebook):
  Level-1: LightGBM + XGBoost + CatBoost + MLP (5-fold each)
  Level-2: Logistic Regression meta-learner on stacked 20-dim probs
  Post-hoc: Ordinal threshold optimization (differential evolution + Nelder-Mead)
  Uncertainty: Split conformal prediction sets

Saves all artifacts needed for Lambda inference to backend/models/.
"""
from __future__ import annotations

import pickle
import re
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from catboost import CatBoostClassifier
from scipy.optimize import differential_evolution, minimize
from scipy.sparse import hstack as sp_hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, cohen_kappa_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

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
    df = df.drop(columns=["disposition", "ed_los_hours"], errors="ignore")
    return df


def clinical_features(df: pd.DataFrame) -> pd.DataFrame:
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
    df["comorbidity_burden"] = df[hx_cols].sum(axis=1)
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
    for col, pat in KEYWORDS.items():
        df[col] = cc_lower.str.contains(pat, regex=True).astype(np.int8)
    df["kw_total"] = df[list(KEYWORDS.keys())].sum(axis=1)

    return df


def main() -> None:
    t0 = time.time()
    print("=" * 70)
    print("SOLACE TRIAGE — STACKED ENSEMBLE TRAINING")
    print("=" * 70)

    # ── 1. Load data ──────────────────────────────────────────────────────
    print("\n[1/8] Loading data")
    df = load()
    print(f"       rows={len(df):,}  cols={df.shape[1]}")

    # ── 2. Carve calibration set ──────────────────────────────────────────
    print("[2/8] Carving calibration set (10%)")
    train_idx, cal_idx = train_test_split(
        np.arange(len(df)), test_size=0.10, random_state=SEED, stratify=df[TARGET].values
    )
    train_main = df.iloc[train_idx].reset_index(drop=True)
    cal_set = df.iloc[cal_idx].reset_index(drop=True)

    # ── 3. Feature engineering ────────────────────────────────────────────
    print("[3/8] Clinical feature engineering")
    train_main = clinical_features(train_main)
    cal_set = clinical_features(cal_set)

    # ── 4. Imputation + encoding + TF-IDF ─────────────────────────────────
    print("[4/8] Imputation + label encoding + TF-IDF")
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
        max_features=500, ngram_range=(1, 3), analyzer="word",
        min_df=3, max_df=0.95, sublinear_tf=True,
    )
    tw = tfidf_word.fit_transform(cc_train)
    tw_cal = tfidf_word.transform(cc_cal)

    tfidf_char = TfidfVectorizer(
        max_features=200, ngram_range=(2, 5), analyzer="char_wb",
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
    struct_cols = [
        c for c in train_main.columns
        if c not in DROP and c not in tfidf_names
        and pd.api.types.is_numeric_dtype(train_main[c])
    ]

    X_train = pd.concat([train_main[struct_cols].astype(np.float32), train_tfidf], axis=1)
    X_cal = pd.concat([cal_set[struct_cols].astype(np.float32), cal_tfidf], axis=1)

    final_medians = {}
    for c in X_train.columns:
        if X_train[c].isnull().any():
            m = X_train[c].median()
            final_medians[c] = m
            X_train[c] = X_train[c].fillna(m)
            X_cal[c] = X_cal[c].fillna(m)

    y_train = train_main[TARGET].values
    y_cal = cal_set[TARGET].values
    feature_names = list(X_train.columns)
    print(f"       features={len(feature_names)}  train={len(X_train):,}  cal={len(X_cal):,}")

    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)

    # ── 5. Train all 4 base models ───────────────────────────────────────
    print("\n[5/8] Training base models (4 x 5-fold)")

    # --- LightGBM (Optuna-tuned hyperparams from notebook) ---
    print("\n  ─── LightGBM ───")
    lgb_params = {
        "objective": "multiclass", "num_class": 5, "metric": "multi_logloss",
        "verbosity": -1, "n_jobs": -1, "random_state": SEED,
        "class_weight": "balanced",
        "learning_rate": 0.0143, "num_leaves": 219, "max_depth": 8,
        "min_child_samples": 42, "subsample": 0.663, "colsample_bytree": 0.546,
        "reg_alpha": 0.00175, "reg_lambda": 0.131, "min_split_gain": 0.168,
    }
    oof_lgb = np.zeros((len(X_train), 5), dtype=np.float32)
    lgb_models = []
    lgb_folds = []
    for fold, (tr_idx, va_idx) in enumerate(skf.split(X_train, y_train)):
        ds_tr = lgb.Dataset(X_train.iloc[tr_idx], label=y_train[tr_idx] - 1)
        ds_va = lgb.Dataset(X_train.iloc[va_idx], label=y_train[va_idx] - 1, reference=ds_tr)
        m = lgb.train(
            lgb_params, ds_tr, num_boost_round=1500, valid_sets=[ds_va],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(500)],
        )
        p = m.predict(X_train.iloc[va_idx], num_iteration=m.best_iteration)
        oof_lgb[va_idx] = p
        q = cohen_kappa_score(y_train[va_idx], p.argmax(1) + 1, weights="quadratic")
        lgb_folds.append(q)
        lgb_models.append(m)
        print(f"    Fold {fold+1}: QWK={q:.4f} (iter {m.best_iteration})")
    lgb_qwk = cohen_kappa_score(y_train, oof_lgb.argmax(1) + 1, weights="quadratic")
    print(f"  LightGBM OOF QWK: {lgb_qwk:.4f}")

    # --- XGBoost (Optuna-tuned) ---
    print("\n  ─── XGBoost ───")
    xgb_params = {
        "objective": "multi:softprob", "num_class": 5, "eval_metric": "mlogloss",
        "verbosity": 0, "nthread": -1, "random_state": SEED,
        "tree_method": "hist",
        "learning_rate": 0.0401, "max_depth": 10, "min_child_weight": 11,
        "subsample": 0.714, "colsample_bytree": 0.734,
        "reg_alpha": 1.115, "reg_lambda": 4.903, "gamma": 1.965,
    }
    oof_xgb = np.zeros((len(X_train), 5), dtype=np.float32)
    xgb_models = []
    xgb_folds = []
    for fold, (tr_idx, va_idx) in enumerate(skf.split(X_train, y_train)):
        sw = compute_sample_weight(class_weight="balanced", y=y_train[tr_idx])
        dm_tr = xgb.DMatrix(X_train.iloc[tr_idx], label=y_train[tr_idx] - 1, weight=sw)
        dm_va = xgb.DMatrix(X_train.iloc[va_idx], label=y_train[va_idx] - 1)
        m = xgb.train(
            xgb_params, dm_tr, num_boost_round=1500,
            evals=[(dm_va, "val")], early_stopping_rounds=50, verbose_eval=False,
        )
        p = m.predict(dm_va).reshape(-1, 5)
        oof_xgb[va_idx] = p
        q = cohen_kappa_score(y_train[va_idx], p.argmax(1) + 1, weights="quadratic")
        xgb_folds.append(q)
        xgb_models.append(m)
        print(f"    Fold {fold+1}: QWK={q:.4f}")
    xgb_qwk = cohen_kappa_score(y_train, oof_xgb.argmax(1) + 1, weights="quadratic")
    print(f"  XGBoost OOF QWK: {xgb_qwk:.4f}")

    # --- CatBoost (Optuna-tuned) ---
    print("\n  ─── CatBoost ───")
    cat_params = {
        "loss_function": "MultiClass", "classes_count": 5, "eval_metric": "MultiClass",
        "random_seed": SEED, "verbose": 200, "iterations": 1500,
        "task_type": "CPU",
        "auto_class_weights": "Balanced", "early_stopping_rounds": 50,
        "learning_rate": 0.0384, "depth": 8, "l2_leaf_reg": 2.308,
        "bagging_temperature": 0.037, "random_strength": 9.622, "border_count": 168,
    }
    oof_cat = np.zeros((len(X_train), 5), dtype=np.float32)
    cat_models = []
    cat_folds = []
    for fold, (tr_idx, va_idx) in enumerate(skf.split(X_train, y_train)):
        m = CatBoostClassifier(**cat_params)
        m.fit(X_train.iloc[tr_idx], y_train[tr_idx] - 1,
              eval_set=(X_train.iloc[va_idx], y_train[va_idx] - 1))
        p = m.predict_proba(X_train.iloc[va_idx])
        oof_cat[va_idx] = p
        q = cohen_kappa_score(y_train[va_idx], p.argmax(1) + 1, weights="quadratic")
        cat_folds.append(q)
        cat_models.append(m)
        print(f"    Fold {fold+1}: QWK={q:.4f}")
    cat_qwk = cohen_kappa_score(y_train, oof_cat.argmax(1) + 1, weights="quadratic")
    print(f"  CatBoost OOF QWK: {cat_qwk:.4f}")

    # --- MLP Neural Network ---
    print("\n  ─── MLP (256→128→64) ───")
    oof_mlp = np.zeros((len(X_train), 5), dtype=np.float32)
    mlp_models = []
    mlp_scalers = []
    mlp_folds = []
    for fold, (tr_idx, va_idx) in enumerate(skf.split(X_train, y_train)):
        scaler = StandardScaler()
        Xtr = scaler.fit_transform(X_train.iloc[tr_idx].fillna(0))
        Xva = scaler.transform(X_train.iloc[va_idx].fillna(0))

        sw = compute_sample_weight(class_weight="balanced", y=y_train[tr_idx])
        rng_mlp = np.random.default_rng(SEED + fold)
        keep = rng_mlp.random(len(sw)) < (sw / sw.max())
        Xtr_b = Xtr[keep]
        ytr_b = y_train[tr_idx][keep] - 1

        m = MLPClassifier(
            hidden_layer_sizes=(256, 128, 64), activation="relu", solver="adam",
            alpha=1e-3, batch_size=2048, max_iter=100, early_stopping=True,
            validation_fraction=0.1, n_iter_no_change=10, random_state=SEED, verbose=False,
        )
        m.fit(Xtr_b, ytr_b)
        p = m.predict_proba(Xva)
        oof_mlp[va_idx] = p
        q = cohen_kappa_score(y_train[va_idx], p.argmax(1) + 1, weights="quadratic")
        mlp_folds.append(q)
        mlp_models.append(m)
        mlp_scalers.append(scaler)
        print(f"    Fold {fold+1}: QWK={q:.4f} (iters: {m.n_iter_})")
    mlp_qwk = cohen_kappa_score(y_train, oof_mlp.argmax(1) + 1, weights="quadratic")
    print(f"  MLP OOF QWK: {mlp_qwk:.4f}")

    # ── 6. Meta-learner stacking ─────────────────────────────────────────
    print("\n[6/8] Meta-learner stacking + threshold optimization")

    # Weighted average (QWK-proportional)
    tw_sum = lgb_qwk + xgb_qwk + cat_qwk + mlp_qwk
    weights = [lgb_qwk / tw_sum, xgb_qwk / tw_sum, cat_qwk / tw_sum, mlp_qwk / tw_sum]
    oof_wavg = weights[0] * oof_lgb + weights[1] * oof_xgb + weights[2] * oof_cat + weights[3] * oof_mlp
    wavg_qwk = cohen_kappa_score(y_train, oof_wavg.argmax(1) + 1, weights="quadratic")
    print(f"  Weighted Average QWK: {wavg_qwk:.4f}")
    print(f"  Weights: LGB={weights[0]:.3f} XGB={weights[1]:.3f} CAT={weights[2]:.3f} MLP={weights[3]:.3f}")

    # Stacked meta-learner (L1-regularized logistic regression)
    oof_meta = np.hstack([oof_lgb, oof_xgb, oof_cat, oof_mlp])
    print(f"  Meta-features: {oof_meta.shape[1]} (5 classes x 4 models)")

    best_C, best_q = 1.0, -1
    for C in [0.01, 0.1, 0.5, 1.0, 5.0, 10.0]:
        tmp = np.zeros((len(oof_meta), 5))
        for tr_idx, va_idx in skf.split(oof_meta, y_train):
            lr = LogisticRegression(C=C, penalty="l1", max_iter=2000, solver="saga", random_state=SEED)
            lr.fit(oof_meta[tr_idx], y_train[tr_idx])
            tmp[va_idx] = lr.predict_proba(oof_meta[va_idx])
        q = cohen_kappa_score(y_train, tmp.argmax(1) + 1, weights="quadratic")
        if q > best_q:
            best_q, best_C = q, C
    print(f"  Best meta-learner C={best_C} (CV QWK={best_q:.4f})")

    # Train final meta-learner on full OOF predictions
    meta_learner = LogisticRegression(C=best_C, penalty="l1", max_iter=2000, solver="saga", random_state=SEED)
    meta_learner.fit(oof_meta, y_train)

    oof_stack = meta_learner.predict_proba(oof_meta)
    stack_qwk = cohen_kappa_score(y_train, oof_stack.argmax(1) + 1, weights="quadratic")
    print(f"  Stacked QWK: {stack_qwk:.4f}")

    # Pick best ensemble
    if stack_qwk >= wavg_qwk:
        oof_final = oof_stack
        method = "Stacked Meta-Learner"
        final_qwk_raw = stack_qwk
    else:
        oof_final = oof_wavg
        method = "Weighted Average"
        final_qwk_raw = wavg_qwk
        meta_learner = None

    # Threshold optimization on ordinal expected values
    def qwk_thresh(thresholds, probs, y_true):
        ev = probs @ np.arange(1, 6)
        preds = np.digitize(ev, sorted(thresholds)) + 1
        return -cohen_kappa_score(y_true, preds, weights="quadratic")

    print("  Running threshold optimization (DE + Nelder-Mead)...")
    res_de = differential_evolution(
        qwk_thresh, [(1, 5)] * 4, args=(oof_final, y_train),
        seed=SEED, maxiter=100, tol=1e-7,
    )
    res_nm = minimize(
        qwk_thresh, x0=[1.5, 2.5, 3.5, 4.5], args=(oof_final, y_train),
        method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-9, "maxiter": 2000},
    )
    de_q, nm_q = -res_de.fun, -res_nm.fun
    res = res_nm if nm_q > de_q else res_de
    thresh_qwk = -res.fun
    print(f"  Threshold opt — DE: {de_q:.6f} | Nelder-Mead: {nm_q:.6f}")

    opt_thresholds = None
    if thresh_qwk > final_qwk_raw:
        opt_thresholds = sorted(res.x.tolist())
        final_preds = np.digitize(oof_final @ np.arange(1, 6), opt_thresholds) + 1
        final_qwk = thresh_qwk
        method += " + Threshold Opt"
        print(f"  Threshold opt improved: {final_qwk_raw:.4f} → {thresh_qwk:.4f}")
    else:
        final_preds = oof_final.argmax(1) + 1
        final_qwk = final_qwk_raw
        print(f"  Threshold opt did not improve; using argmax.")

    final_acc = accuracy_score(y_train, final_preds)
    print(f"\n  FINAL: {method}")
    print(f"    QWK:      {final_qwk:.4f}")
    print(f"    Accuracy: {final_acc:.4f}")

    # ── 7. Conformal calibration ──────────────────────────────────────────
    print("\n[7/8] Conformal calibration on held-out cal set")

    # Get cal set predictions from all 4 models
    cal_lgb = np.mean([m.predict(X_cal, num_iteration=m.best_iteration) for m in lgb_models], axis=0)
    cal_xgb = np.mean([m.predict(xgb.DMatrix(X_cal)).reshape(-1, 5) for m in xgb_models], axis=0)
    cal_cat = np.mean([m.predict_proba(X_cal) for m in cat_models], axis=0)
    cal_mlp = np.zeros((len(X_cal), 5), dtype=np.float32)
    for m, sc in zip(mlp_models, mlp_scalers):
        cal_mlp += m.predict_proba(sc.transform(X_cal.fillna(0))) / N_FOLDS

    if meta_learner is not None:
        cal_meta = np.hstack([cal_lgb, cal_xgb, cal_cat, cal_mlp])
        cal_final = meta_learner.predict_proba(cal_meta)
    else:
        cal_final = weights[0] * cal_lgb + weights[1] * cal_xgb + weights[2] * cal_cat + weights[3] * cal_mlp

    alpha = 0.10
    cal_scores = 1 - cal_final[np.arange(len(y_cal)), y_cal - 1]
    q_hat = float(np.quantile(cal_scores, np.ceil((len(cal_scores) + 1) * (1 - alpha)) / len(cal_scores)))
    print(f"  Clean q̂={q_hat:.4f} (alpha={alpha})")

    # Noise-perturbed calibration
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

    cal_lgb_n = np.mean([m.predict(X_cal_noisy, num_iteration=m.best_iteration) for m in lgb_models], axis=0)
    cal_xgb_n = np.mean([m.predict(xgb.DMatrix(X_cal_noisy)).reshape(-1, 5) for m in xgb_models], axis=0)
    cal_cat_n = np.mean([m.predict_proba(X_cal_noisy) for m in cat_models], axis=0)
    cal_mlp_n = np.zeros((len(X_cal_noisy), 5), dtype=np.float32)
    for m, sc in zip(mlp_models, mlp_scalers):
        cal_mlp_n += m.predict_proba(sc.transform(X_cal_noisy.fillna(0))) / N_FOLDS

    if meta_learner is not None:
        cal_meta_n = np.hstack([cal_lgb_n, cal_xgb_n, cal_cat_n, cal_mlp_n])
        cal_final_n = meta_learner.predict_proba(cal_meta_n)
    else:
        cal_final_n = weights[0] * cal_lgb_n + weights[1] * cal_xgb_n + weights[2] * cal_cat_n + weights[3] * cal_mlp_n

    cal_scores_n = 1 - cal_final_n[np.arange(len(y_cal)), y_cal - 1]
    q_hat_noisy = float(np.quantile(cal_scores_n, np.ceil((len(cal_scores_n) + 1) * (1 - alpha)) / len(cal_scores_n)))
    print(f"  Noise-perturbed q̂={q_hat_noisy:.4f}")

    # ── 8. Save artifacts ─────────────────────────────────────────────────
    print("\n[8/8] Saving artifacts →", OUT)

    # LightGBM fold models
    for i, m in enumerate(lgb_models):
        m.save_model(str(OUT / f"lgbm_fold{i}.txt"))

    # XGBoost fold models
    for i, m in enumerate(xgb_models):
        m.save_model(str(OUT / f"xgb_fold{i}.txt"))

    # CatBoost fold models
    for i, m in enumerate(cat_models):
        m.save_model(str(OUT / f"cat_fold{i}.txt"))

    # Modal defaults
    modal_defaults: dict[str, str] = {}
    for col in CAT_COLS:
        if col in train_main.columns:
            modal_defaults[col] = str(train_main[col].mode().iloc[0])

    # Main artifact pickle (includes MLP models, scalers, meta-learner, thresholds)
    with (OUT / "artifacts.pkl").open("wb") as f:
        pickle.dump({
            # TF-IDF
            "tfidf_word": tfidf_word,
            "tfidf_char": tfidf_char,
            "tfidf_names": tfidf_names,
            # Encoders
            "label_encoders": label_encoders,
            "imputation_medians": {**medians, **final_medians},
            "modal_defaults": modal_defaults,
            # Feature schema
            "feature_names": feature_names,
            "struct_cols": struct_cols,
            "keywords": KEYWORDS,
            "cat_cols": CAT_COLS,
            "impute_cols": IMPUTE_COLS,
            # Fold count
            "n_folds": N_FOLDS,
            # MLP models + scalers (stored in pickle since sklearn objects)
            "mlp_models": mlp_models,
            "mlp_scalers": mlp_scalers,
            # Meta-learner
            "meta_learner": meta_learner,
            # Ensemble weights (QWK-proportional)
            "ensemble_weights": weights,
            # Threshold optimization
            "opt_thresholds": opt_thresholds,
            # Conformal
            "conformal_q_hat": float(q_hat),
            "conformal_q_hat_noisy": float(q_hat_noisy),
            # Metrics
            "oof_qwk": float(final_qwk),
            "oof_accuracy": float(final_acc),
            "lgb_qwk": float(lgb_qwk),
            "xgb_qwk": float(xgb_qwk),
            "cat_qwk": float(cat_qwk),
            "mlp_qwk": float(mlp_qwk),
            "method": method,
            # Metadata
            "dataset": "Kaggle Triagegeist (80k synthetic ED encounters)",
        }, f)

    total_mb = sum(p.stat().st_size for p in OUT.iterdir() if not p.name.startswith(".")) / 1e6
    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"DONE — artifacts size: {total_mb:.1f} MB | elapsed: {elapsed:.0f}s")
    print(f"  LGB={lgb_qwk:.4f}  XGB={xgb_qwk:.4f}  CAT={cat_qwk:.4f}  MLP={mlp_qwk:.4f}")
    print(f"  Weighted Avg={wavg_qwk:.4f}  Stacked={stack_qwk:.4f}")
    print(f"  Final ({method}): QWK={final_qwk:.4f}  Acc={final_acc:.4f}")
    print(f"  Conformal q̂ (noisy): {q_hat_noisy:.4f}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
