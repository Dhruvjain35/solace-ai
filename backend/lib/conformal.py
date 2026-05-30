"""Class-conditional (Mondrian) split-conformal prediction for the ESI ensemble.

The triage ensemble emits a 5-way softmax over ESI levels. A *global* split-
conformal calibration (one q̂ for all classes) is fragile here: on the clean,
templated synthetic training distribution the model is text-dominant and almost
never wrong, so the global nonconformity quantile collapses to q̂ ≈ 1e-4 and the
90% prediction set degenerates to a singleton for every patient — a false sense
of certainty.

This module implements **Mondrian (class-conditional) conformal prediction**
(Vovk 2003; Angelopoulos & Bates 2021, §4.1): the calibration set is partitioned
by the *true* label and a separate q̂ is computed per ESI class. Each class then
gets the marginal-coverage guarantee on its own conditional distribution, so a
class the model handles poorly keeps a wide set even if the global error rate is
tiny. An optional **importance-weighted** variant (Tibshirani et al. 2019) lets
callers up-weight calibration points that resemble the deployment distribution —
the hook real labeled outcomes will use once they land.

Everything here is pure numpy (no sklearn / lightgbm import), so the math is unit
-testable in isolation and adds no Lambda-image dependency beyond DEPS-004's
numpy/scipy floor.

Nonconformity score: ``s = 1 - p(true_label)`` (the standard softmax score used
elsewhere in the codebase). A label y is admitted into the prediction set for a
new point with softmax ``p`` iff ``1 - p[y] <= q̂[y]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# ESI is 1..5; index 0..4 internally.
N_ESI = 5
DEFAULT_ALPHA = 0.10  # 90% target coverage


def nonconformity(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Softmax nonconformity ``1 - p(true)`` for a calibration batch.

    ``probs`` is (n, n_classes), ``labels`` is (n,) of 0-based class indices.
    """
    probs = np.asarray(probs, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if probs.ndim != 2:
        raise ValueError("probs must be 2-D (n_samples, n_classes)")
    if labels.shape[0] != probs.shape[0]:
        raise ValueError("probs and labels length mismatch")
    rows = np.arange(probs.shape[0])
    return 1.0 - probs[rows, labels]


def _conformal_quantile(
    scores: np.ndarray, alpha: float, weights: np.ndarray | None = None
) -> float:
    """The finite-sample-corrected conformal quantile of a score set.

    Unweighted: the ``ceil((n+1)(1-alpha)) / n`` empirical quantile (Angelopoulos
    & Bates eq. 3.2) — the +1 is the conformal small-sample correction.

    Weighted (Tibshirani et al. 2019): the smallest score s such that the
    normalized weight mass at or below s reaches ``1 - alpha``, with the new test
    point's weight folded in as the conventional ``+1`` mass. Falls back to the
    max score (an infinite/degenerate band) when the target mass is unreachable,
    which is the correct conservative behaviour.
    """
    scores = np.asarray(scores, dtype=np.float64)
    n = scores.shape[0]
    if n == 0:
        return 1.0  # no calibration data -> admit everything (max uncertainty)

    if weights is None:
        # Standard unweighted split-conformal quantile with +1 correction.
        level = np.ceil((n + 1) * (1.0 - alpha)) / n
        if level >= 1.0:
            return float(np.max(scores))
        return float(np.quantile(scores, level, method="higher"))

    weights = np.asarray(weights, dtype=np.float64)
    if weights.shape[0] != n:
        raise ValueError("weights and scores length mismatch")
    if np.any(weights < 0):
        raise ValueError("weights must be non-negative")
    order = np.argsort(scores)
    s_sorted = scores[order]
    w_sorted = weights[order]
    # Test point contributes one unit of (normalized) weight at +inf, so the
    # denominator is sum(cal weights) + (mean cal weight as the test proxy).
    test_w = float(np.mean(weights)) if np.sum(weights) > 0 else 1.0
    total = float(np.sum(w_sorted)) + test_w
    if total <= 0:
        return float(np.max(scores))
    cum = np.cumsum(w_sorted) / total
    target = 1.0 - alpha
    idx = np.searchsorted(cum, target, side="left")
    if idx >= n:
        return float(np.max(scores))
    return float(s_sorted[idx])


@dataclass
class MondrianConformal:
    """Per-class (Mondrian) conformal calibrator for ESI prediction sets.

    ``q_hat`` maps a 0-based class index -> its nonconformity threshold. A class
    absent from the calibration set (no examples) falls back to the global q̂ so
    it still produces a defensible set rather than crashing.
    """

    alpha: float = DEFAULT_ALPHA
    q_hat: dict[int, float] = field(default_factory=dict)
    global_q_hat: float = 1.0
    n_per_class: dict[int, int] = field(default_factory=dict)
    source: str = "uncalibrated"

    # ---- fitting -----------------------------------------------------------
    @classmethod
    def fit(
        cls,
        probs: np.ndarray,
        labels: np.ndarray,
        *,
        alpha: float = DEFAULT_ALPHA,
        weights: np.ndarray | None = None,
        n_classes: int = N_ESI,
        source: str = "synthetic_calibration",
    ) -> "MondrianConformal":
        """Calibrate per-class q̂ from a labeled calibration set.

        ``probs`` (n, n_classes) softmax rows, ``labels`` (n,) 0-based truth.
        ``weights`` (n,) optional importance weights for weighted conformal.
        """
        probs = np.asarray(probs, dtype=np.float64)
        labels = np.asarray(labels, dtype=np.int64)
        scores = nonconformity(probs, labels)
        w = None if weights is None else np.asarray(weights, dtype=np.float64)

        global_q = _conformal_quantile(scores, alpha, w)
        q_hat: dict[int, float] = {}
        n_per_class: dict[int, int] = {}
        for c in range(n_classes):
            mask = labels == c
            n_per_class[c] = int(mask.sum())
            if not mask.any():
                q_hat[c] = global_q  # no data for this class -> global fallback
                continue
            cw = None if w is None else w[mask]
            q_hat[c] = _conformal_quantile(scores[mask], alpha, cw)
        return cls(
            alpha=alpha,
            q_hat=q_hat,
            global_q_hat=global_q,
            n_per_class=n_per_class,
            source=source,
        )

    # ---- prediction --------------------------------------------------------
    def predict_set(self, probs: Sequence[float]) -> list[int]:
        """1-based ESI prediction set for one softmax row.

        A class y is admitted iff ``1 - p[y] <= q̂[y]``. Guaranteed non-empty:
        if the threshold test excludes everything (possible when every class q̂
        is tiny), the argmax is returned so the clinician always sees a point
        estimate.
        """
        p = np.asarray(probs, dtype=np.float64)
        members: list[int] = []
        for i in range(p.shape[0]):
            q = self.q_hat.get(i, self.global_q_hat)
            if (1.0 - p[i]) <= q:
                members.append(i + 1)
        if not members:
            members = [int(np.argmax(p)) + 1]
        return members

    def q_hat_by_esi(self) -> dict[str, float]:
        """q̂ keyed by 1-based ESI level string (UI / API friendly)."""
        return {str(c + 1): float(self.q_hat.get(c, self.global_q_hat)) for c in range(N_ESI)}

    def representative_q_hat(self) -> float:
        """A single scalar q̂ for legacy UI fields.

        The mean of the per-class thresholds — more honest than the collapsed
        global value because it is dragged up by classes the model handles
        poorly, rather than dominated by the easy modal class.
        """
        if not self.q_hat:
            return float(self.global_q_hat)
        return float(np.mean(list(self.q_hat.values())))


# ---- empirical coverage (for tests / monitoring) --------------------------
def empirical_coverage(
    calibrator: MondrianConformal,
    probs: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float]:
    """Fraction of holdout points whose true label is in the prediction set.

    Returns ``{"overall": float, "by_class": {esi: float}, "avg_set_size": float}``.
    """
    probs = np.asarray(probs, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    hits = np.zeros(probs.shape[0], dtype=bool)
    sizes = np.zeros(probs.shape[0], dtype=np.float64)
    for i in range(probs.shape[0]):
        pset = calibrator.predict_set(probs[i])
        sizes[i] = len(pset)
        hits[i] = (labels[i] + 1) in pset
    by_class: dict[str, float] = {}
    for c in range(N_ESI):
        mask = labels == c
        if mask.any():
            by_class[str(c + 1)] = float(hits[mask].mean())
    return {
        "overall": float(hits.mean()) if hits.size else 0.0,
        "by_class": by_class,
        "avg_set_size": float(sizes.mean()) if sizes.size else 0.0,
    }
