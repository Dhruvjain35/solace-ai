"""Evidence-grounded recommendation engine — OpenEvidence-grade hybrid RAG.

A curated mini-RAG over open medical sources (PubMed open-access abstracts, CDC
guidelines, NIH/NLM, USPSTF, ACC/AHA, IDSA, NCCI, FDA DailyMed). For each
clinical question Solace surfaces:
  - 3-6 evidence snippets retrieved by a hybrid retriever
  - Each snippet carries a resolvable primary-source citation (PMID/DOI/PMCID/URL)
    plus the source license, exposed via Citation.resolvable_url
  - An LLM synthesizes a short clinical answer that ONLY uses the retrieved snippets
  - If retrieval finds nothing relevant, refuses-and-flags rather than hallucinating

Retrieval design
----------------
Hybrid retrieval fuses two independent rankers:

  1. Sparse BM25-lite — an Okapi-BM25-flavored lexical scorer with tag/title
     field boosts. Pure-Python, zero-dependency; this is the *always-available*
     path and the graceful-degradation fallback.
  2. Dense TF-IDF — a scikit-learn ``TfidfVectorizer`` (1-2 grams, sublinear TF)
     fitted once over the corpus and cached per warm container via ``lru_cache``.
     Query/doc cosine similarity gives a second ranking that captures term
     co-occurrence the bag-of-words BM25 misses.

The two rankings are merged with **Reciprocal Rank Fusion** (RRF):
``score(d) = sum_r 1 / (k_rrf + rank_r(d))``. RRF needs no score calibration
between the two very different scales. The fused candidate set is then passed
through a **lexical cross-encoder proxy** rerank: a query-document scorer that
rewards exact phrase hits, tag coverage and title overlap — a cheap stand-in
for a true cross-encoder that keeps the top results tightly on-topic.

If scikit-learn is unavailable, or the dense index fails to build, retrieval
degrades gracefully to BM25-only with no behavior change for callers.

Pluggable corpus
----------------
Set ``EVIDENCE_CORPUS_PATH`` to a JSONL file (one snippet object per line) to
extend the bundled seed corpus at runtime. Records are merged with the seed and
de-duplicated by citation id / url.

The public surface is stable for callers in routers/clinical_ai.py:
  - ``search(query, *, k=6) -> list[dict]``
  - ``answer(question, *, k=6) -> dict``
  - ``ground(recommendation, context="", *, k=6) -> dict``   (new — for ddx_v2 / em_coding)
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = settings.model_utility

# RRF constant — standard value from Cormack et al. 2009. Larger -> flatter fusion.
_RRF_K = 60
# Candidate pool size before the cross-encoder-proxy rerank.
_CANDIDATE_POOL = 12


# --------------------------------------------------------------------------- #
# Citation — every snippet resolves to a primary source.
# --------------------------------------------------------------------------- #
@dataclass
class Citation:
    """A resolvable pointer to a primary source.

    Exactly one identifier scheme is canonical; ``resolvable_url`` derives a
    dereferenceable URL from whichever identifier is present, preferring the
    most stable scheme (DOI > PMID > PMCID > raw URL).
    """

    citation_id: str            # e.g. "PMID:34709879", "DOI:10.1016/j.jacc.2021.07.053"
    source: str                 # publishing body / journal
    year: int
    title: str
    license: str = "unknown"    # e.g. "public-domain", "CC-BY", "open-access", "guideline-fair-use"
    url: str = ""               # explicit URL when no stable identifier exists

    @property
    def scheme(self) -> str:
        cid = self.citation_id.upper()
        for s in ("DOI", "PMCID", "PMID", "URL"):
            if cid.startswith(s + ":"):
                return s
        return "URL"

    @property
    def resolvable_url(self) -> str:
        """A dereferenceable URL for this citation, derived from its identifier."""
        cid = self.citation_id.strip()
        body = cid.split(":", 1)[1].strip() if ":" in cid else cid
        scheme = self.scheme
        if scheme == "DOI":
            return f"https://doi.org/{body}"
        if scheme == "PMID":
            return f"https://pubmed.ncbi.nlm.nih.gov/{body}/"
        if scheme == "PMCID":
            pmcid = body if body.upper().startswith("PMC") else f"PMC{body}"
            return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
        return self.url or body

    def as_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "scheme": self.scheme,
            "source": self.source,
            "year": self.year,
            "title": self.title,
            "license": self.license,
            "resolvable_url": self.resolvable_url,
        }


@dataclass
class EvidenceSnippet:
    title: str
    body: str
    source: str
    year: int
    url: str
    tags: list[str]
    citation_id: str = ""        # PMID/DOI/PMCID/URL identifier
    license: str = "open-access"

    def __post_init__(self) -> None:
        # Backfill a citation id from the URL if none was supplied.
        if not self.citation_id:
            self.citation_id = _infer_citation_id(self.url)

    @property
    def citation(self) -> Citation:
        return Citation(
            citation_id=self.citation_id,
            source=self.source,
            year=self.year,
            title=self.title,
            license=self.license,
            url=self.url,
        )


def _infer_citation_id(url: str) -> str:
    """Best-effort extraction of a stable identifier from a source URL."""
    u = (url or "").strip()
    if not u:
        return "URL:"
    m = re.search(r"10\.\d{4,9}/[^\s\"<>]+", u)
    if m:
        return f"DOI:{m.group(0).rstrip('/')}"
    m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", u)
    if m:
        return f"PMID:{m.group(1)}"
    m = re.search(r"/(PMC\d+)", u, re.IGNORECASE)
    if m:
        return f"PMCID:{m.group(1).upper()}"
    return f"URL:{u}"


# --------------------------------------------------------------------------- #
# Seed corpus — cleared sources, public domain / open-access / guideline.
# --------------------------------------------------------------------------- #
_SEED_CORPUS: list[EvidenceSnippet] = [
    EvidenceSnippet(
        title="2023 ACC/AHA Chest Pain Guideline — initial evaluation",
        body="In adults presenting with acute chest pain, obtain a 12-lead ECG within 10 minutes. "
             "Use a clinical risk score (HEART, EDACS, or TIMI) plus high-sensitivity troponin to "
             "stratify ACS risk. Patients with HEART score 0-3 and two negative hs-troponins are "
             "low risk and can be discharged with outpatient follow-up.",
        source="J Am Coll Cardiol — Gulati et al.", year=2023,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2021.07.053",
        tags=["chest pain", "acs", "heart score", "troponin"],
        citation_id="DOI:10.1016/j.jacc.2021.07.053", license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="USPSTF screening — colorectal cancer (2021 update)",
        body="USPSTF recommends colorectal cancer screening starting at age 45 for average-risk "
             "adults. Acceptable modalities: colonoscopy every 10 years, FIT annually, FIT-DNA "
             "every 1-3 years, flexible sigmoidoscopy every 5 years, or CT colonography every 5 years.",
        source="USPSTF", year=2021,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/colorectal-cancer-screening",
        tags=["colorectal", "screening", "uspstf", "colonoscopy", "fit"],
        license="public-domain",
    ),
    EvidenceSnippet(
        title="USPSTF — breast cancer screening (2024)",
        body="USPSTF recommends biennial screening mammography for women aged 40 to 74. Women "
             "with dense breasts may benefit from supplemental imaging; this is an individualized "
             "discussion. Screening should continue until life expectancy is less than 10 years.",
        source="USPSTF", year=2024,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/breast-cancer-screening",
        tags=["breast", "screening", "mammogram", "uspstf"],
        license="public-domain",
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
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="2017 ACC/AHA — hypertension management",
        body="BP target <130/80 in adults with confirmed HTN. First-line agents: thiazide-type "
             "diuretic, CCB, ACE-I, or ARB (alone or in combination). Avoid combining ACE-I "
             "with ARB. In Black adults without CKD or HF, prefer thiazide or CCB as first-line.",
        source="J Am Coll Cardiol — Whelton et al.", year=2017,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2017.11.006",
        tags=["hypertension", "htn", "blood pressure", "ace", "arb", "thiazide"],
        citation_id="DOI:10.1016/j.jacc.2017.11.006", license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="Surviving Sepsis Campaign 2021 — adult sepsis bundle",
        body="Hour-1 bundle: lactate, blood cultures before antibiotics, broad-spectrum "
             "antibiotics, 30 mL/kg crystalloid for hypotension or lactate >=4 mmol/L, "
             "vasopressors for MAP <65 after fluids. Reassess lactate q2-4h.",
        source="Crit Care Med — Evans et al.", year=2021,
        url="https://journals.lww.com/ccmjournal/Abstract/2021/11000/Surviving_Sepsis_Campaign__International.21.aspx",
        tags=["sepsis", "lactate", "antibiotics", "fluids"],
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="IDSA — uncomplicated cystitis in women",
        body="First-line for uncomplicated cystitis: nitrofurantoin 100 mg PO BID x 5 days, "
             "TMP-SMX DS BID x 3 days (if local resistance <20%), or fosfomycin 3 g x1 single "
             "dose. Avoid fluoroquinolones for uncomplicated UTI.",
        source="Clin Infect Dis — IDSA Gupta et al.", year=2011,
        url="https://academic.oup.com/cid/article/52/5/e103/388286",
        tags=["uti", "cystitis", "nitrofurantoin", "tmp-smx", "fosfomycin"],
        citation_id="DOI:10.1093/cid/ciq257", license="open-access",
    ),
    EvidenceSnippet(
        title="CHEST — ACCP DVT/PE management guideline",
        body="For confirmed proximal DVT or PE, anticoagulation with apixaban, rivaroxaban, "
             "edoxaban, or dabigatran is preferred over warfarin in patients without cancer or "
             "renal/hepatic disease. Treat 3 months minimum; extend if unprovoked or persistent risk.",
        source="CHEST — Stevens et al.", year=2021,
        url="https://journal.chestnet.org/article/S0012-3692(21)01506-3/fulltext",
        tags=["dvt", "pe", "vte", "anticoagulation", "doac", "apixaban"],
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="USPSTF — depression screening",
        body="Screen all adults for depression; staff-assisted depression-care supports must be "
             "in place. PHQ-2 then PHQ-9 is a common workflow. Treat or refer for psychotherapy "
             "and/or pharmacotherapy when indicated.",
        source="USPSTF", year=2023,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/depression-and-suicide-risk-in-adults-screening",
        tags=["depression", "phq-9", "phq-2", "screening", "uspstf"],
        license="public-domain",
    ),
    EvidenceSnippet(
        title="ACOG — postpartum hypertension",
        body="Postpartum BP >=160/110 mmHg or signs of severe features warrant urgent treatment "
             "with labetalol, hydralazine, or oral nifedipine. Continue surveillance for at least "
             "72 hours postpartum and follow-up within 7-10 days.",
        source="Obstet Gynecol — ACOG", year=2020,
        url="https://www.acog.org/clinical/clinical-guidance/practice-bulletin/articles/2020/06/gestational-hypertension-and-preeclampsia",
        tags=["postpartum", "hypertension", "preeclampsia", "labetalol"],
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="2023 GINA — asthma management",
        body="Track 1 (preferred): low-dose ICS-formoterol as both maintenance and reliever (MART "
             "regimen). Step up by symptoms and lung function. Avoid SABA-only therapy. Confirm "
             "diagnosis with spirometry and bronchodilator response.",
        source="Global Initiative for Asthma", year=2023,
        url="https://ginasthma.org/2023-gina-main-report/",
        tags=["asthma", "ics", "formoterol", "saba"],
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="2023 GOLD — COPD management",
        body="Initial therapy guided by symptom (mMRC, CAT) and exacerbation risk. LAMA or "
             "LABA monotherapy for low-risk; LABA+LAMA combination for higher-risk; add ICS only "
             "if frequent exacerbations or eosinophils >=300.",
        source="GOLD", year=2023,
        url="https://goldcopd.org/2023-gold-report-2/",
        tags=["copd", "lama", "laba", "ics", "exacerbation"],
        license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="AHA stroke guideline — tPA window",
        body="Alteplase 0.9 mg/kg IV (max 90 mg) within 4.5 hours of last-known-well in eligible "
             "ischemic stroke. Endovascular thrombectomy up to 24 hours in select large-vessel "
             "occlusions with favorable imaging.",
        source="Stroke — Powers et al.", year=2019,
        url="https://www.ahajournals.org/doi/10.1161/STR.0000000000000211",
        tags=["stroke", "tpa", "alteplase", "thrombectomy"],
        citation_id="DOI:10.1161/STR.0000000000000211", license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="CDC — adult immunization schedule",
        body="Annual influenza for all adults; Tdap or Td every 10 years (one Tdap if not "
             "previously); zoster (Shingrix) two-dose at age 50+; pneumococcal (PCV20 or PCV15+PPSV23) "
             "at age 65+ or earlier with risk; HPV through age 26, shared decision 27-45.",
        source="CDC ACIP", year=2024,
        url="https://www.cdc.gov/vaccines/schedules/hcp/imz/adult.html",
        tags=["immunization", "vaccine", "flu", "tdap", "shingrix", "hpv", "pneumococcal"],
        license="public-domain",
    ),
    EvidenceSnippet(
        title="2022 ACC/AHA atrial fibrillation",
        body="In non-valvular Afib, calculate CHA2DS2-VASc; anticoagulate at 2+ in men or 3+ "
             "in women (or 1+ at clinician discretion). DOAC preferred over warfarin except in "
             "moderate-severe mitral stenosis or mechanical valve. Rate or rhythm control is reasonable.",
        source="J Am Coll Cardiol — Joglar et al.", year=2024,
        url="https://www.jacc.org/doi/10.1016/j.jacc.2023.08.017",
        tags=["afib", "atrial fibrillation", "anticoagulation", "cha2ds2", "doac"],
        citation_id="DOI:10.1016/j.jacc.2023.08.017", license="guideline-fair-use",
    ),
    EvidenceSnippet(
        title="USPSTF — lung cancer screening",
        body="Annual low-dose CT for adults age 50-80 with 20+ pack-year smoking history who "
             "currently smoke or quit within past 15 years. Stop screening if life expectancy <10 "
             "years or willing/able to undergo curative lung surgery.",
        source="USPSTF", year=2021,
        url="https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/lung-cancer-screening",
        tags=["lung cancer", "ldct", "screening", "smoker", "uspstf"],
        license="public-domain",
    ),
]


# --------------------------------------------------------------------------- #
# Pluggable corpus — EVIDENCE_CORPUS_PATH JSONL merged with the seed.
# --------------------------------------------------------------------------- #
def _load_jsonl_corpus(path: str) -> list[EvidenceSnippet]:
    """Load extra snippets from a JSONL file. Bad lines are skipped, not fatal."""
    out: list[EvidenceSnippet] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for ln, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw or raw.startswith("#"):
                    continue
                try:
                    rec = json.loads(raw)
                    out.append(
                        EvidenceSnippet(
                            title=str(rec["title"]),
                            body=str(rec["body"]),
                            source=str(rec.get("source", "unknown")),
                            year=int(rec.get("year", 0)),
                            url=str(rec.get("url", "")),
                            tags=[str(t).lower() for t in rec.get("tags", [])],
                            citation_id=str(rec.get("citation_id", "")),
                            license=str(rec.get("license", "open-access")),
                        )
                    )
                except Exception as e:  # noqa: BLE001 — one bad line must not kill the corpus
                    log.warning("evidence_rag: skipping bad JSONL line %d in %s: %s", ln, path, e)
    except FileNotFoundError:
        log.warning("evidence_rag: EVIDENCE_CORPUS_PATH=%s not found, using seed only", path)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence_rag: failed to read EVIDENCE_CORPUS_PATH=%s: %s", path, e)
    return out


@lru_cache(maxsize=1)
def _corpus() -> tuple[EvidenceSnippet, ...]:
    """Seed corpus merged with the optional external JSONL, de-duped by citation id.

    Cached for the lifetime of the warm container.
    """
    merged: list[EvidenceSnippet] = list(_SEED_CORPUS)
    extra_path = (
        os.environ.get("EVIDENCE_CORPUS_PATH")
        or getattr(settings, "evidence_corpus_path", None)
    )
    if extra_path:
        merged.extend(_load_jsonl_corpus(extra_path))

    seen: set[str] = set()
    deduped: list[EvidenceSnippet] = []
    for s in merged:
        key = (s.citation_id or s.url or s.title).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
    log.info("evidence_rag: corpus ready — %d snippets (seed=%d)", len(deduped), len(_SEED_CORPUS))
    return tuple(deduped)


# Backwards-compatible alias — some callers / tooling reference CORPUS directly.
CORPUS: tuple[EvidenceSnippet, ...] = _corpus()


# --------------------------------------------------------------------------- #
# Tokenization
# --------------------------------------------------------------------------- #
def _tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9-]+", (text or "").lower()) if len(w) > 2]


# --------------------------------------------------------------------------- #
# Sparse ranker — Okapi-BM25-lite with field boosts.
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _bm25_stats() -> dict[str, Any]:
    """Pre-compute IDF and document lengths for the corpus. Cached per container."""
    corpus = _corpus()
    docs: list[list[str]] = []
    df: dict[str, int] = {}
    for s in corpus:
        toks = _tokenize(s.title + " " + s.body + " " + " ".join(s.tags))
        docs.append(toks)
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n = max(1, len(corpus))
    avgdl = sum(len(d) for d in docs) / n if docs else 1.0
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    return {"docs": docs, "idf": idf, "avgdl": avgdl}


def _bm25_lite(query: str, k: int) -> list[tuple[int, float]]:
    """Okapi BM25 over the corpus with tag/title field boosts.

    Returns ``(corpus_index, score)`` pairs, score-descending. This is the
    always-available path: it needs no third-party library.
    """
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return []
    corpus = _corpus()
    stats = _bm25_stats()
    idf, avgdl = stats["idf"], stats["avgdl"]
    b, k1 = 0.75, 1.5
    scored: list[tuple[int, float]] = []
    for i, s in enumerate(corpus):
        body_tokens = _tokenize(s.title + " " + s.body)
        title_tokens = set(_tokenize(s.title))
        tags = {t.lower() for t in s.tags}
        dl = len(body_tokens) or 1
        score = 0.0
        for q in q_tokens:
            tf = body_tokens.count(q)
            if tf:
                w = idf.get(q, 0.5)
                score += w * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
            if q in tags:
                score += 4.0
            if q in title_tokens:
                score += 2.0
        if score > 0:
            scored.append((i, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


# --------------------------------------------------------------------------- #
# Dense ranker — scikit-learn TF-IDF cosine similarity.
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _dense_index() -> Any:
    """Build the TF-IDF vectorizer + document matrix once per warm container.

    Returns ``(vectorizer, doc_matrix)`` or ``None`` if scikit-learn is missing
    or the build fails — callers must treat ``None`` as "dense unavailable" and
    fall back to BM25-only.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except Exception as e:  # noqa: BLE001
        log.warning("evidence_rag: scikit-learn unavailable, dense retrieval disabled: %s", e)
        return None
    try:
        corpus = _corpus()
        # Tags are repeated so they carry extra weight in the vector space.
        docs = [
            f"{s.title} {s.title} {s.body} {' '.join(s.tags)} {' '.join(s.tags)}"
            for s in corpus
        ]
        vec = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            sublinear_tf=True,
            min_df=1,
            stop_words="english",
            token_pattern=r"(?u)\b[a-z0-9][a-z0-9-]+\b",
        )
        matrix = vec.fit_transform(docs)
        log.info("evidence_rag: dense TF-IDF index built — %s", matrix.shape)
        return (vec, matrix)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence_rag: dense index build failed, falling back to BM25: %s", e)
        return None


