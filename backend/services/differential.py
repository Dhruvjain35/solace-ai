"""Claude-generated differential diagnosis — Glass-grade depth.

Two public entry points:

  - ``generate(...)`` — backward-compatible wrapper returning ``list[dict]``
    with the legacy keys (``diagnosis``, ``icd10``, ``likelihood``,
    ``rule_in``, ``rule_out``, ``must_not_miss``). Callers in
    ``routers/intake.py`` and the downstream ``workup`` / ``disposition``
    services read ``diagnosis`` / ``likelihood`` and serialize the list, so
    that shape is frozen.

  - ``generate_deep(...)`` — the rich object:
        {
          "differential":  [ {weight, supporting, refuting, discriminator,
                               reasoning, ...}, ... ],
          "conformal":     {set_90, set_95, nonconformity, alpha, ...},
          "red_flags":     [ {diagnosis, icd10, group, ...}, ... ],
          "counterfactuals": [ {question, discriminates, ...}, ... ],
        }

This module also exposes the *shared* differential-diagnosis primitives that
``services/ddx_v2.py`` delegates to, so the red-flag canon and the conformal
math live in exactly one place:

  - ``RED_FLAG_LIBRARY`` / ``match_red_flags(text)``
  - ``conformal_sets(differential)``
  - ``counterfactual_prompts(differential)``

Everything here is decision support shown as an "AI draft" — the clinician
verifies, narrows, or rejects each entry before workup orders go in. It never
auto-acts and never replaces the ``triage_ml`` model output.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings
from lib.medical_format import format_medical_info

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

_LIKELIHOOD_TO_WEIGHT = {"high": 0.62, "moderate": 0.27, "low": 0.11}


# ---------------------------------------------------------------------------
# Canonical "don't-miss" red-flag library
# ---------------------------------------------------------------------------
# Keyed by chief-complaint group. Each entry: a keyword regex (case-insensitive)
# and the life/limb-threatening diagnoses that group must never miss. Both this
# module and ddx_v2 read from here so there is a single source of truth.
RED_FLAG_LIBRARY: list[dict[str, Any]] = [
    {
        "group": "chest_pain",
        "trigger": r"chest|cp\b|substernal|crushing|squeez|pressure|tightness",
        "must_not_miss": [
            ("Acute coronary syndrome", "I20.9"),
            ("Pulmonary embolism", "I26.99"),
            ("Aortic dissection", "I71.00"),
            ("Pericardial tamponade", "I31.9"),
            ("Tension pneumothorax", "J93.0"),
            ("Esophageal rupture (Boerhaave)", "K22.3"),
        ],
    },
    {
        "group": "stroke",
        "trigger": r"weakness|numbness|slurred|facial droop|fast\b|stroke|aphasia|vision loss|dysarthria",
        "must_not_miss": [
            ("Acute ischemic stroke", "I63.9"),
            ("Intracranial hemorrhage", "I62.9"),
            ("Transient ischemic attack", "G45.9"),
        ],
    },
    {
        "group": "sepsis",
        "trigger": r"sepsis|septic|rigors|chills.*fever|fever.*confus|hypotens|lethargic.*fever",
        "must_not_miss": [
            ("Sepsis / septic shock", "A41.9"),
            ("Meningitis", "G03.9"),
            ("Necrotizing soft-tissue infection", "M72.6"),
        ],
    },
    {
        "group": "abdominal",
        "trigger": r"abdominal|abd pain|belly|stomach pain|flank pain",
        "must_not_miss": [
            ("Appendicitis", "K35.80"),
            ("Bowel obstruction", "K56.60"),
            ("Mesenteric ischemia", "K55.0"),
            ("Ruptured abdominal aortic aneurysm", "I71.3"),
            ("Ectopic pregnancy", "O00.9"),
            ("Perforated viscus", "K65.9"),
        ],
    },
    {
        "group": "headache",
        "trigger": r"headache|worst headache|thunderclap|\bha\b|head pain",
        "must_not_miss": [
            ("Subarachnoid hemorrhage", "I60.9"),
            ("Bacterial meningitis", "G00.9"),
            ("Giant cell (temporal) arteritis", "M31.6"),
            ("Cerebral venous thrombosis", "I63.6"),
        ],
    },
    {
        "group": "dyspnea",
        "trigger": r"shortness of breath|sob\b|dyspnea|trouble breathing|can'?t breathe",
        "must_not_miss": [
            ("Pulmonary embolism", "I26.99"),
            ("Tension pneumothorax", "J93.0"),
            ("Acute pulmonary edema", "J81.0"),
            ("Anaphylaxis", "T78.2XXA"),
        ],
    },
    {
        "group": "peds_fever",
        "trigger": r"fever\b.*(infant|baby|newborn|< ?3 ?mo|months old|weeks old)|(infant|baby|newborn).*fever",
        "must_not_miss": [
            ("Neonatal sepsis", "P36.9"),
            ("Bacterial meningitis", "G00.9"),
            ("Herpsimplex (HSV) disease of newborn", "P35.2"),
        ],
    },
    {
        "group": "testicular_torsion",
        "trigger": r"testic|scrotal|testes|groin pain.*(boy|male|man)",
        "must_not_miss": [("Testicular torsion", "N44.00")],
    },
    {
        "group": "ectopic",
        "trigger": r"vagin.*bleed|pregnan.*bleed|missed period.*bleed|pelvic pain.*pregnan",
        "must_not_miss": [("Ectopic pregnancy", "O00.9")],
    },
    {
        "group": "cauda_equina",
        "trigger": r"back pain.*(numb|weak|saddle|incontinen|retention)|saddle anesthesia",
        "must_not_miss": [
            ("Cauda equina syndrome", "G83.4"),
            ("Spinal cord compression", "G95.20"),
        ],
    },
    {
        "group": "airway",
        "trigger": r"sore throat.*(drool|stridor|trismus)|stridor|drooling.*throat",
        "must_not_miss": [
            ("Epiglottitis", "J05.10"),
            ("Retropharyngeal abscess", "J39.0"),
        ],
    },
]


def match_red_flags(text: str) -> list[dict[str, Any]]:
    """Scan free text against the red-flag canon.

    Returns a de-duplicated list of ``{diagnosis, icd10, group, must_not_miss}``
    for every don't-miss diagnosis whose chief-complaint group keyword fired.
    Shared by ``generate_deep`` here and by ``ddx_v2``.
    """
    haystack = (text or "").lower()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for canon in RED_FLAG_LIBRARY:
        if not re.search(canon["trigger"], haystack):
            continue
        for dx, icd in canon["must_not_miss"]:
            key = dx.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "diagnosis": dx,
                    "icd10": icd,
                    "group": canon["group"],
                    "must_not_miss": True,
                }
            )
    return out


# ---------------------------------------------------------------------------
# Adaptive-prediction-set conformal calibration
# ---------------------------------------------------------------------------
def conformal_sets(differential: list[dict[str, Any]]) -> dict[str, Any]:
    """Adaptive prediction sets at 90% / 95% coverage.

    Nonconformity score for each diagnosis is ``1 - weight`` (lower weight =>
    more "non-conforming"). We rank by weight descending and accumulate
    normalized weight until the target coverage (1 - alpha) is reached — the
    smallest prefix of diagnoses whose cumulative weight covers the threshold.
    The diagnosis that crosses the threshold is included so the set is a true
    cover. This is the adaptive-prediction-set (APS) construction.

    Returns ``{set_90, set_95, nonconformity, threshold_90, threshold_95}``.
    """
    if not differential:
        return {
            "set_90": [],
            "set_95": [],
            "nonconformity": [],
            "threshold_90": 0.90,
            "threshold_95": 0.95,
        }

    weights = [max(0.0, float(d.get("weight", 0.0) or 0.0)) for d in differential]
    total = sum(weights) or 1.0
    norm = [w / total for w in weights]

    paired = sorted(
        zip(differential, norm), key=lambda pair: pair[1], reverse=True
    )

    nonconformity = [
        {
            "diagnosis": d.get("diagnosis", ""),
            "weight": round(w, 4),
            "score": round(1.0 - w, 4),
        }
        for d, w in paired
    ]

    def _aps(target: float) -> list[str]:
        chosen: list[str] = []
        cum = 0.0
        for d, w in paired:
            chosen.append(d.get("diagnosis", ""))
            cum += w
            if cum >= target - 1e-9:
                break
        return [name for name in chosen if name]

    set_90 = _aps(0.90)
    set_95 = _aps(0.95)
    if not set_90 and paired:
        set_90 = [paired[0][0].get("diagnosis", "")]
    if not set_95 and paired:
        set_95 = [paired[0][0].get("diagnosis", "")]

    return {
        "set_90": set_90,
        "set_95": set_95,
        "nonconformity": nonconformity,
        "threshold_90": 0.90,
        "threshold_95": 0.95,
    }


def counterfactual_prompts(differential: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic counterfactual questions seeded from the top of the Ddx.

    These are the "what would change my mind" prompts a senior clinician asks.
    The LLM also returns its own counterfactuals; these guarantee a baseline
    even when the model omits them. Each entry:
    ``{question, discriminates, why}``.
    """
    top = [d.get("diagnosis", "") for d in differential[:3] if d.get("diagnosis")]
    prompts: list[dict[str, Any]] = []
    if len(top) >= 2:
        prompts.append(
            {
                "question": f"What single finding best discriminates {top[0]} from {top[1]}?",
                "discriminates": top[:2],
                "why": "Resolves the leading two contenders before committing workup.",
            }
        )
    if len(top) >= 3:
        prompts.append(
            {
                "question": f"What discriminates the top 3 ({', '.join(top)})?",
                "discriminates": top,
                "why": "Identifies the one test that collapses the differential fastest.",
            }
        )
    must_miss = [d.get("diagnosis", "") for d in differential if d.get("must_not_miss")]
    if must_miss:
        prompts.append(
            {
                "question": f"What finding would let me safely rule OUT {must_miss[0]}?",
                "discriminates": [must_miss[0]],
                "why": "Don't-miss diagnosis — needs an explicit rule-out, not just a low rank.",
            }
        )
    return prompts


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
_SYSTEM_DEEP = """You are an experienced ED attending generating a differential \
diagnosis (Ddx) draft from a patient intake. The clinician verifies before acting.

Output JSON ONLY (no preamble, no markdown fence):
{
  "differential": [
    {
      "diagnosis": "short Dx name (e.g. 'Acute appendicitis')",
      "icd10": "best-guess ICD-10 code (e.g. K35.80) or empty",
      "weight": 0.0-1.0,
      "supporting": ["feature from the case that argues FOR this Dx", "..."],
      "refuting": ["feature absent or arguing AGAINST this Dx", "..."],
      "discriminator": "the single best test/maneuver to confirm or exclude this Dx",
      "reasoning": "1-2 sentence clinical rationale tying the case to this Dx",
      "must_not_miss": false
    }
  ],
  "counterfactuals": [
    {
      "question": "what additional finding would meaningfully change the ranking?",
      "discriminates": ["Dx A", "Dx B"],
      "why": "what that finding resolves"
    }
  ]
}

Rules:
- Return 3-5 differential entries, ordered by weight (highest first).
- weight = your normalized pretest probability across the list; weights should sum to ~1.0.
- "must_not_miss" = true ONLY for life/limb-threatening Dx (MI, PE, AAA, sepsis, stroke,
  ectopic, dissection, etc) that have at least one supporting feature.
- supporting / refuting: 1-3 short clinical phrases each, drawn DIRECTLY from the
  transcript / vitals / hx given. Never invent findings.
- "discriminator": one concrete next step (test, imaging, exam maneuver) — not a list.
- counterfactuals: 2-4 entries on what would change the ranking.
- Use the chief complaint as anchor. Only list Dx with at least one supporting feature.
- If the visit is clearly low-acuity non-pharmacologic (med refill, paperwork), return
  {"differential": [], "counterfactuals": []}.
"""


