# Clinical AI Model Improvement Research

Status: research / recommendations. Author scope: ML quality of the Solace triage stack.
Date: 2026-05-16.

This document is implementation-focused. Every recommendation is scoped to what
is codeable on the **existing LightGBM 5-fold + SHAP stack** plus the Claude-LLM
services already wired in (`ddx_v2.py`, `evidence_rag.py`). Nothing here requires
a GPU, a deep model, or a retrain from scratch unless explicitly flagged.

Files reviewed: `backend/services/triage_ml.py`, `triage_engine.py`, `ddx_v2.py`,
`early_warning.py`, `sepsis_bundle.py`, `evidence_rag.py`.

---

## 0. Problem inventory (what the code does today)

| Area | Current state | Defect |
|---|---|---|
| Conformal set (ESI) | `triage_ml.predict`: `conformal_set = [i+1 for i,p if (1-p) <= q_hat]` — a single global `q_hat` (LAC / least-ambiguous score). | Marginal coverage only. On text-dominated synthetic data the top-1 softmax probability saturates near 1.0, so `1-p` for the true class is tiny and the set collapses to a singleton — coverage is **not** honored per ESI level. ESI-1/2 (rare, high-stakes) are exactly where the set should widen and it does not. |
| Ddx "conformal" | `ddx_v2._conformal`: cumulative-sum of LLM-reported `weight` until 0.90/0.95. | This is **not conformal prediction**. There is no calibration set, no nonconformity score, no coverage guarantee. The name is misleading and the "weights" are uncalibrated LLM self-reports — known to be overconfident. A single LLM call also gives no uncertainty estimate. |
| Sepsis EWS | `early_warning.sepsis_ews`: fixed-threshold additive MEWS+qSOFA hybrid, single snapshot. | No trend term, no probability output, no calibration to an outcome, no explicit operating point. "Calibrated to published validations" is a claim, not a calibrated model. Cannot demonstrably beat Epic ESM without an ROC/PR comparison. |
| Evidence RAG | `evidence_rag._bm25_lite`: lexical-only BM25-lite over 16 inline snippets. | Pure sparse retrieval. Misses semantic paraphrase ("can't catch my breath" vs "dyspnea"). No reranking. No dense recall. |
| Bias | None. `triage_ml` carries `sex`, `language`, `insurance_type`, `age_group` as features and label-encodes them straight into the model. | No subgroup audit. Synthetic-data label bias propagates silently. `insurance_type` as a triage feature is an active fairness liability. |

The root failure mode for (a) and (b) is the same: **text dominance**. The TF-IDF
block (`tfidf_word` + `tfidf_char`) supplies thousands of features that let the
LightGBM ensemble memorize the synthetic chief-complaint templates, producing
near-deterministic softmax outputs. Any uncertainty method layered on top of a
saturated probability vector will under-cover.

---

## (a) Fixing conformal-set collapse

### a.1 — Switch the nonconformity score from LAC to APS, then RAPS

The current score is **LAC** (Least Ambiguous set-valued Classifier):
`s(x,y) = 1 - p_hat(y|x)`. LAC produces the *smallest* sets and is the most
fragile under miscalibration — when `p_hat` saturates, sets collapse.

Move to **APS** (Adaptive Prediction Sets, Romano, Sesia & Candès, NeurIPS 2020):
the score is the cumulative softmax mass of classes ranked above the true class,
plus a randomized fraction of the true class:

```
s(x,y) = sum_{k: p_hat(k) >= p_hat(y)} p_hat(k) - U * p_hat(y),   U ~ Uniform(0,1)
```

APS targets conditional coverage and naturally widens sets where the probability
vector is flat. Because the score uses *ranked cumulative mass*, it degrades
gracefully even when the top probability is over-confident.

APS can over-cover and produce large tails. Layer **RAPS** (Regularized APS,
Angelopoulos et al., ICLR 2021) on top — add a penalty `lambda * max(0, rank - k_reg)`
to the score, which truncates the tail. RAPS achieves the same coverage as APS
with sets reported 5-10x smaller. Tune `lambda` and `k_reg` on the calibration
split.

