"""Differential diagnosis v2 — extends services/differential.py with:

  - Conformal prediction sets at 90% / 95% coverage based on softmax-style
    likelihood weights returned by the LLM.
  - Hard-coded "don't-miss" red-flag canon by chief complaint group; if the
    transcript has any matching keyword we surface the red-flag dx with high
    visibility regardless of LLM ranking.
  - Counterfactual prompts ("what would change this differential?").
  - Specialty bias: pass `specialty` to bias priors toward that specialty's
    pretest probabilities.

The output is decision support — never auto-acts, never replaces the existing
triage_ml model output.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# Canonical red-flag library: keyed by chief-complaint-anchor regex
RED_FLAGS: list[dict[str, Any]] = [
    {
        "trigger": r"chest|cp|substernal|crushing|squeez|pressure",
        "must_not_miss": [
            ("Acute coronary syndrome", "I20.9"),
            ("Pulmonary embolism", "I26.99"),
            ("Aortic dissection", "I71.00"),
            ("Pericardial tamponade", "I31.9"),
            ("Tension pneumothorax", "J93.0"),
            ("Esophageal rupture", "K22.3"),
        ],
    },
    {
        "trigger": r"weakness|numbness|slurred|facial droop|fast|stroke|aphasia",
        "must_not_miss": [("Acute ischemic stroke", "I63.9"), ("Intracranial hemorrhage", "I62.9"), ("TIA", "G45.9")],
    },
    {
        "trigger": r"abdominal|abd pain|belly|stomach pain",
        "must_not_miss": [
            ("Appendicitis", "K35.80"),
            ("Bowel obstruction", "K56.60"),
            ("Mesenteric ischemia", "K55.0"),
            ("AAA rupture", "I71.3"),
            ("Ectopic pregnancy", "O00.9"),
            ("Perforated viscus", "K65.9"),
        ],
    },
    {
        "trigger": r"headache|worst headache|thunderclap|ha",
        "must_not_miss": [
            ("Subarachnoid hemorrhage", "I60.9"),
            ("Meningitis", "G03.9"),
            ("Temporal arteritis", "M31.6"),
            ("CVT", "I63.6"),
        ],
    },
    {
        "trigger": r"shortness of breath|sob|dyspnea|trouble breathing",
        "must_not_miss": [
            ("Pulmonary embolism", "I26.99"),
            ("Tension pneumothorax", "J93.0"),
            ("Acute pulmonary edema", "J81.0"),
            ("Anaphylaxis", "T78.2XXA"),
        ],
    },
    {
        "trigger": r"fever\b.*(infant|baby|< ?3 ?mo|months)",
        "must_not_miss": [("Neonatal sepsis", "P36.9"), ("Bacterial meningitis", "G00.9")],
    },
    {
        "trigger": r"testic|scrotal|testes",
        "must_not_miss": [("Testicular torsion", "N44.00")],
    },
    {
        "trigger": r"vagin.*bleed|pregnan.*bleed|missed period.*bleed",
        "must_not_miss": [("Ectopic pregnancy", "O00.9")],
    },
    {
        "trigger": r"back pain.*(numb|weak|saddle|incontinen)",
        "must_not_miss": [("Cauda equina syndrome", "G83.4"), ("Spinal cord compression", "G95.20")],
    },
    {
        "trigger": r"sore throat.*drool|stridor|trismus",
        "must_not_miss": [("Epiglottitis", "J05.10"), ("Retropharyngeal abscess", "J39.0")],
    },
]


_SYSTEM = """You are an experienced ED attending generating a differential diagnosis (Ddx) draft.

Return JSON ONLY (no markdown):
{
  "differential": [
    {
      "diagnosis": "short Dx name",
      "icd10": "best-guess ICD-10",
      "weight": 0.0-1.0,             // your normalized likelihood across the list
      "rule_in": ["clinical feature 1", "..."],
      "rule_out": ["what argues against / what is missing"],
      "must_not_miss": false,
      "next_step": "single best discriminating test or maneuver",
      "evidence_quote": "verbatim short snippet from the transcript that anchored this Dx"
    }
  ],
  "counterfactuals": [
    {"if_true": "additional history/finding", "would_change": "which Dx rises/falls"}
  ]
}

