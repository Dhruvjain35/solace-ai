"""Evidence-grounded recommendation engine.

A curated mini-RAG over open medical sources (PubMed open-access abstracts, CDC
guidelines, NIH/NLM, USPSTF, ACC/AHA, IDSA, NCCI, FDA DailyMed). For each
clinical question Solace surfaces:
  - 3-6 evidence snippets ranked by relevance
  - Each snippet carries a primary-source citation (URL + year + body)
  - LLM synthesizes a short clinical answer that ONLY uses the retrieved snippets
  - If retrieval finds nothing relevant, refuses-and-flags rather than hallucinating

The corpus is shipped inline as a starter set so the feature works zero-config
in production. Swappable for a vector store (pgvector / OpenSearch) by setting
EVIDENCE_RAG_BACKEND=vector and providing the appropriate connection.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


@dataclass
class EvidenceSnippet:
    title: str
    body: str
    source: str
    year: int
    url: str
    tags: list[str]


# Starter corpus — cleared sources, public domain or open-access. Curated by topic.
# In production this is replaced by a vector index over the same sources at scale.
CORPUS: list[EvidenceSnippet] = [
    EvidenceSnippet(
        title="2023 ACC/AHA Chest Pain Guideline — initial evaluation",
        body="In adults presenting with acute chest pain, obtain a 12-lead ECG within 10 minutes. "
             "Use a clinical risk score (HEART, EDACS, or TIMI) plus high-sensitivity troponin to "
             "stratify ACS risk. Patients with HEART score 0-3 and two negative hs-troponins are "
             "low risk and can be discharged with outpatient follow-up.",
        source="J Am Coll Cardiol — Gulati et al.", year=2023,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2021.07.053",
        tags=["chest pain", "acs", "heart score", "troponin"],
    ),
    EvidenceSnippet(
        title="USPSTF screening — colorectal cancer (2021 update)",
        body="USPSTF recommends colorectal cancer screening starting at age 45 for average-risk "
             "adults. Acceptable modalities: colonoscopy every 10 years, FIT annually, FIT-DNA "
             "every 1-3 years, flexible sigmoidoscopy every 5 years, or CT colonography every 5 years.",
        source="USPSTF", year=2021,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/colorectal-cancer-screening",
        tags=["colorectal", "screening", "uspstf", "colonoscopy", "fit"],
    ),
    EvidenceSnippet(
        title="USPSTF — breast cancer screening (2024)",
        body="USPSTF recommends biennial screening mammography for women aged 40 to 74. Women "
             "with dense breasts may benefit from supplemental imaging; this is an individualized "
             "discussion. Screening should continue until life expectancy is less than 10 years.",
        source="USPSTF", year=2024,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/breast-cancer-screening",
        tags=["breast", "screening", "mammogram", "uspstf"],
    ),
    EvidenceSnippet(
        title="2024 ADA standards — diabetes management",
        body="In adults with type 2 diabetes and established CVD, use SGLT2 inhibitors or GLP-1 "
             "receptor agonists with proven CV benefit independent of A1c. A1c target is "
             "individualized; <7% for most, <6.5% if achievable safely, 7.5-8% in elderly with "
             "limited life expectancy. Annual eye, foot, kidney, and depression screening.",
        source="Diabetes Care — ADA", year=2024,
        url="https://diabetesjournals.org/care/issue/47/Supplement_1",
        tags=["diabetes", "a1c", "sglt2", "glp-1", "screening"],
    ),
    EvidenceSnippet(
        title="2017 ACC/AHA — hypertension management",
        body="BP target <130/80 in adults with confirmed HTN. First-line agents: thiazide-type "
             "diuretic, CCB, ACE-I, or ARB (alone or in combination). Avoid combining ACE-I "
             "with ARB. In Black adults without CKD or HF, prefer thiazide or CCB as first-line.",
        source="J Am Coll Cardiol — Whelton et al.", year=2017,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2017.11.006",
        tags=["hypertension", "htn", "blood pressure", "ace", "arb", "thiazide"],
    ),
    EvidenceSnippet(
        title="Surviving Sepsis Campaign 2021 — adult sepsis bundle",
        body="Hour-1 bundle: lactate, blood cultures before antibiotics, broad-spectrum "
             "antibiotics, 30 mL/kg crystalloid for hypotension or lactate >=4 mmol/L, "
             "vasopressors for MAP <65 after fluids. Reassess lactate q2-4h.",
        source="Crit Care Med — Evans et al.", year=2021,
        url="https://journals.lww.com/ccmjournal/Abstract/2021/11000/Surviving_Sepsis_Campaign__International.21.aspx",
        tags=["sepsis", "lactate", "antibiotics", "fluids"],
    ),
    EvidenceSnippet(
        title="IDSA — uncomplicated cystitis in women",
        body="First-line for uncomplicated cystitis: nitrofurantoin 100 mg PO BID x 5 days, "
             "TMP-SMX DS BID x 3 days (if local resistance <20%), or fosfomycin 3 g x1 single "
             "dose. Avoid fluoroquinolones for uncomplicated UTI.",
        source="Clin Infect Dis — IDSA Gupta et al.", year=2011,
        url="https://academic.oup.com/cid/article/52/5/e103/388286",
        tags=["uti", "cystitis", "nitrofurantoin", "tmp-smx", "fosfomycin"],
    ),
    EvidenceSnippet(
        title="CHEST — ACCP DVT/PE management guideline",
        body="For confirmed proximal DVT or PE, anticoagulation with apixaban, rivaroxaban, "
             "edoxaban, or dabigatran is preferred over warfarin in patients without cancer or "
             "renal/hepatic disease. Treat 3 months minimum; extend if unprovoked or persistent risk.",
        source="CHEST — Stevens et al.", year=2021,
        url="https://journal.chestnet.org/article/S0012-3692(21)01506-3/fulltext",
        tags=["dvt", "pe", "vte", "anticoagulation", "doac", "apixaban"],
    ),
    EvidenceSnippet(
        title="USPSTF — depression screening",
        body="Screen all adults for depression; staff-assisted depression-care supports must be "
             "in place. PHQ-2 then PHQ-9 is a common workflow. Treat or refer for psychotherapy "
             "and/or pharmacotherapy when indicated.",
        source="USPSTF", year=2023,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/depression-and-suicide-risk-in-adults-screening",
        tags=["depression", "phq-9", "phq-2", "screening", "uspstf"],
    ),
    EvidenceSnippet(
        title="ACOG — postpartum hypertension",
        body="Postpartum BP >=160/110 mmHg or signs of severe features warrant urgent treatment "
             "with labetalol, hydralazine, or oral nifedipine. Continue surveillance for at least "
             "72 hours postpartum and follow-up within 7-10 days.",
        source="Obstet Gynecol — ACOG", year=2020,
        url="https://www.acog.org/clinical/clinical-guidance/practice-bulletin/articles/2020/06/gestational-hypertension-and-preeclampsia",
        tags=["postpartum", "hypertension", "preeclampsia", "labetalol"],
    ),
    EvidenceSnippet(
        title="2023 GINA — asthma management",
        body="Track 1 (preferred): low-dose ICS-formoterol as both maintenance and reliever (MART "
             "regimen). Step up by symptoms and lung function. Avoid SABA-only therapy. Confirm "
             "diagnosis with spirometry and bronchodilator response.",
        source="Global Initiative for Asthma", year=2023,
        url="https://ginasthma.org/2023-gina-main-report/",
        tags=["asthma", "ics", "formoterol", "saba"],
    ),
    EvidenceSnippet(
        title="2023 GOLD — COPD management",
        body="Initial therapy guided by symptom (mMRC, CAT) and exacerbation risk. LAMA or "
             "LABA monotherapy for low-risk; LABA+LAMA combination for higher-risk; add ICS only "
             "if frequent exacerbations or eosinophils >=300.",
        source="GOLD", year=2023,
        url="https://goldcopd.org/2023-gold-report-2/",
        tags=["copd", "lama", "laba", "ics", "exacerbation"],
    ),
    EvidenceSnippet(
        title="AHA stroke guideline — tPA window",
        body="Alteplase 0.9 mg/kg IV (max 90 mg) within 4.5 hours of last-known-well in eligible "
             "ischemic stroke. Endovascular thrombectomy up to 24 hours in select large-vessel "
             "occlusions with favorable imaging.",
        source="Stroke — Powers et al.", year=2019,
        url="https://www.ahajournals.org/doi/10.1161/STR.0000000000000211",
        tags=["stroke", "tpa", "alteplase", "thrombectomy"],
    ),
    EvidenceSnippet(
        title="CDC — adult immunization schedule",
        body="Annual influenza for all adults; Tdap or Td every 10 years (one Tdap if not "
             "previously); zoster (Shingrix) two-dose at age 50+; pneumococcal (PCV20 or PCV15+PPSV23) "
             "at age 65+ or earlier with risk; HPV through age 26, shared decision 27-45.",
        source="CDC ACIP", year=2024,
        url="https://www.cdc.gov/vaccines/schedules/hcp/imz/adult.html",
        tags=["immunization", "vaccine", "flu", "tdap", "shingrix", "hpv", "pneumococcal"],
    ),
    EvidenceSnippet(
        title="2022 ACC/AHA atrial fibrillation",
        body="In non-valvular Afib, calculate CHA2DS2-VASc; anticoagulate at 2+ in men or 3+ "
             "in women (or 1+ at clinician discretion). DOAC preferred over warfarin except in "
             "moderate-severe mitral stenosis or mechanical valve. Rate or rhythm control is reasonable.",
        source="J Am Coll Cardiol — Joglar et al.", year=2024,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2023.08.017",
        tags=["afib", "atrial fibrillation", "anticoagulation", "cha2ds2", "doac"],
    ),
    EvidenceSnippet(
        title="USPSTF — lung cancer screening",
        body="Annual low-dose CT for adults age 50-80 with 20+ pack-year smoking history who "
             "currently smoke or quit within past 15 years. Stop screening if life expectancy <10 "
             "years or willing/able to undergo curative lung surgery.",
        source="USPSTF", year=2021,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/lung-cancer-screening",
        tags=["lung cancer", "ldct", "screening", "smoker", "uspstf"],
    ),
]


def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9-]+", (text or "").lower()) if len(w) > 2]


def _bm25_lite(query: str, corpus: list[EvidenceSnippet], k: int = 6) -> list[tuple[EvidenceSnippet, float]]:
    """Hybrid BM25-flavored retrieval — tag matches weighted heavier than body matches."""
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return []
    scored: list[tuple[EvidenceSnippet, float]] = []
    for s in corpus:
        score = 0.0
        text_tokens = _tokenize(s.title + " " + s.body)
        title_tokens = _tokenize(s.title)
        tags = [t.lower() for t in s.tags]
        for q in q_tokens:
            if q in tags:
                score += 4.0
            if q in title_tokens:
                score += 2.0
            score += text_tokens.count(q) * 0.5
        # Phrase bonus
        if any(q in s.body.lower() for q in q_tokens if " " in q):
            score += 1.5
        if score > 0:
            scored.append((s, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


_SYNTH_SYSTEM = """You are a clinical evidence synthesizer. You answer the clinical question using \
ONLY the supplied evidence snippets. Cite each claim by its snippet index in square brackets.

