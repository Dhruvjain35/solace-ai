"""Differential diagnosis v2 — clinician-facing ``/ddx/v2`` endpoint.

This module keeps its keyword-arg ``generate()`` signature (the only caller is
``routers/clinical_ai.py``). It no longer owns the red-flag canon or the
conformal math — those now live in ``services/differential.py`` as the single
source of truth, and ddx_v2 *delegates* to them:

  - ``differential.match_red_flags`` — canonical don't-miss library lookup.
  - ``differential.conformal_sets`` — adaptive prediction sets (set_90/set_95)
    with per-diagnosis nonconformity = ``1 - weight``.
  - ``differential.counterfactual_prompts`` — deterministic "what discriminates
    the top 3?" baseline merged with the LLM's own counterfactuals.

What ddx_v2 adds on top is a specialty-biased LLM prompt: pass ``specialty`` to
bias the differential toward that specialty's pretest probabilities.

The output is decision support — never auto-acts, never replaces the existing
``triage_ml`` model output.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from lib import claude, json_extract
from lib.config import settings
from services import differential

log = logging.getLogger(__name__)

_MODEL = settings.model_clinical

# Re-exported so existing references to ddx_v2.RED_FLAGS keep resolving; the
# authoritative library now lives in services/differential.py.
RED_FLAGS = differential.RED_FLAG_LIBRARY


_SYSTEM = """You are an experienced ED attending generating a differential diagnosis (Ddx) draft.

Return JSON ONLY (no markdown):
{
  "differential": [
    {
      "diagnosis": "short Dx name",
      "icd10": "best-guess ICD-10",
      "weight": 0.0-1.0,
      "supporting": ["clinical feature arguing FOR this Dx", "..."],
      "refuting": ["what argues against / what is missing", "..."],
      "discriminator": "single best discriminating test or maneuver",
      "reasoning": "1-2 sentence clinical rationale tying the case to this Dx",
      "must_not_miss": false,
      "evidence_quote": "verbatim short snippet from the transcript that anchored this Dx"
    }
  ],
  "counterfactuals": [
    {
      "question": "what additional history/finding would change the ranking?",
      "discriminates": ["Dx A", "Dx B"],
      "why": "which Dx rises/falls and why"
    }
  ]
}

Rules:
- Return 3-6 entries; weight = your normalized pretest probability across the list,
  weights should sum to ~1.0.
- Bias your pretest probabilities toward the SPECIALTY context provided.
- Anchor every entry to at least one transcript-derived fact in "supporting".
- "discriminator": one concrete next step — not a list.
- counterfactuals: 2-4 entries on what would meaningfully change rankings.
- Set must_not_miss true ONLY for life/limb threats with at least one supporting feature.
"""


def _build_prompt(
    transcript: str,
    chief_complaint: str,
    medical_info: dict[str, Any] | None,
    specialty: str,
    vitals: dict[str, Any] | None,
) -> str:
    parts = [
        f"Specialty context: {specialty.upper()}",
        f"Chief complaint: {chief_complaint or '(infer from transcript)'}",
        f'Transcript:\n"""\n{transcript[:8000]}\n"""',
    ]
    if medical_info:
        parts.append(f"Medical history: {json.dumps(medical_info)[:1200]}")
    if vitals:
        v = ", ".join(f"{k}={val}" for k, val in vitals.items() if val is not None)
        if v:
            parts.append(f"Bedside vitals: {v}")
    parts.append("Return JSON now.")
    return "\n\n".join(parts)


def _call_llm(prompt: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the specialty-biased Claude call. Returns ``(differential, cf)``."""
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=2800,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            purpose="ddx_v2",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        # Tolerant parse: handles markdown fences and output truncated at the
        # token ceiling (which silently broke this on the chattier model).
        parsed = json_extract.extract_obj(text)
        if not parsed:
            return [], []
        return _clean_differential(parsed.get("differential")), _clean_counterfactuals(
            parsed.get("counterfactuals")
        )
    except Exception as e:  # noqa: BLE001 - decision support degrades gracefully
        log.warning("ddx_v2 LLM call failed: %s", e)
        return [], []