def _build_user_prompt(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None,
    followup_qa: list[dict] | None,
    photo_analysis: dict[str, Any] | None,
    vitals: dict[str, Any] | None,
) -> str:
    parts = [
        f'Transcript:\n"""\n{transcript.strip()[:8000]}\n"""',
        f"ESI: {esi_level}",
    ]
    if medical_info:
        parts.append(f"Medical info: {format_medical_info(medical_info)}")
    if followup_qa:
        try:
            from services.followups import format_qa_for_prompts

            qa = format_qa_for_prompts(followup_qa)
        except Exception:
            qa = ""
        if qa:
            parts.append(f"Follow-up Q&A:\n{qa}")
    if photo_analysis and photo_analysis.get("description"):
        parts.append(f"Photo: {photo_analysis['description']}")
    if vitals:
        v = ", ".join(f"{k}={val}" for k, val in vitals.items() if val is not None)
        if v:
            parts.append(f"Bedside vitals: {v}")
    parts.append("Return the JSON object now.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Deep generation
# ---------------------------------------------------------------------------
def generate_deep(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
    chief_complaint: str = "",
) -> dict[str, Any]:
    """Glass-grade differential.

    Returns ``{differential, conformal, red_flags, counterfactuals}``.

    - ``differential``: ranked, each with weight / supporting / refuting /
      discriminator / reasoning / must_not_miss.
    - ``conformal``: adaptive prediction sets (set_90 / set_95) with the
      per-diagnosis nonconformity scores (1 - weight).
    - ``red_flags``: don't-miss diagnoses matched from the canonical library
      against the transcript + chief complaint.
    - ``counterfactuals``: "what discriminates the top 3?" style prompts —
      LLM-supplied entries merged with a deterministic baseline.
    """
    empty: dict[str, Any] = {
        "differential": [],
        "conformal": conformal_sets([]),
        "red_flags": [],
        "counterfactuals": [],
    }
    if not settings.anthropic_api_key:
        return empty

    diff: list[dict[str, Any]] = []
    llm_counterfactuals: list[dict[str, Any]] = []
    try:
        prompt = _build_user_prompt(
            transcript, esi_level, medical_info, followup_qa, photo_analysis, vitals
        )
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1600,
            system=_SYSTEM_DEEP,
            messages=[{"role": "user", "content": prompt}],
            purpose="differential",
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        diff, llm_counterfactuals = _parse_deep(raw)
    except Exception as e:  # noqa: BLE001 - decision support must degrade gracefully
        log.exception("Deep differential generation failed: %s", e)
        return empty

    # Anchor red flags from the canon and fold any missing ones into the Ddx.
    red_flags = match_red_flags(f"{transcript} {chief_complaint}")
    diff = _merge_red_flags(diff, red_flags)

    conformal = conformal_sets(diff)

    # Merge LLM counterfactuals with the deterministic baseline, de-duped.
    counterfactuals = _merge_counterfactuals(
        llm_counterfactuals, counterfactual_prompts(diff)
    )

    return {
        "differential": diff,
        "conformal": conformal,
        "red_flags": red_flags,
        "counterfactuals": counterfactuals,
    }


def _merge_red_flags(
    diff: list[dict[str, Any]], red_flags: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fold canonical don't-miss diagnoses into the Ddx if the LLM omitted them.

    Existing entries that match a red flag are marked ``must_not_miss``. Missing
    ones are appended with a low weight so they surface without dominating the
    ranking; the clinician still sees them in ``red_flags`` regardless.
    """
    by_name = {d.get("diagnosis", "").lower(): d for d in diff}
    for rf in red_flags:
        key = rf["diagnosis"].lower()
        if key in by_name:
            by_name[key]["must_not_miss"] = True
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
                    "surfaced from the red-flag library, not yet supported by the case."
                ),
                "must_not_miss": True,
            }
        )
    return diff


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


def _parse_deep(raw: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the deep JSON object. Returns ``(differential, counterfactuals)``."""
    text = raw.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return [], []
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [], []
    if not isinstance(obj, dict):
        return [], []

    cleaned: list[dict[str, Any]] = []
    for item in obj.get("differential") or []:
        if not isinstance(item, dict):
            continue
        dx = str(item.get("diagnosis", "")).strip()
        if not dx:
            continue
        try:
            weight = float(item.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        cleaned.append(
            {
                "diagnosis": dx,
                "icd10": str(item.get("icd10", "")).strip(),
                "weight": max(0.0, min(1.0, weight)),
                "supporting": _str_list(item.get("supporting") or item.get("rule_in")),
                "refuting": _str_list(item.get("refuting") or item.get("rule_out")),
                "discriminator": str(item.get("discriminator", "")).strip(),
                "reasoning": str(item.get("reasoning", "")).strip(),
                "must_not_miss": bool(item.get("must_not_miss")),
            }
        )
        if len(cleaned) >= 6:
            break

    counterfactuals: list[dict[str, Any]] = []
    for item in obj.get("counterfactuals") or []:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        counterfactuals.append(
            {
                "question": q,
                "discriminates": _str_list(item.get("discriminates")),
                "why": str(item.get("why", "")).strip(),
            }
        )

    cleaned.sort(key=lambda d: d.get("weight", 0.0), reverse=True)
    return cleaned, counterfactuals


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:4]


def _weight_to_likelihood(weight: float) -> str:
    if weight >= 0.45:
        return "high"
    if weight >= 0.18:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------
def generate(
    transcript: str,
    esi_level: int,
    medical_info: dict[str, Any] | None = None,
    followup_qa: list[dict] | None = None,
    photo_analysis: dict[str, Any] | None = None,
    vitals: dict[str, Any] | None = None,
) -> list[dict]:
    """Legacy entry point — returns the flat ``list[dict]`` shape.

    Wraps :func:`generate_deep` and projects each diagnosis onto the legacy
    keys consumed by ``routers/intake.py`` (serialized to the ``differential``
    column) and the downstream ``workup`` / ``disposition`` services
    (``diagnosis`` / ``likelihood``). The richer fields are passed through too
    so existing readers keep working while new readers can opt into depth.
    """
    deep = generate_deep(
        transcript,
        esi_level,
        medical_info=medical_info,
        followup_qa=followup_qa,
        photo_analysis=photo_analysis,
        vitals=vitals,
    )
    out: list[dict] = []
    for d in deep["differential"]:
        weight = float(d.get("weight", 0.0) or 0.0)
        out.append(
            {
                "diagnosis": d["diagnosis"],
                "icd10": d.get("icd10", ""),
                "likelihood": _weight_to_likelihood(weight),
                "rule_in": d.get("supporting", []),
                "rule_out": d.get("refuting", []),
                "must_not_miss": bool(d.get("must_not_miss")),
                # passthrough depth for new readers — legacy callers ignore these
                "weight": weight,
                "discriminator": d.get("discriminator", ""),
                "reasoning": d.get("reasoning", ""),
            }
        )
    return out
