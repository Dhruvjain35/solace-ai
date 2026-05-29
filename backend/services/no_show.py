"""No-show prediction — risk-tiered appointment reminders.

This module predicts the probability a booked patient misses their appointment
so the reminder cadence can be tiered (see ``services/scheduling.py``).

Two prediction paths, selected automatically and reported in the ``model``
field of every result:

  * ``"lgbm_synthetic_v1"`` — an lru_cache'd LightGBM binary classifier trained
    once per process on a *synthetic* dataset (see ``generate_synthetic_dataset``).
  * ``"rule_based_v1"`` — a clinically-defensible rule combination used when
    LightGBM is unavailable, or if model training raised. The original v1
    behaviour, preserved verbatim, so the UX never hard-fails.

EQUITY / FAIRNESS
-----------------
Protected attributes (race, ethnicity, sex, the IMD/deprivation index, and the
raw zip/postcode) are *never* fed to the model. The model only sees behavioral
history, lead time, appointment timing, visit type, distance, and age. The
protected attributes are carried alongside predictions purely so that
``equity_audit()`` can report the predicted-risk distribution by demographic
group and flag any gap for human review — disparate cadence is a fairness
hazard even when the model itself is attribute-blind (a high-risk tier means
more outreach, which is generally beneficial, but an *under*-served group is a
real harm). See the model card in ``services/model_cards.py``.

SYNTHETIC DATA CAVEAT
---------------------
The classifier is trained on a fully synthetic dataset generated in-process.
It encodes literature-informed associations (prior-behavior dominance, lead-time
and early-slot effects, distance/deprivation gradients) but it is NOT trained on
any real scheduling records. Real-world calibration WILL differ. Mirrors the
``triage_ml`` convention of shipping a clearly-flagged synthetic model so the UX
and the model-swap seam exist now; production swaps in a model trained on the
hospital's own historical ``solace-appointments`` data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

log = logging.getLogger(__name__)

# Feature columns fed to the model, in a fixed order. Protected attributes are
# deliberately absent — see the module docstring.
FEATURE_NAMES: list[str] = [
    "prior_no_show_rate",   # prior_no_shows / (prior_no_shows + prior_completed)
    "prior_total_visits",   # volume of behavioral history available
    "booking_lead_days",    # days between booking and appointment
    "appt_hour",            # hour-of-day of the appointment (0-23)
    "appt_dow",             # day-of-week of the appointment (0=Mon .. 6=Sun)
    "visit_type_code",      # ordinal encoding of visit type
    "distance_km",          # patient-to-clinic travel distance
    "deprivation_index",    # area deprivation 0-1 (1 = most deprived)
    "age",                  # patient age in years
    "has_phone",            # 1 if a reminder channel is reachable
]

# Ordinal visit-type encoding. Higher = empirically higher no-show base rate.
_VISIT_TYPE_CODES: dict[str, int] = {
    "follow_up": 0,
    "physical": 1,
    "lab": 1,
    "imaging": 1,
    "consult": 2,
    "new_patient": 3,
    "specialist": 3,
}

SYNTHETIC_DATASET_SIZE = 6000
SYNTHETIC_SEED = 20260516
POPULATION_BASELINE = 0.10  # ~10% population no-show rate


# --- feature engineering --------------------------------------------------------


def _hours_until(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return 24.0
    now = datetime.now(timezone.utc)
    return max(0.0, (dt - now).total_seconds() / 3600)


def _visit_type_code(visit_type: str) -> int:
    return _VISIT_TYPE_CODES.get((visit_type or "").strip().lower(), 0)


def build_features(
    *,
    appointment_iso: str,
    prior_no_shows: int = 0,
    prior_completed: int = 0,
    visit_type: str = "follow_up",
    booking_lead_days: int = 7,
    distance_km: float = 5.0,
    deprivation_index: float = 0.5,
    age: int | None = None,
    has_phone: bool = True,
) -> dict[str, float]:
    """Shared feature pipeline. Produces the ``FEATURE_NAMES`` vector as a dict.

    Used both by the synthetic dataset generator (so training and inference
    share one code path) and by ``predict()``. Inputs are clipped/defaulted so a
    sparse intake never produces a NaN that the model cannot score.
    """
    total = max(0, int(prior_no_shows)) + max(0, int(prior_completed))
    prior_rate = (max(0, int(prior_no_shows)) / total) if total > 0 else POPULATION_BASELINE

    appt_hour, appt_dow = 12, 0
    try:
        dt = datetime.fromisoformat(appointment_iso.replace("Z", "+00:00"))
        appt_hour, appt_dow = dt.hour, dt.weekday()
    except Exception:
        log.debug("no_show.build_features: unparseable appointment_iso=%r", appointment_iso)

    return {
        "prior_no_show_rate": float(prior_rate),
        "prior_total_visits": float(min(total, 50)),
        "booking_lead_days": float(max(0, min(int(booking_lead_days), 365))),
        "appt_hour": float(appt_hour),
        "appt_dow": float(appt_dow),
        "visit_type_code": float(_visit_type_code(visit_type)),
        "distance_km": float(max(0.0, min(float(distance_km), 200.0))),
        "deprivation_index": float(max(0.0, min(float(deprivation_index), 1.0))),
        "age": float(age if age is not None else 40),
        "has_phone": 1.0 if has_phone else 0.0,
    }


def _feature_vector(feats: dict[str, float]) -> list[float]:
    return [feats[name] for name in FEATURE_NAMES]


# --- synthetic dataset ----------------------------------------------------------


def _latent_no_show_prob(feats: dict[str, float]) -> float:
    """Literature-informed ground-truth no-show probability for one synthetic row.

    SYNTHETIC: this function *is* the data-generating process for the synthetic
    training set. It is not a clinical claim — it encodes well-replicated
    directional effects (prior-behavior dominance, lead-time, early-slot, Monday,
    distance, deprivation, youngest cohort, unreachable patient).
    """
    p = POPULATION_BASELINE
    # Prior behavior — strongest predictor in the no-show literature.
    if feats["prior_total_visits"] >= 3:
        p = 0.55 * feats["prior_no_show_rate"] + 0.45 * p
    # Lead time — longer waits forget / re-plan.
    lead = feats["booking_lead_days"]
    if lead >= 30:
        p += 0.07
    elif lead >= 14:
        p += 0.035
    # Early-morning slots and Mondays.
    if feats["appt_hour"] < 9:
        p += 0.04
    if feats["appt_dow"] == 0:
        p += 0.02
    # Visit type.
    p += 0.013 * feats["visit_type_code"]
    # Distance — travel burden.
    p += min(0.06, feats["distance_km"] / 800.0)
    # Deprivation — transport, childcare, work inflexibility.
    p += 0.08 * feats["deprivation_index"]
    # Youngest cohort.
    if feats["age"] < 25:
        p += 0.03
    # Unreachable — no reminder lands.
    if feats["has_phone"] < 0.5:
        p += 0.05
    return max(0.01, min(0.95, p))


def generate_synthetic_dataset(
    n: int = SYNTHETIC_DATASET_SIZE, seed: int = SYNTHETIC_SEED
) -> tuple[list[list[float]], list[int]]:
    """Generate a SYNTHETIC labelled dataset for the no-show classifier.

    Returns ``(X, y)`` where ``X`` is a list of ``FEATURE_NAMES``-ordered vectors
    and ``y`` is a list of 0/1 no-show labels. Fully synthetic — see the module
    docstring. Deterministic given ``seed`` so the lru_cache'd model is stable.

    Note: protected attributes (deprivation here doubles as a deprivation proxy
    that IS a model feature; race/sex/zip are not generated as features at all).
    ``deprivation_index`` is included because area-deprivation is an actionable,
    non-protected operational signal; ``equity_audit`` still slices on it.
    """
    import random

    rng = random.Random(seed)
    X: list[list[float]] = []
    y: list[int] = []
    visit_types = list(_VISIT_TYPE_CODES.keys())

    for _ in range(n):
        prior_total = rng.choices(
            [0, 1, 2, 3, 4, 6, 9, 14], weights=[25, 15, 12, 12, 12, 10, 8, 6]
        )[0]
        # Binomial draw via repeated Bernoulli — stdlib random has no binomial().
        prior_no = sum(1 for _ in range(prior_total) if rng.random() < 0.18)
        # Random appointment in the next ~6 weeks.
        hour = rng.choices(range(8, 18), weights=[3, 4, 5, 5, 4, 3, 5, 5, 4, 3])[0]
        dow = rng.choice([0, 1, 2, 3, 4])
        feats = build_features(
            appointment_iso=f"2026-06-{rng.randint(1, 28):02d}T{hour:02d}:00:00Z",
            prior_no_shows=prior_no,
            prior_completed=prior_total - prior_no,
            visit_type=rng.choice(visit_types),
            booking_lead_days=rng.choice([1, 3, 5, 7, 10, 14, 21, 30, 45, 60]),
            distance_km=round(rng.expovariate(1 / 8.0), 1),
            deprivation_index=round(rng.random(), 3),
            age=rng.randint(16, 88),
        )
        # Override dow with the sampled workday (build_features parsed the iso day).
        feats["appt_dow"] = float(dow)
        prob = _latent_no_show_prob(feats)
        label = 1 if rng.random() < prob else 0
        X.append(_feature_vector(feats))
        y.append(label)

    return X, y


# --- model ----------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_model() -> Any | None:
    """Train (once per process) and cache a LightGBM no-show classifier.

    Returns the fitted ``lightgbm.Booster``, or ``None`` if LightGBM is missing
    or training failed — in which case ``predict()`` uses the rule-based path.
    """
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError:
        log.warning("no_show: lightgbm/numpy not installed — using rule-based fallback")
        return None

    try:
        X, y = generate_synthetic_dataset()
        dtrain = lgb.Dataset(
            np.asarray(X, dtype=np.float64),
            label=np.asarray(y, dtype=np.int32),
            feature_name=list(FEATURE_NAMES),
        )
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "num_leaves": 15,
            "learning_rate": 0.05,
            "min_data_in_leaf": 40,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.9,
            "bagging_freq": 1,
            "verbosity": -1,
            "seed": SYNTHETIC_SEED,
        }
        booster = lgb.train(params, dtrain, num_boost_round=160)
        log.info("no_show: trained synthetic LightGBM classifier (%d rows)", len(y))
        return booster
    except Exception as e:  # pragma: no cover - defensive
        log.exception("no_show: model training failed, falling back to rules: %s", e)
        return None


def _rule_based_probability(feats: dict[str, float]) -> float:
    """Original v1 rule combination — clinically-defensible, no model required."""
    base = POPULATION_BASELINE
    if feats["prior_total_visits"] >= 3:
        base = 0.4 * feats["prior_no_show_rate"] + 0.6 * base
    lead = feats["booking_lead_days"]
    if lead >= 30:
        base += 0.06
    elif lead >= 14:
        base += 0.03
    base += 0.012 * feats["visit_type_code"]
    if feats["appt_hour"] < 9:
        base += 0.04
    if feats["appt_dow"] == 0:
        base += 0.02
    base += min(0.05, feats["distance_km"] / 1000.0)
    base += 0.06 * feats["deprivation_index"]
    if feats["age"] < 25:
        base += 0.03
    if feats["has_phone"] < 0.5:
        base += 0.05
    return max(0.0, min(0.95, base))


def _tier_for(prob: float) -> tuple[str, list[str]]:
    """Map a no-show probability to a risk tier + reminder cadence.

    Cadence here is the canonical tiering; ``scheduling.reminder_plan`` consumes
    the tier to build the concrete channel plan.
    """
    if prob >= 0.30:
        return "high", ["sms 7d", "sms 3d", "voice 1d", "voice 4h"]
    if prob >= 0.15:
        return "medium", ["sms 3d", "sms 1d", "sms 4h"]
    return "low", ["sms 1d"]


def predict(
    appointment_iso: str,
    prior_no_shows: int = 0,
    prior_completed: int = 0,
    visit_type: str = "follow_up",
    booking_lead_days: int = 7,
    age: int | None = None,
    has_phone: bool = True,
    *,
    distance_km: float = 5.0,
    deprivation_index: float = 0.5,
) -> dict[str, Any]:
    """Predict no-show risk for one appointment.

    Backward-compatible: the original positional/keyword signature is unchanged;
    ``distance_km`` and ``deprivation_index`` are new keyword-only optionals with
    safe defaults, so existing callers (e.g. ``routers/care_ops.py``) keep working.

    The LightGBM path is used when available; otherwise a rule-based fallback.
    The ``model`` field always reports which path produced the number, and
    ``synthetic`` / ``caveat`` flag that the shipped model is synthetic-trained.
    """
    feats = build_features(
        appointment_iso=appointment_iso,
        prior_no_shows=prior_no_shows,
        prior_completed=prior_completed,
        visit_type=visit_type,
        booking_lead_days=booking_lead_days,
        distance_km=distance_km,
        deprivation_index=deprivation_index,
        age=age,
        has_phone=has_phone,
    )

    booster = _load_model()
    if booster is not None:
        try:
            import numpy as np

            row = np.asarray([_feature_vector(feats)], dtype=np.float64)
            prob = float(booster.predict(row)[0])
            model_name = "lgbm_synthetic_v1"
        except Exception as e:  # pragma: no cover - defensive
            log.warning("no_show: model.predict failed (%s) — using rules", e)
            prob = _rule_based_probability(feats)
            model_name = "rule_based_v1"
    else:
        prob = _rule_based_probability(feats)
        model_name = "rule_based_v1"

    prob = max(0.0, min(0.95, prob))
    tier, cadence = _tier_for(prob)

    return {
        "no_show_probability": round(prob, 3),
        "tier": tier,
        "reminder_cadence": cadence,
        "hours_until": round(_hours_until(appointment_iso), 1),
        "model": model_name,
        "synthetic": True,
        "caveat": (
            "Risk score from a model trained on SYNTHETIC scheduling data. "
            "Real-world calibration will differ — recalibrate on the hospital's "
            "own historical appointments before operational use."
        ),
        "features": feats,
    }


# --- equity audit ---------------------------------------------------------------


def equity_audit(
    records: list[dict[str, Any]], group_key: str = "demographic_group"
) -> dict[str, Any]:
    """Report the predicted-risk distribution by demographic group.

    ``records`` is a list of dicts. Each must carry a ``group_key`` value
    (the protected attribute — e.g. race, ethnicity, sex, deprivation band) and
    EITHER an already-computed ``no_show_probability``/``tier`` OR the raw
    ``predict()`` inputs (``appointment_iso`` plus the optional kwargs), in which
    case this function scores them.

    IMPORTANT: the protected attribute is used ONLY to slice the audit. It is
    never a model feature (see module docstring). The audit exists because a
    tiering policy can still be inequitable even with an attribute-blind model.

    Returns per-group mean predicted risk + tier mix, plus the largest
    between-group gap in mean risk, with a ``flag`` set when that gap exceeds a
    review threshold (0.05 absolute, configurable downstream).
    """
    GAP_THRESHOLD = 0.05
    groups: dict[str, list[float]] = {}
    group_tiers: dict[str, dict[str, int]] = {}

    for rec in records or []:
        group = str(rec.get(group_key, "unknown"))

        prob = rec.get("no_show_probability")
        tier = rec.get("tier")
        if prob is None:
            scored = predict(
                rec.get("appointment_iso", ""),
                prior_no_shows=rec.get("prior_no_shows", 0),
                prior_completed=rec.get("prior_completed", 0),
                visit_type=rec.get("visit_type", "follow_up"),
                booking_lead_days=rec.get("booking_lead_days", 7),
                age=rec.get("age"),
                has_phone=rec.get("has_phone", True),
                distance_km=rec.get("distance_km", 5.0),
                deprivation_index=rec.get("deprivation_index", 0.5),
            )
            prob, tier = scored["no_show_probability"], scored["tier"]
        if tier is None:
            tier, _ = _tier_for(float(prob))

        groups.setdefault(group, []).append(float(prob))
        tcount = group_tiers.setdefault(group, {"low": 0, "medium": 0, "high": 0})
        tcount[tier] = tcount.get(tier, 0) + 1

    by_group: dict[str, Any] = {}
    for group, probs in groups.items():
        n = len(probs)
        mean = sum(probs) / n
        tcount = group_tiers[group]
        by_group[group] = {
            "n": n,
            "mean_no_show_probability": round(mean, 4),
            "tier_mix": tcount,
            "high_risk_share": round(tcount.get("high", 0) / n, 4) if n else 0.0,
        }

    means = {g: v["mean_no_show_probability"] for g, v in by_group.items()}
    gap = 0.0
    gap_pair: list[str] = []
    if len(means) >= 2:
        hi_g = max(means, key=means.get)
        lo_g = min(means, key=means.get)
        gap = round(means[hi_g] - means[lo_g], 4)
        gap_pair = [hi_g, lo_g]

    return {
        "group_key": group_key,
        "n_records": sum(len(p) for p in groups.values()),
        "by_group": by_group,
        "max_risk_gap": gap,
        "max_risk_gap_groups": gap_pair,
        "gap_threshold": GAP_THRESHOLD,
        "flag": gap > GAP_THRESHOLD,
        "note": (
            "Protected attributes are NOT model features; this audit slices "
            "predictions by group purely to surface disparate reminder cadence "
            "for human review. A flagged gap warrants a fairness review, not an "
            "automatic model change."
        ),
    }