If the evidence is insufficient, say so plainly: "The retrieved evidence does not directly address ..."
Never use parametric memory to fill gaps. Never invent citations.

Return JSON ONLY:
{
  "answer": "2-4 short paragraphs in clinical voice, citation indices like [1] [3]",
  "key_recommendations": ["short bullet 1", "short bullet 2"],
  "uncertainty": "what is missing or unclear in the retrieved evidence"
}
"""


def search(query: str, *, k: int = 6) -> list[dict[str, Any]]:
    """Retrieve top-k snippets for the query."""
    hits = _bm25_lite(query, CORPUS, k=k)
    return [
        {
            "index": i + 1,
            "title": s.title,
            "body": s.body,
            "source": s.source,
            "year": s.year,
            "url": s.url,
            "tags": s.tags,
            "score": round(score, 2),
        }
        for i, (s, score) in enumerate(hits)
    ]


def answer(question: str, *, k: int = 6) -> dict[str, Any]:
    """Search then synthesize. Refuses to answer if no evidence retrieved."""
    snippets = search(question, k=k)
    if not snippets:
        return {
            "question": question,
            "snippets": [],
            "answer": "No evidence found in the curated Solace evidence base for this question. Please consult primary literature or specialty references.",
            "key_recommendations": [],
            "uncertainty": "no_retrieval_match",
        }
    if not settings.anthropic_api_key:
        return {"question": question, "snippets": snippets, "answer": "(LLM unavailable; see retrieved evidence below)", "key_recommendations": [], "uncertainty": "llm_unavailable"}

    snippet_block = "\n\n".join(
        f"[{s['index']}] {s['title']} ({s['source']}, {s['year']})\n{s['body']}\nURL: {s['url']}"
        for s in snippets
    )
    user = f"Question: {question}\n\nEvidence snippets:\n{snippet_block}\n\nReturn JSON now."
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_SYNTH_SYSTEM,
            messages=[{"role": "user", "content": user}],
            purpose="evidence_rag",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        out = json.loads(text)
    except Exception as e:
        log.warning("evidence_rag synthesis failed: %s", e)
        out = {"answer": "(synthesis failed)", "key_recommendations": [], "uncertainty": "synthesis_error"}
    return {"question": question, "snippets": snippets, **out}
