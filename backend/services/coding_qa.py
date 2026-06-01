"""Coding QA + audit-defense layer over ``services.em_coding`` output.

``em_coding.suggest()`` already emits E&M and CPT codes, each carrying a
deterministic confidence plus the MDM / time / NCCI evidence behind it. This
module is the *quality-assurance and audit-defensibility* wrapper a CFO / RCM
lead (or a payer-downcoding appeal, e.g. Cigna's R49 program) needs: for every
emitted code it produces a calibrated **confidence band**, a **needs-human-
review** flag, the **evidence trail** already computed upstream, a plain-English
**audit_rationale** for why the level is defensible, and a **downcoding_risk**
flag. It rolls these up into a **clean_code_rate** for the encounter.

Design constraints (per CONSTITUTION.md):
- ARCH-002: no boto3 here; this is a pure service-layer transform.
- ARCH-003: no AI provider call here — the scoring reuses em_coding's own
  deterministic confidences. Fully deterministic, side-effect free.
- SEC-002: every log line carries only non-PHI scalars (code, band, counts).
  Free-text evidence (which may quote the note verbatim) is NEVER logged.
- Additive: this module reads em_coding output; it does not mutate it.

The confidence bands mirror the spirit of ``lib.conformal``: a single scalar
confidence is bucketed into high / medium / low against fixed thresholds, the
same way the conformal layer turns a per-class q̂ into a human-facing band.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence band thresholds
# ---------------------------------------------------------------------------
# em_coding's own confidences cluster around well-known anchors: a clean top E&M
# pick is 0.85, a top pick that disagrees with documented time is 0.6, the
# alternate is 0.45, CPT top picks start at 0.8 and NCCI-error codes are capped
# at 0.3. The bands below are chosen so those anchors land intuitively:
#   high   >= 0.80  (clean top pick, no contradicting evidence)
#   medium >= 0.50  (plausible but contested — time disagreement, alternate)
#   low    <  0.50  (weak support or an NCCI-flagged / orphaned code)
_BAND_HIGH = 0.80
_BAND_MEDIUM = 0.50

# A code at or below the high threshold but flagged by NCCI / time disagreement
# always needs human review regardless of its numeric confidence.
_REVIEW_CONFIDENCE_FLOOR = _BAND_HIGH


def confidence_band(confidence: float) -> str:
    """Bucket a 0..1 confidence into ``high`` / ``medium`` / ``low``."""
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        c = 0.0
    if c >= _BAND_HIGH:
        return "high"
    if c >= _BAND_MEDIUM:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Per-code QA review
# ---------------------------------------------------------------------------

def _ncci_flags_for(code: str, ncci: dict[str, Any]) -> list[dict[str, Any]]:
    """NCCI flags from em_coding's validation block that name this code."""
    out: list[dict[str, Any]] = []
    for f in ncci.get("flags", []) or []:
        if code in (f.get("codes") or []):
            out.append(f)
    return out


def _review_em_code(
    entry: dict[str, Any],
    *,
    rank: int,
    time_check: dict[str, Any],
    leveling: dict[str, Any],
) -> dict[str, Any]:
    """QA report for one ranked E&M code."""
    code = str(entry.get("code", ""))
    confidence = float(entry.get("confidence", 0.0))
    band = confidence_band(confidence)
    agrees_with_time = bool(entry.get("agrees_with_time", True))
    time_documented = bool(time_check.get("documented", False))

    # Downcoding risk: a payer is most likely to downcode the *billed* (top) code
    # when the documented time contradicts the MDM-derived level, or when MDM
    # support is thin (band below high). Alternates are not "the bill" so they
    # don't carry downcoding risk themselves.
    downcoding_risk = rank == 1 and (band != "high" or (time_documented and not agrees_with_time))

    # Human review is required when the primary bill isn't a clean high-band pick,
    # or whenever the time cross-check disagrees with the chosen level.
    needs_human_review = (
        rank == 1
        and (confidence < _REVIEW_CONFIDENCE_FLOOR
             or (time_documented and not agrees_with_time))
    )

    evidence = {
        "supporting_documentation": entry.get("supporting_documentation", ""),
        "mdm_tier": leveling.get("mdm_tier"),
        "element_scores": leveling.get("element_scores"),
        "leveling_rule": leveling.get("rule"),
        "agrees_with_time": agrees_with_time,
        "time_crosscheck": {
            "documented": time_documented,
            "time_based_code": time_check.get("time_based_code"),
            "time_based_range": time_check.get("time_based_range"),
        },
    }

    if band == "high" and not downcoding_risk:
        rationale = (
            f"E&M {code} is supported by the AMA 2-of-3 MDM rule at the "
            f"'{leveling.get('mdm_tier')}' tier"
            + (" and the documented total time independently agrees."
               if (time_documented and agrees_with_time) else ".")
        )
    elif time_documented and not agrees_with_time:
        rationale = (
            f"E&M {code} is MDM-supported, but the documented total time maps to "
            f"{time_check.get('time_based_code')} — reconcile MDM vs. time before "
            "billing to withstand a downcoding review."
        )
    else:
        rationale = (
            f"E&M {code} rests on limited MDM support (confidence {confidence:.2f}); "
            "strengthen the note's data/risk documentation before billing at this level."
        )

    return {
        "code": code,
        "category": "em",
        "rank": rank,
        "confidence": round(confidence, 2),
        "confidence_band": band,
        "needs_human_review": needs_human_review,
        "downcoding_risk": downcoding_risk,
        "evidence": evidence,
        "audit_rationale": rationale,
    }