def _dense_search(query: str, k: int) -> list[tuple[int, float]]:
    """Cosine-similarity ranking over the TF-IDF index. Empty if dense unavailable."""
    index = _dense_index()
    if index is None or not (query or "").strip():
        return []
    try:
        from sklearn.metrics.pairwise import cosine_similarity

        vec, matrix = index
        q_vec = vec.transform([query])
        sims = cosine_similarity(q_vec, matrix)[0]
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(sims) if s > 0.0),
            key=lambda x: x[1],
            reverse=True,
        )
        return ranked[:k]
    except Exception as e:  # noqa: BLE001
        log.warning("evidence_rag: dense search failed, BM25-only this call: %s", e)
        return []


# --------------------------------------------------------------------------- #
# Reciprocal Rank Fusion
# --------------------------------------------------------------------------- #
def _rrf_fuse(*rankings: list[tuple[int, float]], k_rrf: int = _RRF_K) -> list[tuple[int, float]]:
    """Fuse multiple ``(index, score)`` rankings with Reciprocal Rank Fusion.

    RRF combines rankings of incompatible score scales without calibration:
    ``score(d) = sum over rankings of 1 / (k_rrf + rank(d))``.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, (idx, _score) in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k_rrf + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


# --------------------------------------------------------------------------- #
# Cross-encoder proxy rerank
# --------------------------------------------------------------------------- #
def _cross_encoder_proxy(query: str, idx: int) -> float:
    """Lexical stand-in for a cross-encoder relevance score in [0, ~10].

    Rewards exact phrase containment, tag coverage and title overlap — the
    signals a true query-document cross-encoder would learn, computed cheaply.
    """
    s = _corpus()[idx]
    q = (query or "").lower()
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return 0.0
    tags = {t.lower() for t in s.tags}
    title_tokens = set(_tokenize(s.title))
    body_l = s.body.lower()

    tag_cov = len(q_tokens & tags) / max(1, len(q_tokens))
    title_cov = len(q_tokens & title_tokens) / max(1, len(q_tokens))
    # Phrase hit — reward when a multi-word tag appears verbatim in the query.
    phrase = sum(1.0 for t in tags if " " in t and t in q)
    # Body term coverage.
    body_tokens = set(_tokenize(body_l))
    body_cov = len(q_tokens & body_tokens) / max(1, len(q_tokens))
    return 4.0 * tag_cov + 2.5 * title_cov + 1.5 * phrase + 2.0 * body_cov


# --------------------------------------------------------------------------- #
# Hybrid retrieval
# --------------------------------------------------------------------------- #
def _hybrid_retrieve(query: str, k: int) -> list[tuple[EvidenceSnippet, float, dict[str, Any]]]:
    """Sparse + dense fused with RRF, then cross-encoder-proxy reranked.

    Returns ``(snippet, final_score, debug)`` tuples. Degrades to BM25-only when
    the dense index is unavailable.
    """
    if not (query or "").strip():
        return []
    sparse = _bm25_lite(query, k=_CANDIDATE_POOL)
    dense = _dense_search(query, k=_CANDIDATE_POOL)

    if dense:
        fused = _rrf_fuse(sparse, dense)
        retrieval_mode = "hybrid-rrf"
    else:
        # Graceful degradation — BM25-only, but still RRF-normalized for a clean scale.
        fused = _rrf_fuse(sparse)
        retrieval_mode = "bm25-only"

    if not fused:
        return []

    sparse_rank = {idx: r for r, (idx, _) in enumerate(sparse, 1)}
    dense_rank = {idx: r for r, (idx, _) in enumerate(dense, 1)}

    # Rerank the fused candidate pool with the cross-encoder proxy.
    reranked: list[tuple[EvidenceSnippet, float, dict[str, Any]]] = []
    corpus = _corpus()
    for idx, rrf_score in fused[:_CANDIDATE_POOL]:
        ce = _cross_encoder_proxy(query, idx)
        # Final score blends fused recall signal with the precision-oriented reranker.
        final = rrf_score * 100.0 + ce
        reranked.append((
            corpus[idx],
            final,
            {
                "retrieval_mode": retrieval_mode,
                "rrf_score": round(rrf_score, 5),
                "rerank_score": round(ce, 3),
                "sparse_rank": sparse_rank.get(idx),
                "dense_rank": dense_rank.get(idx),
            },
        ))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:k]


def _snippet_to_dict(i: int, s: EvidenceSnippet, score: float, debug: dict[str, Any]) -> dict[str, Any]:
    c = s.citation
    return {
        "index": i,
        "title": s.title,
        "body": s.body,
        "source": s.source,
        "year": s.year,
        "url": s.url,
        "tags": s.tags,
        "score": round(score, 3),
        "citation_id": c.citation_id,
        "license": c.license,
        "citation": c.as_dict(),
        "retrieval": debug,
    }


# --------------------------------------------------------------------------- #
# LLM synthesis prompt
# --------------------------------------------------------------------------- #
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

_GROUND_SYSTEM = """You are a clinical fact-checker. You are given a candidate recommendation and a \
set of retrieved evidence snippets. Decide whether the recommendation is SUPPORTED by the evidence.