Implementation: this is ~40 lines, no retrain. Operates on the existing
`probs` vector in `predict()`. The calibration step (computing the quantile)
runs once at training time in the Triagegeist notebook and the resulting
`q_hat` ships in `artifacts.pkl`. Recommend `mapie` (`MapieClassifier`,
`method="raps"`) to avoid hand-rolling the randomized quantile, or implement
directly — the APS/RAPS scoring functions are short and well documented in
Angelopoulos & Bates, *A Gentle Introduction to Conformal Prediction* (2023).

### a.2 — Mondrian (class-conditional) calibration

A single global `q_hat` gives only **marginal** coverage: averaged over all ESI
levels. For triage that is the wrong guarantee — ESI-1 (resuscitation) under-coverage
is a patient-safety event, while ESI-4/5 over-coverage is merely noise.

**Mondrian / class-conditional conformal** (Vovk, *Conditional Validity of
Inductive Conformal Predictors*, 2012; Bostrom et al., COPA 2021) computes a
**separate quantile per ESI level** using only calibration points whose *true*
label is that level:

```
for level L in 1..5:
    cal_scores_L = [ s(x_i, y_i) for i in calibration if y_i == L ]
    q_hat[L]     = quantile(cal_scores_L, ceil((n_L+1)(1-alpha)) / n_L)
# at inference, class k enters the set iff  s(x, k) <= q_hat[k]
```

This guarantees `1-alpha` coverage *within each ESI level*. Ding et al.
(*Class-Conditional Conformal Prediction with Many Classes*, NeurIPS 2023)
show that with few calibration points per rare class, naive class-conditional
quantiles are unstable; their **clustered** variant pools statistically similar
classes. With only 5 ESI levels and an 80k-row dataset there are easily
thousands of calibration points even for ESI-1, so plain Mondrian is sufficient
here — no clustering needed.

Ship `conformal_q_hat` as a length-5 array keyed by ESI level. The inference
change in `predict()`:

```python
q = art["conformal_q_hat_mondrian"]   # list[5]
conformal_set = [k + 1 for k, p in enumerate(probs) if aps_score(probs, k) <= q[k]]
```

### a.3 — A vitals-only ensemble member to break text dominance

The diagnosis of conformal collapse is that TF-IDF features let the model fit
synthetic chief-complaint phrasing almost deterministically. Add a **third
calibrated head**: train a separate LightGBM (or even logistic regression) on
**structured features only** — vitals, flags, composites (`qsofa`, `sirs`,
`shock_index`, `news2_score`), age, comorbidity counts — *excluding all
`tfidf_*` columns*. `struct_cols` already exists in `artifacts.pkl`, so the
feature subset is free.

Then form the final probability vector as a **modality average**:

```
p_final = w_text * p_textfull + w_vitals * p_vitalsonly
```

The vitals-only member produces genuinely uncertain probabilities on ambiguous
cases (real patient signal, not template memorization), which de-saturates
`p_final` and lets APS/RAPS produce honest set sizes. Tune `w_vitals` (start
0.4) on the calibration QWK. This is the single highest-leverage fix for
collapse because it attacks the cause, not the symptom.

### a.4 — Per-modality conformal calibration

Run conformal calibration **separately on each ensemble member** and combine,
rather than calibrating the blended vector once. Concretely: compute APS scores
on `p_textfull` and on `p_vitalsonly` independently, take per-member Mondrian
quantiles, and form the prediction set as the **union** (conservative — preserves
coverage) or a weighted-vote intersection (tighter — validate coverage empirically).
The union rule is the safe default for triage and is trivially codeable.

This also gives a free diagnostic: if the text member's set is a singleton but
the vitals member's set is `{2,3,4}`, the UI can surface "model confidence is
driven by chief-complaint text, not measured vitals" — directly actionable for
a clinician and a strong trust signal.