def _review_cpt_code(entry: dict[str, Any], ncci: dict[str, Any]) -> dict[str, Any]:
    """QA report for one ranked CPT/procedure code."""
    code = str(entry.get("code", ""))
    confidence = float(entry.get("confidence", 0.0))
    band = confidence_band(confidence)
    ncci_clean = bool(entry.get("ncci_clean", True))
    flags = _ncci_flags_for(code, ncci)
    has_error = any(f.get("severity") == "error" for f in flags)

    # CPT codes need review when NCCI flagged an error, or support is weak.
    needs_human_review = has_error or band == "low"
    # Downcoding / denial risk: an NCCI flag (error or bundling warning) is the
    # classic payer denial / downcode trigger for procedures.
    downcoding_risk = bool(flags) or band == "low"

    evidence = {
        "support": entry.get("support", ""),
        "add_on": bool(entry.get("add_on", False)),
        "ncci_clean": ncci_clean,
        "ncci_flags": flags,
    }

    if has_error:
        rationale = (
            f"CPT {code} carries an NCCI error edit; resolve it before billing or "
            "the line will be denied."
        )
    elif flags:
        rationale = (
            f"CPT {code} is supported but a bundling edit applies — append "
            "documentation/modifier justification to defend separate payment."
        )
    elif band == "low":
        rationale = (
            f"CPT {code} has weak note support (confidence {confidence:.2f}); confirm "
            "the procedure is documented before billing."
        )
    else:
        rationale = (
            f"CPT {code} is documented and passes NCCI edits — defensible as billed."
        )

    return {
        "code": code,
        "category": "cpt",
        "rank": None,
        "confidence": round(confidence, 2),
        "confidence_band": band,
        "needs_human_review": needs_human_review,
        "downcoding_risk": downcoding_risk,
        "evidence": evidence,
        "audit_rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def review_codes(coding_result: dict[str, Any]) -> dict[str, Any]:
    """Wrap an ``em_coding.suggest()`` result in a QA / audit-defense report.

    Pure, deterministic, no LLM call. Returns::

        {
          "available": bool,
          "reviews": [ {code, category, confidence, confidence_band,
                        needs_human_review, evidence, audit_rationale,
                        downcoding_risk, rank}, ... ],
          "clean_code_rate": float,     # fraction not needing human review
          "needs_review_count": int,
          "downcoding_risk_count": int,
          "total_codes": int,
          "summary": str,               # non-PHI, audit-trail friendly
        }

    If ``coding_result`` is unavailable (LLM gated off, or an upstream error),
    returns ``{"available": False}`` so callers can pass through unchanged.
    """
    if not isinstance(coding_result, dict) or not coding_result.get("available"):
        return {"available": False}

    ncci = coding_result.get("ncci_validation", {}) or {}
    time_check = coding_result.get("time_crosscheck", {}) or {}
    leveling = coding_result.get("em_leveling", {}) or {}

    reviews: list[dict[str, Any]] = []

    # E&M codes: review the ranked list (top pick is the bill; alternates are
    # context). ``em_ranked`` already carries rank, confidence, evidence.
    for entry in coding_result.get("em_ranked", []) or []:
        rank = int(entry.get("rank", len(reviews) + 1))
        reviews.append(_review_em_code(entry, rank=rank, time_check=time_check,
                                       leveling=leveling))

    # CPT / procedure codes.
    for entry in coding_result.get("cpt_ranked", []) or []:
        reviews.append(_review_cpt_code(entry, ncci))

    total = len(reviews)
    needs_review = sum(1 for r in reviews if r["needs_human_review"])
    downcoding = sum(1 for r in reviews if r["downcoding_risk"])
    clean_rate = round((total - needs_review) / total, 3) if total else 1.0

    summary = (
        f"{total - needs_review}/{total} codes clean; "
        f"{needs_review} need human review; {downcoding} carry downcoding risk."
    )

    # SEC-002: log only non-PHI scalars — never the evidence free-text.
    log.info(
        "coding_qa total=%s needs_review=%s downcoding_risk=%s clean_rate=%s",
        total, needs_review, downcoding, clean_rate,
    )

    return {
        "available": True,
        "reviews": reviews,
        "clean_code_rate": clean_rate,
        "needs_review_count": needs_review,
        "downcoding_risk_count": downcoding,
        "total_codes": total,
        "summary": summary,
    }