def _clean_differential(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        dx = str(item.get("diagnosis", "")).strip()
        if not dx:
            continue
        try:
            weight = float(item.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        out.append(
            {
                "diagnosis": dx,
                "icd10": str(item.get("icd10", "")).strip(),
                "weight": max(0.0, min(1.0, weight)),
                "supporting": _str_list(item.get("supporting") or item.get("rule_in")),
                "refuting": _str_list(item.get("refuting") or item.get("rule_out")),
                "discriminator": str(
                    item.get("discriminator") or item.get("next_step") or ""
                ).strip(),
                "reasoning": str(item.get("reasoning", "")).strip(),
                "must_not_miss": bool(item.get("must_not_miss")),
                "evidence_quote": str(item.get("evidence_quote", "")).strip(),
            }
        )
        if len(out) >= 6:
            break
    return out


def _clean_counterfactuals(value: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        # Accept both the new {question,...} schema and the legacy
        # {if_true, would_change} schema.
        question = str(item.get("question") or item.get("if_true") or "").strip()
        if not question:
            continue
        out.append(
            {
                "question": question,
                "discriminates": _str_list(item.get("discriminates")),
                "why": str(item.get("why") or item.get("would_change") or "").strip(),
            }
        )
    return out


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:4]


def generate(
    transcript: str,
    chief_complaint: str = "",
    *,
    medical_info: dict[str, Any] | None = None,
    specialty: str = "ed",
    vitals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Specialty-biased differential with conformal sets and red-flag canon.

    Output shape (unchanged keys, richer per-diagnosis depth):
        {
          "differential":    [ {diagnosis, icd10, weight, supporting, refuting,
                                 discriminator, reasoning, must_not_miss,
                                 evidence_quote}, ... ],
          "counterfactuals": [ {question, discriminates, why}, ... ],
          "red_flags":       [ {diagnosis, icd10, group, must_not_miss}, ... ],
          "conformal":       {set_90, set_95, nonconformity,
                              threshold_90, threshold_95},
        }

    Red-flag matching and conformal calibration are delegated to the shared
    helpers in ``services/differential.py``.
    """
    empty: dict[str, Any] = {
        "differential": [],
        "counterfactuals": [],
        "red_flags": [],
        "conformal": differential.conformal_sets([]),
    }
    if not claude.available():
        return empty

    prompt = _build_prompt(transcript, chief_complaint, medical_info, specialty, vitals)

    # The LLM call and the (cheap, deterministic) red-flag scan are independent;
    # run them concurrently so the red-flag library lookup never sits behind the
    # network round-trip. ThreadPoolExecutor keeps this safe for the blocking
    # claude SDK call.
    red_flag_text = f"{transcript} {chief_complaint}"
    with ThreadPoolExecutor(max_workers=2) as pool:
        llm_future = pool.submit(_call_llm, prompt)
        rf_future = pool.submit(differential.match_red_flags, red_flag_text)
        diff, llm_counterfactuals = llm_future.result()
        red_flags = rf_future.result()

    # Fold any missing don't-miss diagnoses into the differential.
    diff_names = {d["diagnosis"].lower() for d in diff}
    for rf in red_flags:
        if rf["diagnosis"].lower() in diff_names:
            for d in diff:
                if d["diagnosis"].lower() == rf["diagnosis"].lower():
                    d["must_not_miss"] = True
            continue
        diff.append(
            {
                "diagnosis": rf["diagnosis"],
                "icd10": rf["icd10"],
                "weight": 0.05,
                "supporting": ["red-flag canon match — verify by exam/test"],
                "refuting": [],
                "discriminator": "rule out per institutional pathway",
                "reasoning": (
                    f"Don't-miss diagnosis for the {rf['group']} complaint group; "
                    "surfaced from the shared red-flag library."
                ),
                "must_not_miss": True,
                "evidence_quote": "",
            }
        )

    diff.sort(key=lambda d: d.get("weight", 0.0), reverse=True)

    conformal = differential.conformal_sets(diff)
    counterfactuals = _merge_counterfactuals(
        llm_counterfactuals, differential.counterfactual_prompts(diff)
    )

    return {
        "differential": diff,
        "counterfactuals": counterfactuals,
        "red_flags": red_flags,
        "conformal": conformal,
    }


def _merge_counterfactuals(
    llm: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(llm) + list(baseline):
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        norm = q.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(item)
    return out[:6]