### a.5 — Validation: report coverage, do not assume it

Add to the training notebook and to `model_metrics`:

- **Marginal coverage** on a held-out test split (target `1-alpha`, e.g. 0.90).
- **Per-ESI coverage** (the Mondrian guarantee — must hold for every level).
- **Average set size** and the **set-size distribution** per ESI level.
- A **synthetic-vs-noisy** comparison: the code already keeps
  `conformal_q_hat_noisy`; keep that pattern and report both, because the noisy
  number is the realistic one.

Coverage that holds on synthetic data will *not* transfer to real EHR data —
state this explicitly and re-calibrate on the first real labeled cohort
(conformal calibration needs only a few hundred labeled examples, which makes
it the cheapest thing to re-fit post-deployment).

---

## (b) Better Ddx ranking and calibration

### b.1 — Rename the misnamed function

`ddx_v2._conformal` is **not conformal prediction** — it is cumulative-probability
thresholding (a "top-p / nucleus" set) on uncalibrated LLM self-reported weights.
Calling output keys `set_90` / `set_95` falsely implies a 90 % / 95 % coverage
guarantee that does not exist. This is a clinical-safety documentation defect:
a clinician reading "95 % set" will trust it as calibrated.

Minimum fix: rename to `cumulative_likelihood_set` with keys `top_p_90` /
`top_p_95`, and label it in the UI as "LLM-estimated likelihood grouping, not a
coverage-guaranteed set." Real conformal would require a labeled Ddx calibration
corpus (b.3).

### b.2 — Self-consistency sampling for Ddx ranking and uncertainty

A single `claude.messages_create` call gives a point estimate with no
uncertainty. Replace with **self-consistency sampling** (Wang et al.,
*Self-Consistency Improves Chain of Thought Reasoning*, ICLR 2023): call the
model **N=5-7 times at temperature ~0.7**, then aggregate.

For each candidate diagnosis, derive:

- **`vote_frequency`** = fraction of the N samples that listed it. This is a far
  better-calibrated rank signal than a single self-reported `weight`. Kumar et
  al. (PMC11648734, 2024) found self-consistency to be the most effective
  uncertainty proxy for LLM medical diagnosis, with discrimination ROC-AUC
  0.68-0.79 across tasks.
- **`mean_weight`** and **`weight_std`** across samples that listed it — the
  spread quantifies model uncertainty for that diagnosis.
- **Semantic entropy** of the top-ranked diagnosis across samples (cluster
  paraphrases — "MI" / "acute coronary syndrome" / "heart attack" — via the
  ICD-10 code or a cheap embedding match before counting). High entropy → flag
  the case as low-confidence and widen the surfaced list.

Cost: 5-7x the LLM tokens per Ddx. Mitigate with **adaptive self-consistency**
(Reliability-Aware Adaptive Self-Consistency, arXiv 2601.02970): stop sampling
early once the top-diagnosis vote share crosses a confidence threshold —
typically 2-3 calls suffice for easy cases, the full budget only for hard ones.
The N calls are independent → run them concurrently (the SDK supports
parallel requests) so wall-clock latency stays at roughly one call.

### b.3 — Genuine calibration once a labeled corpus exists

To make a *real* coverage claim for Ddx, build a small calibration set of
encounters with a gold final diagnosis (chart-abstracted, or NEJM-style case
reports as a proxy — the 2024 medical-LLM benchmarks used exactly this). Then:

- Nonconformity score `s = 1 - vote_frequency(true_dx)`.
- Split-conformal quantile on that calibration set → an honest prediction set
  that contains the true diagnosis with `1-alpha` probability.
- Optionally **isotonic-regress** `vote_frequency` → empirical hit-rate so the
  displayed per-diagnosis number is a calibrated probability, not a vote share.

Until that corpus exists, do not advertise a coverage number.

### b.4 — Keep the red-flag canon, but separate it visually