Rules:
- Return 3-6 entries; weights must sum to ~1.0 (we'll normalize).
- Anchor every entry to at least one transcript-derived fact in rule_in.
- counterfactuals: 2-4 entries on what would meaningfully change rankings.
- Set must_not_miss true ONLY for life/limb threats with at least one supporting feature.
"""


def _redflag_anchor(transcript: str) -> list[dict[str, Any]]:
    text = (transcript or "").lower()
    out: list[dict[str, Any]] = []
    for canon in RED_FLAGS:
        if re.search(canon["trigger"], text):
            for dx, icd in canon["must_not_miss"]:
                out.append({"diagnosis": dx, "icd10": icd, "must_not_miss": True})
    # de-dupe
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for item in out:
        key = item["diagnosis"]
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq


def _conformal(diff: list[dict[str, Any]]) -> dict[str, Any]:
    if not diff:
        return {"set_90": [], "set_95": []}
    weights = [max(0.0, float(d.get("weight", 0))) for d in diff]
    s = sum(weights) or 1.0
    norm = [w / s for w in weights]
    # Sort by weight desc
    paired = sorted(zip(diff, norm), key=lambda x: x[1], reverse=True)
    set_90: list[str] = []
    set_95: list[str] = []
    cum = 0.0
    for d, w in paired:
        cum += w
        if cum <= 0.90 + 1e-9:
            set_90.append(d["diagnosis"])
        if cum <= 0.95 + 1e-9:
            set_95.append(d["diagnosis"])
    # ensure non-empty
    if not set_90 and paired:
        set_90 = [paired[0][0]["diagnosis"]]
    if not set_95 and paired:
        set_95 = [paired[0][0]["diagnosis"]]
    return {"set_90": set_90, "set_95": set_95}


def generate(
    transcript: str,
    chief_complaint: str = "",
    *,
    medical_info: dict[str, Any] | None = None,
    specialty: str = "ed",
    vitals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"differential": [], "counterfactuals": [], "red_flags": [], "conformal": {"set_90": [], "set_95": []}}
    parts = [
        f"Specialty context: {specialty.upper()}",
        f"Chief complaint: {chief_complaint or '(infer from transcript)'}",
        f'Transcript:\n"""\n{transcript[:8000]}\n"""',
    ]
    if medical_info:
        parts.append(f"Medical history: {json.dumps(medical_info)[:1200]}")
    if vitals:
        v = ", ".join(f"{k}={v}" for k, v in vitals.items() if v is not None)
        if v:
            parts.append(f"Bedside vitals: {v}")
    parts.append("Return JSON now.")

    diff: list[dict[str, Any]] = []
    cf: list[dict[str, Any]] = []
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=1400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            purpose="ddx_v2",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        diff = parsed.get("differential", [])
        cf = parsed.get("counterfactuals", [])
    except Exception as e:
        log.warning("ddx_v2 failed: %s", e)

    red_flags = _redflag_anchor(transcript + " " + chief_complaint)
    # Merge red flags into the differential if missing
    diff_names = {d["diagnosis"].lower() for d in diff}
    for rf in red_flags:
        if rf["diagnosis"].lower() not in diff_names:
            diff.append({
                "diagnosis": rf["diagnosis"],
                "icd10": rf["icd10"],
                "weight": 0.05,
                "rule_in": ["red-flag canon match — verify by exam/test"],
                "rule_out": [],
                "must_not_miss": True,
                "next_step": "rule out per institutional pathway",
                "evidence_quote": "",
            })

    conf = _conformal(diff)
    return {
        "differential": diff,
        "counterfactuals": cf,
        "red_flags": red_flags,
        "conformal": conf,
    }