Rules:
- Only use the supplied snippets. Never use outside knowledge.
- "supported" means the evidence directly backs the recommendation's clinical claim.
- "partial" means the evidence is related but does not fully establish the claim.
- "unsupported" means no snippet backs it (or the evidence contradicts it).

Return JSON ONLY:
{
  "verdict": "supported" | "partial" | "unsupported",
  "confidence": 0.0-1.0,
  "supporting_indices": [1, 3],
  "rationale": "one or two sentences citing snippet indices"
}
"""


def _llm_json(system: str, user: str, *, purpose: str, max_tokens: int = 900) -> dict[str, Any] | None:
    """Call Claude expecting a JSON object back. Returns None on any failure."""
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            purpose=purpose,
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence_rag: LLM call (%s) failed: %s", purpose, e)
        return None


# --------------------------------------------------------------------------- #
# Public API — stable for routers/clinical_ai.py callers.
# --------------------------------------------------------------------------- #
def search(query: str, *, k: int = 6) -> list[dict[str, Any]]:
    """Retrieve top-k evidence snippets for the query via hybrid retrieval.

    Each result carries a resolvable citation and a ``retrieval`` debug block.
    """
    hits = _hybrid_retrieve(query, k=k)
    return [
        _snippet_to_dict(i + 1, s, score, debug)
        for i, (s, score, debug) in enumerate(hits)
    ]


def answer(question: str, *, k: int = 6) -> dict[str, Any]:
    """Search then synthesize. Refuses to answer if no evidence is retrieved."""
    snippets = search(question, k=k)
    if not snippets:
        return {
            "question": question,
            "snippets": [],
            "answer": "No evidence found in the curated Solace evidence base for this question. "
                      "Please consult primary literature or specialty references.",
            "key_recommendations": [],
            "uncertainty": "no_retrieval_match",
        }
    if not claude.available():
        return {
            "question": question,
            "snippets": snippets,
            "answer": "(LLM unavailable; see retrieved evidence below)",
            "key_recommendations": [],
            "uncertainty": "llm_unavailable",
        }

    snippet_block = "\n\n".join(
        f"[{s['index']}] {s['title']} ({s['source']}, {s['year']})\n{s['body']}\n"
        f"Citation: {s['citation_id']} -> {s['citation']['resolvable_url']}"
        for s in snippets
    )
    user = f"Question: {question}\n\nEvidence snippets:\n{snippet_block}\n\nReturn JSON now."
    out = _llm_json(_SYNTH_SYSTEM, user, purpose="evidence_rag")
    if out is None:
        out = {"answer": "(synthesis failed)", "key_recommendations": [], "uncertainty": "synthesis_error"}
    return {"question": question, "snippets": snippets, **out}


def ground(recommendation: str, context: str = "", *, k: int = 6) -> dict[str, Any]:
    """Verify a candidate recommendation against retrieved evidence.

    This is the interface ddx_v2 / em_coding call before surfacing a
    recommendation: it retrieves supporting evidence and asks the LLM whether
    the recommendation is actually backed by it.

    Returns::

        {
          "grounded": bool,                # True iff verdict is "supported"
          "verdict": "supported"|"partial"|"unsupported",
          "confidence": float,             # 0.0-1.0
          "citations": [Citation.as_dict(), ...],   # resolvable supporting citations
          "supporting_evidence": [snippet dict, ...],
          "rationale": str,
        }

    Degrades safely: with no retrieval it returns grounded=False; with no LLM it
    returns a heuristic verdict from retrieval overlap so callers still get a
    usable signal.
    """
    query = f"{recommendation} {context}".strip()
    snippets = search(query, k=k)

    if not snippets:
        return {
            "grounded": False,
            "verdict": "unsupported",
            "confidence": 0.0,
            "citations": [],
            "supporting_evidence": [],
            "rationale": "No evidence retrieved from the Solace evidence base for this recommendation.",
        }

    # No LLM — heuristic grounding from the top reranker score.
    if not claude.available():
        top = snippets[0]
        rerank = top.get("retrieval", {}).get("rerank_score", 0.0) or 0.0
        if rerank >= 5.0:
            verdict, conf = "supported", 0.6
        elif rerank >= 2.0:
            verdict, conf = "partial", 0.4
        else:
            verdict, conf = "unsupported", 0.2
        support = [s for s in snippets if (s.get("retrieval", {}).get("rerank_score", 0.0) or 0.0) >= 2.0]
        return {
            "grounded": verdict == "supported",
            "verdict": verdict,
            "confidence": conf,
            "citations": [s["citation"] for s in support],
            "supporting_evidence": support,
            "rationale": "Heuristic grounding (LLM unavailable): verdict from lexical rerank overlap.",
        }

    snippet_block = "\n\n".join(
        f"[{s['index']}] {s['title']} ({s['source']}, {s['year']})\n{s['body']}"
        for s in snippets
    )
    ctx_line = f"\nClinical context: {context}" if context else ""
    user = (
        f"Candidate recommendation: {recommendation}{ctx_line}\n\n"
        f"Evidence snippets:\n{snippet_block}\n\nReturn JSON now."
    )
    out = _llm_json(_GROUND_SYSTEM, user, purpose="evidence_ground", max_tokens=500)
    if out is None:
        return {
            "grounded": False,
            "verdict": "unsupported",
            "confidence": 0.0,
            "citations": [],
            "supporting_evidence": [],
            "rationale": "Grounding check failed (synthesis error).",
        }

    verdict = str(out.get("verdict", "unsupported")).lower()
    try:
        confidence = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    indices = {int(i) for i in out.get("supporting_indices", []) if str(i).strip().isdigit()}
    support = [s for s in snippets if s["index"] in indices] or (
        snippets[:2] if verdict in ("supported", "partial") else []
    )
    return {
        "grounded": verdict == "supported",
        "verdict": verdict,
        "confidence": confidence,
        "citations": [s["citation"] for s in support],
        "supporting_evidence": support,
        "rationale": str(out.get("rationale", "")),
    }