The hard-coded `RED_FLAGS` merge is sound — a deterministic safety net that
does not depend on the LLM. Keep it. But injected red flags currently get a flat
`weight: 0.05` and then flow into the (renamed) likelihood set, mixing a
keyword-trigger signal with a probabilistic one. Surface red flags as a
**separate "must-not-miss — rule out" panel**, never inside the ranked
likelihood list, so the two epistemics stay distinct.

---

## (c) A sepsis EWS that can beat Epic ESM

Epic's ESM is the bar to clear, and it is a low bar: external validation at
Michigan Medicine (Wong et al., *JAMA Internal Medicine* 2021) found
**AUC 0.63** (vs Epic's claimed 0.76-0.83), **33 % sensitivity**, **12 % PPV**,
missed **67 %** of sepsis cases, and generated alerts on 18 % of all
hospitalizations — massive alert fatigue. The failure causes were **inadequate
calibration**, weak discrimination, and a poorly chosen operating point. Solace's
EWS must fix exactly those.

The current `early_warning.sepsis_ews` is a fixed-threshold additive score with
no probability output, no trend term, and no operating point — it cannot be
*compared* to ESM on an ROC/PR curve, let alone shown to beat it. Recommendations:

### c.1 — Make it a calibrated probabilistic model

Train a LightGBM (or logistic regression for a transparent, auditable baseline)
on the same Triagegeist features to predict **P(sepsis within 6-12 h)**, using a
Sepsis-3 label. The MEWS+qSOFA additive score becomes one *input feature* and a
fallback, not the model. This gives a continuous risk that can be ROC/PR-evaluated
against ESM.

### c.2 — Trend-aware features

ESM and the current EWS both score a single snapshot. Deterioration is a
*trajectory*. `deterioration_index` already computes `vitals_4h_ago` deltas —
promote those deltas into the sepsis model as features: `delta_hr`, `delta_sbp`,
`delta_rr`, `delta_temp`, `delta_spo2`, slope of `shock_index`, and a
"new oxygen requirement" flag. Trend features are consistently the largest
single AUC gain over snapshot-only EWS in the deterioration literature.

### c.3 — Isotonic calibration

Fit **isotonic regression** on a held-out split to map raw model score →
observed sepsis rate (`sklearn.isotonic.IsotonicRegression`, or
`CalibratedClassifierCV(method="isotonic")`). Isotonic is non-parametric and
handles the S-shaped miscalibration of tree ensembles better than Platt scaling.
Report a **reliability diagram** and **Brier score / ECE** — calibration was the
named Epic failure, so this must be a headline metric, not an afterthought.

### c.4 — Choose the operating point on the PR curve, not the ROC curve

Sepsis is rare (low prevalence) → ROC is misleadingly optimistic. Pick the alert
threshold on the **precision-recall curve**. Define a target operating point
*explicitly* — e.g. sensitivity >= 0.80 at the highest achievable precision, or
maximize F-beta with beta>1 (recall-weighted). Publish the resulting
sensitivity / PPV / alert-rate so it can be put side-by-side with ESM's
33 % / 12 % / 18 %. Beating ESM means: higher sensitivity *and* a lower alert
rate. A two-threshold scheme ("elevated" surveillance band + "high" hard alert)
keeps alert fatigue down — only the high band interrupts the clinician.

### c.5 — Keep per-feature attribution

The current `contributions` list is a real strength over ESM's black box —
ESM's opacity was part of why clinicians distrusted it. Keep it: use SHAP on the
LightGBM sepsis model (the SHAP plumbing in `triage_ml._shap_top_features`
generalizes directly) so every alert ships with its drivers.

### c.6 — Validate trend vs snapshot honestly

Report AUROC **and AUPRC** for snapshot-only vs trend-aware on the same held-out
split, with confidence intervals. State the synthetic-data caveat: a number that
beats ESM's 0.63 on synthetic data is necessary but not sufficient — re-validate
on real data before any clinical claim.

---

## (d) Hybrid RAG retrieval and reranking

`evidence_rag._bm25_lite` is lexical-only. It will match "UTI" but miss
"burning when I pee", and match "MI" but miss "crushing chest pressure". The
production pattern for clinical RAG is **hybrid retrieve → rerank → synthesize**.

### d.1 — Add a dense retriever, fuse with BM25

Keep BM25-lite (it is the *precision* leg — exact matches on drug names,
ICD-10 codes, score names like "CHA2DS2-VASc" where dense retrievers reliably
fail). Add a **dense leg**: embed each `EvidenceSnippet` once at startup and the
query at request time. For a 16-snippet inline corpus a tiny sentence-transformer
or an embedding API call is plenty; no vector DB needed until the corpus grows
(the code already anticipates this with `EVIDENCE_RAG_BACKEND=vector`).

Fuse the two ranked lists with **Reciprocal Rank Fusion** (Cormack et al., 2009)
— `score(d) = sum 1/(k + rank_i(d))`, `k≈60` — which needs no score
normalization and is robust. For technical clinical corpora, weight the two legs
roughly equally.

### d.2 — Add a cross-encoder reranker

The biggest single-component RAG gain reported in the literature is the
reranker. After hybrid retrieval of the top ~20-50 candidates, run a
**cross-encoder** (query + snippet jointly encoded → relevance score) and pass
only the top 5-6 to the Claude synthesizer. A small cross-encoder (e.g. a
`ms-marco`-style MiniLM reranker, or an LLM-as-reranker call if avoiding a model
dependency) is enough at this corpus size. Standard pattern:
**retrieve 50 hybrid → rerank → top-5 to LLM**.

### d.3 — Keep the refuse-on-no-evidence behavior

`answer()` already refuses when retrieval is empty and instructs the synthesizer
to use only retrieved snippets — this is correct and a real anti-hallucination
control. With hybrid retrieval, recall rises, so add a **minimum rerank-score
floor**: if even the top reranked snippet is below a relevance threshold, refuse,
rather than synthesizing from a weak match. This preserves the safety property
while raising recall.

---

## (e) Bias-audit methodology

`triage_ml` ingests `sex`, `language`, `insurance_type`, `age_group` and
label-encodes them straight into the model. There is no subgroup audit. On
synthetic Kaggle data, any labeling bias in the generator is silently learned.
`insurance_type` as a triage feature is an active fairness liability — there is
no clinical reason payer status should change an acuity prediction.

### e.1 — Define protected attributes and audit cohorts

Audit across: `sex`, `age_group`, `language` (proxy for limited-English
proficiency), and — if present — race/ethnicity. Treat `insurance_type` as a
**candidate feature to remove** (e.2).

### e.2 — Drop or quarantine `insurance_type`

Remove `insurance_type` from `struct_cols`, retrain, and check the QWK delta.
If accuracy is unchanged (likely), the feature was contributing bias risk for
no clinical value — drop it permanently. If it helps, that itself is evidence of
a confound worth investigating, not a reason to keep it.

### e.3 — Subgroup performance parity

Per protected subgroup, report and compare:

- **Per-ESI accuracy** and **QWK**.
- **Under-triage rate** — predicted ESI numerically *higher* (less acute) than
  true. This is the safety-critical error; an under-triage disparity across
  subgroups is the headline fairness metric for triage.
- **Conformal coverage** per subgroup — Mondrian (a.2) guarantees coverage per
  *class*, not per *demographic group*. Verify empirically that coverage holds
  within each subgroup; if it does not, extend Mondrian to subgroup-conditional
  calibration (same mechanism, partition the calibration set by subgroup).
- **Calibration** per subgroup — reliability diagram and ECE.

### e.4 — Equalized-odds style check on under-triage

Frame the primary fairness criterion as **equalized odds on under-triage**:
the under-triage rate should be statistically indistinguishable across protected
groups, conditional on true ESI. Report differences with bootstrap confidence
intervals. (Fairlearn provides `MetricFrame` and the equalized-odds metrics
off the shelf and integrates with any sklearn-style predictor.)

### e.5 — SHAP-based bias surfacing

Use the existing SHAP plumbing to audit *direction*: aggregate SHAP values for
protected-attribute features across the test set. A protected attribute with
large mean |SHAP| is driving predictions and demands scrutiny. This converts
SHAP from a per-patient explainer into a population-level bias instrument at
near-zero extra cost.

### e.6 — Document the synthetic-data ceiling

State plainly: a fairness audit on synthetic data validates the *methodology and
pipeline*, not real-world fairness. The audit harness must be re-run on the
first real labeled cohort. Build the harness now so it is ready.

---

## Prioritized roadmap

| Priority | Item | Effort | Why first |
|---|---|---|---|
| P0 | (a.3) Vitals-only ensemble member | M — one extra LightGBM, `struct_cols` already exists | Attacks the *cause* of conformal collapse (text dominance). Unblocks every other uncertainty fix. |
| P0 | (a.1 + a.2) APS/RAPS + Mondrian conformal | S — ~40-60 lines, calibration in notebook, no retrain | Replaces fragile LAC with per-ESI coverage; safety-critical for ESI-1/2. |
| P1 | (c) Calibrated, trend-aware, isotonic sepsis EWS w/ PR operating point | L — new model + calibration + eval | Directly beats the Epic ESM benchmark; a headline differentiator. |
| P1 | (b.1 + b.2) Rename misnamed "conformal" + self-consistency Ddx sampling | M — rename is trivial; sampling is parallel LLM calls | Fixes a clinical-safety mislabel; gives real Ddx uncertainty. |
| P2 | (d) Hybrid retrieval + cross-encoder reranking | M — dense leg + RRF + reranker | Largest retrieval-quality gain; lower risk, no patient-safety blocker. |
| P2 | (e) Bias-audit harness + drop `insurance_type` | M — harness is reusable; feature drop is trivial | Methodology must exist before real data arrives; `insurance_type` removal is a quick fairness win. |

Cross-cutting: every metric above must be reported **per ESI level / per
subgroup**, and every claim must carry the **synthetic-data caveat** plus a
re-calibration plan for the first real labeled cohort. Conformal calibration and
isotonic calibration both need only a few hundred labeled examples — making them
the cheapest, highest-value things to re-fit post-deployment.

---

## References

- Romano, Sesia & Candès. *Classification with Valid and Adaptive Coverage* (APS). NeurIPS 2020.
- Angelopoulos, Bates, Jordan & Malik. *Uncertainty Sets for Image Classifiers using Conformal Prediction* (RAPS). ICLR 2021.
- Angelopoulos & Bates. *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification.* 2023.
- Vovk. *Conditional Validity of Inductive Conformal Predictors.* ACML 2012.
- Boström et al. *Mondrian Conformal Predictive Distributions.* COPA / PMLR 152, 2021.
- Ding, Angelopoulos, Bates, Jordan & Tibshirani. *Class-Conditional Conformal Prediction with Many Classes.* NeurIPS 2023.
- Wang et al. *Self-Consistency Improves Chain of Thought Reasoning in Language Models.* ICLR 2023.
- Kumar et al. *Large language model uncertainty proxies: discrimination and calibration for medical diagnosis and treatment.* PMC11648734, 2024.
- *Reliability-Aware Adaptive Self-Consistency for Efficient Sampling in LLM Reasoning.* arXiv:2601.02970, 2026.
- Wong, Otles, Donnelly et al. *External Validation of a Widely Implemented Proprietary Sepsis Prediction Model in Hospitalized Patients (Epic ESM).* JAMA Internal Medicine, 2021. PMC8218233.
- Habib, Lin & Grant. *The Epic Sepsis Model Falls Short — The Importance of External Validation.* JAMA Internal Medicine, 2021. PubMed 34152360.
- Cormack, Clarke & Buettcher. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods.* SIGIR 2009.
- *Retrieval-Augmented Generation in Biomedicine: A Survey.* arXiv:2505.01146, 2025.
