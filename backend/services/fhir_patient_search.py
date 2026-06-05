"""Real FHIR patient search against a public SMART-on-FHIR sandbox.

Default backend is the SMART Health IT public sandbox at
https://launch.smarthealthit.org/v/r4/fhir — no registration, no auth,
Synthea-generated realistic patient population. Free for demos and
integration testing.

Production swap: set EHR_FHIR_BASE_URL + EHR_FHIR_ACCESS_TOKEN to point at
Epic / Cerner / Athena once SMART backend services + client-credentials grant
is configured. The function signatures here don't change.

Why this is the right call for Solace today:
  - Real FHIR R4 wire format (not a mock proxy) — proves the integration story
  - Synthea data has full longitudinal records: 5-10 years of encounters,
    realistic problem lists, med history, allergies — so a demo lookup actually
    pre-fills meaningful data
  - Zero ops setup — no client_id registration, no JWKS hosting, just HTTP

Operations:
  - Hard timeout: 6s for primary Patient search, 4s for each follow-on resource
  - Falls back to {} on any error — the patient intake flow continues regardless
  - Each fetch is logged with response time so we can spot sandbox latency
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from difflib import SequenceMatcher
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_FHIR_BASE = "https://launch.smarthealthit.org/v/r4/fhir"
SEARCH_TIMEOUT_S = 6.0
RESOURCE_TIMEOUT_S = 4.0

# --- Identity matching configuration ----------------------------------------------
# Patient-safety critical: a wrong-chart match can pre-fill an intake with the
# wrong allergies / meds / problem list. The decision engine below is biased
# toward NOT matching when there is any doubt. A miss is a recoverable demo
# annoyance; a false match is a clinical incident.
#
# Weighted scoring: each signal contributes points toward a 0.0-1.0 confidence.
# A candidate must clear MATCH_THRESHOLD *and* survive the hard-reject gates
# (DOB conflict, ambiguous top-two) to be returned. Otherwise the caller gets
# None and falls through to the next lookup path.
NAME_WEIGHT = 0.40
DOB_WEIGHT = 0.35
SEX_WEIGHT = 0.10
PHONE_WEIGHT = 0.10
MRN_WEIGHT = 0.05

# Minimum confidence to auto-accept a single candidate.
MATCH_THRESHOLD = 0.72
# Below this a candidate is rejected outright (no_match).
NO_MATCH_CEILING = 0.50
# Fuzzy name-similarity floor — below this names are treated as different people.
NAME_SIMILARITY_FLOOR = 0.80
# If the best and second-best candidates are within this confidence gap, the
# result is ambiguous and we refuse to guess.
AMBIGUITY_MARGIN = 0.12


def _base_url() -> str:
    return os.environ.get("EHR_FHIR_BASE_URL", DEFAULT_FHIR_BASE).rstrip("/")


def _auth_header() -> dict[str, str]:
    """Token comes from the SMART backend-services flow when wired against
    Epic/Cerner. Public SMART Health IT sandbox needs no auth, so empty dict is fine."""
    tok = os.environ.get("EHR_FHIR_ACCESS_TOKEN", "").strip()
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _client() -> httpx.Client:
    headers = {"Accept": "application/fhir+json", **_auth_header()}
    return httpx.Client(timeout=SEARCH_TIMEOUT_S, headers=headers)


# ----------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------


def match_by_demographics(
    *,
    given: str,
    family: str,
    birth_date: str = "",
    gender: str = "",
    phone: str = "",
) -> dict[str, Any] | None:
    """Search FHIR Patient by name + birthDate and run the identity decision
    engine over the candidates.

    Returns the normalized record (allergies, meds, conditions, prior visits
    already fetched) ONLY when the decision engine returns status == "matched".
    On "needs_review" or "no_match" — including the dangerous case where the
    only candidate's DOB conflicts with the supplied DOB — this returns None so
    the caller falls through to the next lookup path rather than writing to a
    wrong chart.

    `birth_date` should be YYYY-MM-DD when known.
    """
    given = (given or "").strip()
    family = (family or "").strip()
    if not given and not family:
        return None

    params: dict[str, str] = {"_count": "10"}
    if family:
        params["family"] = family
    if given:
        params["given"] = given
    if birth_date:
        params["birthdate"] = birth_date
    if gender:
        params["gender"] = gender.lower()

    bundle = _search("Patient", params)
    if not bundle:
        return None

    candidates = [
        (e.get("resource") or {})
        for e in (bundle.get("entry", []) or [])
        if (e.get("resource") or {}).get("resourceType") == "Patient"
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None

    query = {
        "given": given,
        "family": family,
        "birth_date": birth_date,
        "gender": gender,
        "phone": phone,
        "mrn": "",
    }
    decision = match_status(query, candidates)
    log.info(
        "FHIR demographic match: status=%s confidence=%.2f reason=%s",
        decision["status"], decision["confidence"], decision["reason"],
    )
    if decision["status"] != "matched" or decision["patient"] is None:
        return None

    return _enrich_patient(decision["patient"])


def match_by_member_id(member_id: str, provider_hint: str = "") -> dict[str, Any] | None:
    """Search FHIR Patient by insurance identifier.

    Insurance member_id is shared across a family plan: a spouse and children
    can all carry the same subscriber id. If the search returns more than one
    distinct Patient we CANNOT tell which family member is at the desk from the
    member_id alone — returning entries[0] would be a coin-flip wrong-chart
    risk. In that case this hardens to None and the caller falls through to a
    name+DOB lookup, which can actually disambiguate.

    A single unambiguous hit is still a free win.
    """
    member_id = (member_id or "").strip()
    if not member_id:
        return None
    bundle = _search("Patient", {"identifier": member_id, "_count": "5"})
    if not bundle:
        return None

    resources = [
        (e.get("resource") or {})
        for e in (bundle.get("entry", []) or [])
        if (e.get("resource") or {}).get("resourceType") == "Patient"
    ]
    resources = [r for r in resources if r]
    if not resources:
        return None

    # Collapse duplicates of the same logical Patient (same id).
    distinct: dict[str, dict[str, Any]] = {}
    for r in resources:
        rid = str(r.get("id") or id(r))
        distinct.setdefault(rid, r)

    if len(distinct) > 1:
        log.info(
            "FHIR member_id %s resolved to %d distinct patients (family plan) "
            "- refusing to guess, returning None",
            _redact_id(member_id), len(distinct),
        )
        return None

    return _enrich_patient(next(iter(distinct.values())))


# ----------------------------------------------------------------------------------
# Identity decision engine
# ----------------------------------------------------------------------------------


def match_status(query: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide whether any FHIR Patient candidate is the person described by
    `query`. Patient-safety critical — biased toward refusing to match.

    `query` keys (all optional, strings): given, family, birth_date, gender,
    phone, mrn. `candidates` is a list of raw FHIR Patient resources.

    Returns a dict:
      {
        "status":     "matched" | "needs_review" | "no_match",
        "confidence": float 0.0-1.0,        # confidence of the top candidate
        "reason":     str,                   # human-readable explanation
        "patient":    dict | None,           # the chosen FHIR Patient, or None
      }

    Hard-reject gates (any one forces a non-"matched" status):
      - top score below MATCH_THRESHOLD
      - DOB conflict: query DOB present and differs from candidate DOB
      - ambiguous top-two: best and runner-up within AMBIGUITY_MARGIN
    """
    if not candidates:
        return _decision("no_match", 0.0, "no candidates returned by FHIR", None)

    scored = [(_score_candidate(query, c), c) for c in candidates]
    # Sort by confidence descending; on ties keep input order (stable sort).
    scored.sort(key=lambda sc: sc[0]["confidence"], reverse=True)

    best_score, best_patient = scored[0]
    confidence = best_score["confidence"]

    # Gate 1 — DOB conflict on the top candidate. A wrong DOB means a wrong
    # person, full stop. Never match across a DOB mismatch.
    if best_score["dob_conflict"]:
        return _decision(
            "no_match", confidence,
            "top candidate's date of birth conflicts with the supplied DOB",
            None,
        )

    # Gate 2 — name too dissimilar. Even a strong DOB hit is not enough if the
    # name is a different person (DOB collisions happen).
    if best_score["name_similarity"] < NAME_SIMILARITY_FLOOR:
        return _decision(
            "no_match", confidence,
            f"best candidate name similarity {best_score['name_similarity']:.2f} "
            f"below floor {NAME_SIMILARITY_FLOOR}",
            None,
        )

    # Gate 3 — sub-threshold score.
    if confidence < NO_MATCH_CEILING:
        return _decision(
            "no_match", confidence,
            f"top confidence {confidence:.2f} below no-match ceiling {NO_MATCH_CEILING}",
            None,
        )
    if confidence < MATCH_THRESHOLD:
        return _decision(
            "needs_review", confidence,
            f"top confidence {confidence:.2f} below match threshold {MATCH_THRESHOLD} "
            "- weak evidence, clinician must confirm",
            None,
        )

    # Gate 4 — ambiguous top-two. If a runner-up is nearly as good, we cannot
    # safely pick one. Demand a clear winner.
    if len(scored) > 1:
        runner_up = scored[1][0]["confidence"]
        if not scored[1][0]["dob_conflict"] and (confidence - runner_up) < AMBIGUITY_MARGIN:
            return _decision(
                "needs_review", confidence,
                f"top two candidates are too close (gap "
                f"{confidence - runner_up:.2f} < {AMBIGUITY_MARGIN}) "
                "- ambiguous, clinician must confirm",
                None,
            )

    return _decision(
        "matched", confidence,
        f"unique high-confidence match ({best_score['reason']})",
        best_patient,
    )


def _decision(status: str, confidence: float, reason: str, patient: dict | None) -> dict[str, Any]:
    return {
        "status": status,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "patient": patient,
    }


def _score_candidate(query: dict[str, Any], patient: dict[str, Any]) -> dict[str, Any]:
    """Weighted similarity score for one FHIR Patient against the query.

    Returns a dict with the overall `confidence` (sum of weighted signals,
    renormalized over the signals that were actually evaluable), the raw
    `name_similarity`, a `dob_conflict` boolean, and a `reason` summary.
    """
    signals: list[str] = []
    earned = 0.0
    possible = 0.0

    # --- Name (fuzzy, accent-folded) ---
    q_name = _norm_name(f"{query.get('given', '')} {query.get('family', '')}")
    c_name = _norm_name(_candidate_name(patient))
    name_sim = _name_similarity(q_name, c_name) if (q_name and c_name) else 0.0
    if q_name and c_name:
        possible += NAME_WEIGHT
        earned += NAME_WEIGHT * name_sim
        signals.append(f"name~{name_sim:.2f}")

    # --- DOB (exact match only; partial/mismatch flagged) ---
    q_dob = (query.get("birth_date") or "").strip()
    c_dob = (patient.get("birthDate") or "").strip()
    dob_conflict = False
    if q_dob and c_dob:
        possible += DOB_WEIGHT
        if q_dob == c_dob:
            earned += DOB_WEIGHT
            signals.append("dob=exact")
        elif len(q_dob) >= 4 and len(c_dob) >= 4 and q_dob[:4] == c_dob[:4]:
            # Same birth year, different month/day — still a conflict for a
            # full date, but note the partial agreement.
            dob_conflict = True
            signals.append("dob!=conflict(year-only)")
        else:
            dob_conflict = True
            signals.append("dob!=conflict")

    # --- Sex / gender ---
    q_sex = _normalize_sex(query.get("gender", ""))
    c_sex = _normalize_sex(patient.get("gender", ""))
    if q_sex and c_sex and q_sex not in {"other"} and c_sex not in {"other"}:
        possible += SEX_WEIGHT
        if q_sex == c_sex:
            earned += SEX_WEIGHT
            signals.append("sex=match")
        else:
            signals.append("sex!=mismatch")

    # --- Phone (digits-only comparison, tolerant of formatting/country code) ---
    q_phone = _digits(query.get("phone", ""))
    c_phone = _digits(_best_phone(patient))
    if q_phone and c_phone:
        possible += PHONE_WEIGHT
        if _phone_match(q_phone, c_phone):
            earned += PHONE_WEIGHT
            signals.append("phone=match")
        else:
            signals.append("phone!=mismatch")

    # --- MRN (exact identifier value) ---
    q_mrn = (query.get("mrn") or "").strip().lower()
    c_mrn = _find_mrn(patient.get("identifier") or []).strip().lower()
    if q_mrn and c_mrn:
        possible += MRN_WEIGHT
        if q_mrn == c_mrn:
            earned += MRN_WEIGHT
            signals.append("mrn=match")
        else:
            signals.append("mrn!=mismatch")

    # Renormalize over the signals we could actually evaluate, so a missing
    # phone number does not silently cap the confidence at 0.90.
    confidence = (earned / possible) if possible > 0 else 0.0

    return {
        "confidence": confidence,
        "name_similarity": name_sim,
        "dob_conflict": dob_conflict,
        "reason": ", ".join(signals) or "no comparable signals",
    }


# ----------------------------------------------------------------------------------
# Matching primitives
# ----------------------------------------------------------------------------------


def _fold_accents(s: str) -> str:
    """Strip diacritics so 'José' matches 'Jose'."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _norm_name(s: str) -> str:
    """Lowercase, accent-fold, drop punctuation, collapse whitespace."""
    s = _fold_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _name_similarity(a: str, b: str) -> float:
    """Fuzzy name similarity in [0, 1] via difflib.

    Compares the full normalized strings and also a token-set comparison so
    that word-order swaps ('Smith John' vs 'John Smith') and middle-name
    presence/absence do not tank the score. Returns the better of the two.
    """
    if not a or not b:
        return 0.0
    whole = SequenceMatcher(None, a, b).ratio()
    tok_a = " ".join(sorted(a.split()))
    tok_b = " ".join(sorted(b.split()))
    token = SequenceMatcher(None, tok_a, tok_b).ratio()
    return max(whole, token)


def _candidate_name(patient: dict[str, Any]) -> str:
    return _hn_to_string(_first_name(patient.get("name") or []))


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _phone_match(a: str, b: str) -> bool:
    """Phone equality tolerant of country codes — compare the last 10 digits."""
    if not a or not b:
        return False
    return a[-10:] == b[-10:] if (len(a) >= 10 and len(b) >= 10) else a == b


def _best_phone(patient: dict[str, Any]) -> str:
    """Prefer a mobile number, else any phone telecom."""
    telecoms = patient.get("telecom") or []
    for t in telecoms:
        if (t.get("system") or "").lower() == "phone" and (t.get("use") or "").lower() == "mobile":
            return str(t.get("value", ""))
    return _first_telecom(telecoms, "phone")


def _redact_id(value: str) -> str:
    """Mask an identifier for logs — never log a full member_id."""
    v = (value or "").strip()
    if len(v) <= 4:
        return "*" * len(v)
    return f"{'*' * (len(v) - 4)}{v[-4:]}"


# ----------------------------------------------------------------------------------
# Internal — Patient enrichment + FHIR fetch
# ----------------------------------------------------------------------------------


def _enrich_patient(patient: dict[str, Any]) -> dict[str, Any]:
    """Given a FHIR Patient, fetch allergies + meds + problems + encounters in
    parallel and return the normalized Solace record shape."""
    patient_id = patient.get("id")
    if not patient_id:
        return _normalize_patient(patient, {}, {}, {}, {})

    fetches = {
        "allergies": ("AllergyIntolerance", {"patient": patient_id, "_count": "20"}),
        "meds": ("MedicationRequest", {"patient": patient_id, "status": "active", "_count": "20"}),
        "conditions": ("Condition", {"patient": patient_id, "clinical-status": "active", "_count": "20"}),
        "encounters": ("Encounter", {"patient": patient_id, "_count": "5", "_sort": "-date"}),
    }
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_key = {pool.submit(_search, kind, params): key for key, (kind, params) in fetches.items()}
        for fut in as_completed(future_to_key):
            key = future_to_key[fut]
            try:
                results[key] = fut.result() or {}
            except Exception as e:  # noqa: BLE001
                log.info("FHIR enrich %s failed: %s", key, e)
                results[key] = {}

    return _normalize_patient(
        patient,
        results.get("allergies", {}),
        results.get("meds", {}),
        results.get("conditions", {}),
        results.get("encounters", {}),
    )


def _search(resource_type: str, params: dict[str, str]) -> dict[str, Any] | None:
    url = f"{_base_url()}/{resource_type}"
    try:
        with _client() as c:
            resp = c.get(url, params=params, timeout=RESOURCE_TIMEOUT_S if resource_type != "Patient" else SEARCH_TIMEOUT_S)
            if resp.status_code != 200:
                log.info("FHIR %s -> %d (%s)", resource_type, resp.status_code, resp.text[:160])
                return None
            return resp.json()
    except httpx.TimeoutException:
        log.info("FHIR %s timed out", resource_type)
        return None
    except Exception as e:  # noqa: BLE001
        log.info("FHIR %s error: %s", resource_type, e)
        return None


# ----------------------------------------------------------------------------------
# Normalization
# ----------------------------------------------------------------------------------


def _normalize_patient(
    patient: dict[str, Any],
    allergies_bundle: dict[str, Any],
    meds_bundle: dict[str, Any],
    conds_bundle: dict[str, Any],
    encounters_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Reshape a FHIR Patient + related resources into Solace's EHR record shape.

    Solace's internal shape matches what the dashboard EHRPanel + intake prefill
    expect: a flat dict with allergies/medications/conditions/prior_visits arrays.
    """
    name = _hn_to_string(_first_name(patient.get("name") or []))
    dob = patient.get("birthDate") or ""
    gender = patient.get("gender") or ""
    mrn = _find_mrn(patient.get("identifier") or [])
    phone = _first_telecom(patient.get("telecom") or [], "phone")

    record = {
        "mrn": mrn or patient.get("id", ""),
        "fhir_id": patient.get("id", ""),
        "name": name,
        "dob": dob,
        "age": _age_from_dob(dob),
        "sex": _normalize_sex(gender),
        "phone": phone,
        "blood_type": "—",
        "height_cm": None,
        "weight_kg": None,
        "bmi": None,
        "primary_care_provider": _pcp_from_general_practitioner(patient.get("generalPractitioner") or []),
        "insurance": "",
        "emergency_contact": _emergency_contact(patient.get("contact") or []),
        "allergies": _allergies(allergies_bundle),
        "medications": _medications(meds_bundle),
        "conditions": _conditions(conds_bundle),
        "family_history": [],
        "social_history": "",
        "immunizations": [],
        "prior_visits": _prior_visits(encounters_bundle),
        "source": "fhir_sandbox",
    }
    return record


# ----------------------------------------------------------------------------------
# FHIR field helpers
# ----------------------------------------------------------------------------------


def _first_name(names: list[dict]) -> dict:
    if not names:
        return {}
    for n in names:
        if (n.get("use") or "").lower() == "official":
            return n
    return names[0]


def _hn_to_string(n: dict) -> str:
    if not isinstance(n, dict):
        return ""
    if n.get("text"):
        return str(n["text"])
    given = " ".join(n.get("given") or [])
    family = n.get("family") or ""
    parts = [p for p in (given, family) if p]
    return " ".join(parts).strip()


def _find_mrn(identifiers: list[dict]) -> str:
    for ident in identifiers:
        type_codings = ((ident.get("type") or {}).get("coding") or [])
        for c in type_codings:
            if c.get("code") in {"MR", "MRN"} or "medical record" in str(c.get("display", "")).lower():
                return str(ident.get("value", ""))
    return identifiers[0].get("value", "") if identifiers else ""


def _first_telecom(telecoms: list[dict], system: str) -> str:
    for t in telecoms:
        if (t.get("system") or "").lower() == system:
            return str(t.get("value", ""))
    return ""


def _pcp_from_general_practitioner(gps: list[dict]) -> str:
    if not gps:
        return ""
    return str(gps[0].get("display") or gps[0].get("reference") or "")


def _emergency_contact(contacts: list[dict]) -> str:
    for c in contacts:
        relationship = ((c.get("relationship") or [{}])[0].get("coding") or [{}])[0].get("display", "")
        name = _hn_to_string(c.get("name") or {})
        phone = _first_telecom(c.get("telecom") or [], "phone")
        if name:
            parts = [name]
            if relationship:
                parts.append(f"({relationship})")
            if phone:
                parts.append(phone)
            return " ".join(parts)
    return ""


def _age_from_dob(dob: str) -> int | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", dob)
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        today = date.today()
        return today.year - y - ((today.month, today.day) < (mo, d))
    except Exception:  # noqa: BLE001
        return None


def _normalize_sex(g: str) -> str:
    g = (g or "").lower()
    if g in {"m", "male"}:
        return "male"
    if g in {"f", "female"}:
        return "female"
    return g or "other"


def _allergies(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        substance = (r.get("code") or {}).get("text") or _coding_display(r.get("code") or {})
        if substance and substance.lower() not in {"none", "nka", "nkda"}:
            out.append(substance)
    return out or []


def _medications(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        med = (r.get("medicationCodeableConcept") or {}).get("text") or _coding_display(r.get("medicationCodeableConcept") or {})
        if med:
            out.append(med)
    return out


def _conditions(bundle: dict) -> list[str]:
    out: list[str] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        cond = (r.get("code") or {}).get("text") or _coding_display(r.get("code") or {})
        if cond:
            out.append(cond)
    return out


def _prior_visits(bundle: dict) -> list[dict]:
    out: list[dict] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        period = r.get("period") or {}
        type_text = ""
        if r.get("type"):
            type_text = (r["type"][0] or {}).get("text") or _coding_display((r["type"][0] or {}))
        reason = ""
        rc = r.get("reasonCode") or []
        if rc:
            reason = rc[0].get("text") or _coding_display(rc[0])
        out.append({
            "date": (period.get("start") or "")[:10],
            "type": type_text or "Encounter",
            "facility": _ref_display(r.get("serviceProvider")),
            "chief_complaint": reason or "—",
            "disposition": str(r.get("status") or ""),
            "note": "",
        })
    return out


def _coding_display(field: dict) -> str:
    coding = (field.get("coding") or [])
    if coding:
        return str(coding[0].get("display") or coding[0].get("code") or "")
    return ""


def _ref_display(ref: dict | None) -> str:
    if not ref:
        return ""
    return str(ref.get("display") or ref.get("reference") or "")


# ==================================================================================
# USCDI v3 / US Core resource reads
# ==================================================================================
#
# Everything above resolves *identity* (which chart) and pre-fills a small
# Solace record shape. This section adds breadth: read the rest of the USCDI v3
# data classes for an already-resolved patient — Condition (problems),
# Medication (request + statement), AllergyIntolerance, Immunization,
# Observation (labs + vitals), DocumentReference, Encounter, Procedure.
#
# Two design choices keep this safe and reusable:
#   * Every read is **parametrized by base_url + access_token** (defaulting to
#     the env-driven SMART sandbox), so `ehr_gateway.read_resource` can pass a
#     specific hospital's vendor FHIR base + SMART token through the SAME code
#     path for Epic / Oracle / athena — no per-vendor read duplication.
#   * Each read returns a flat, PHI-minimal Solace dict (coded value + display
#     + date), never the raw FHIR resource, so callers/log lines stay free of
#     incidental identifiers (supports COMP-001 / no-PHI-in-logs posture).

# US Core resource types Solace surfaces, mapped to the FHIR search param that
# scopes them to one patient. (DocumentReference/Encounter/Observation/etc. all
# use `patient`; this map is the single source of truth for the read surface.)
USCDI_RESOURCE_TYPES: tuple[str, ...] = (
    "Condition",
    "MedicationRequest",
    "MedicationStatement",
    "AllergyIntolerance",
    "Immunization",
    "Observation",
    "DocumentReference",
    "Encounter",
    "Procedure",
)

# Observation US Core profiles split by `category`; callers ask for "labs" or
# "vitals" and we translate to the FHIR observation-category token.
_OBS_CATEGORY = {
    "labs": "laboratory",
    "vitals": "vital-signs",
    "social": "social-history",
}

_DEFAULT_READ_COUNT = "50"


def _search_at(
    base_url: str,
    resource_type: str,
    params: dict[str, str],
    *,
    access_token: str = "",
    timeout_s: float = RESOURCE_TIMEOUT_S,
    http_client: Any = None,
) -> dict[str, Any] | None:
    """`_search` against an explicit base_url + token (vendor-routable).

    Mirrors `_search` (timeout-bounded, fail-soft to None) but does not read
    module-level env, so the gateway can drive a hospital-specific Epic/Oracle/
    athena FHIR endpoint through the same normalization helpers below.

    `http_client` is an optional injected ``httpx.Client`` (or compatible) so
    tests can wire the offline mock FHIR server without touching the network;
    when omitted a short-lived client is created per call.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/{resource_type}"
    headers = {"Accept": "application/fhir+json"}
    tok = (access_token or "").strip()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        if http_client is not None:
            resp = http_client.get(url, params=params, headers=headers, timeout=timeout_s)
            if resp.status_code != 200:
                log.info("FHIR %s -> %d", resource_type, resp.status_code)
                return None
            return resp.json()
        with httpx.Client(timeout=timeout_s, headers=headers) as c:
            resp = c.get(url, params=params, timeout=timeout_s)
            if resp.status_code != 200:
                log.info("FHIR %s -> %d", resource_type, resp.status_code)
                return None
            return resp.json()
    except httpx.TimeoutException:
        log.info("FHIR %s timed out", resource_type)
        return None
    except Exception as e:  # noqa: BLE001
        log.info("FHIR %s error: %s", resource_type, e)
        return None


def _bundle_resources(bundle: dict[str, Any] | None, resource_type: str) -> list[dict[str, Any]]:
    """Pull resources of `resource_type` out of a FHIR search Bundle."""
    if not bundle:
        return []
    out: list[dict[str, Any]] = []
    for e in bundle.get("entry", []) or []:
        r = e.get("resource") or {}
        if r.get("resourceType") == resource_type:
            out.append(r)
    return out


def read_uscdi_resources(
    patient_id: str,
    resource_type: str,
    *,
    base_url: str = "",
    access_token: str = "",
    observation_category: str = "",
    count: str = _DEFAULT_READ_COUNT,
    active_only: bool = False,
    http_client: Any = None,
) -> list[dict[str, Any]]:
    """Read one US Core resource type for `patient_id`, normalized for Solace.

    `resource_type` must be one of `USCDI_RESOURCE_TYPES`. `observation_category`
    ("labs" | "vitals" | "social") scopes Observation reads; it is ignored for
    other types. `active_only` adds the relevant active filter for Condition /
    MedicationRequest. Returns a list of flat dicts (never raw FHIR), [] on any
    error so the caller's flow continues.
    """
    if resource_type not in USCDI_RESOURCE_TYPES:
        log.info("read_uscdi_resources: unsupported type %s", resource_type)
        return []
    pid = (patient_id or "").strip()
    if not pid:
        return []

    params: dict[str, str] = {"patient": pid, "_count": count}
    if resource_type == "Observation":
        cat = _OBS_CATEGORY.get((observation_category or "").lower())
        if cat:
            params["category"] = cat
        params["_sort"] = "-date"
    elif resource_type == "Encounter":
        params["_sort"] = "-date"
    elif resource_type == "DocumentReference":
        params["_sort"] = "-date"
    elif resource_type == "Condition" and active_only:
        params["clinical-status"] = "active"
    elif resource_type == "MedicationRequest" and active_only:
        params["status"] = "active"

    base = (base_url or "").strip()
    if base or http_client is not None:
        bundle = _search_at(
            base, resource_type, params,
            access_token=access_token, http_client=http_client,
        )
    else:
        bundle = _search(resource_type, params)
    resources = _bundle_resources(bundle, resource_type)
    return [_normalize_uscdi(resource_type, r) for r in resources]


def read_uscdi_summary(
    patient_id: str,
    *,
    base_url: str = "",
    access_token: str = "",
    http_client: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """Read the full USCDI v3 clinical picture for `patient_id` in parallel.

    Returns a dict keyed by a Solace-facing section name
    (problems / medications / allergies / immunizations / labs / vitals /
    documents / encounters / procedures), each a list of normalized dicts.
    Fail-soft: any individual read that errors yields an empty list for that
    section rather than failing the whole summary.
    """
    pid = (patient_id or "").strip()
    if not pid:
        return {}

    # (section, resource_type, observation_category)
    plan: list[tuple[str, str, str]] = [
        ("problems", "Condition", ""),
        ("medications", "MedicationRequest", ""),
        ("medication_statements", "MedicationStatement", ""),
        ("allergies", "AllergyIntolerance", ""),
        ("immunizations", "Immunization", ""),
        ("labs", "Observation", "labs"),
        ("vitals", "Observation", "vitals"),
        ("documents", "DocumentReference", ""),
        ("encounters", "Encounter", ""),
        ("procedures", "Procedure", ""),
    ]
    out: dict[str, list[dict[str, Any]]] = {section: [] for section, _, _ in plan}
    with ThreadPoolExecutor(max_workers=min(8, len(plan))) as pool:
        fut_to_section = {
            pool.submit(
                read_uscdi_resources,
                pid,
                rtype,
                base_url=base_url,
                access_token=access_token,
                observation_category=obs_cat,
                http_client=http_client,
            ): section
            for section, rtype, obs_cat in plan
        }
        for fut in as_completed(fut_to_section):
            section = fut_to_section[fut]
            try:
                out[section] = fut.result() or []
            except Exception as e:  # noqa: BLE001
                log.info("USCDI summary %s read failed: %s", section, e)
                out[section] = []
    return out


# ----------------------------------------------------------------------------------
# US Core normalizers — raw FHIR resource -> flat Solace dict (PHI-minimal)
# ----------------------------------------------------------------------------------


def _normalize_uscdi(resource_type: str, r: dict[str, Any]) -> dict[str, Any]:
    """Dispatch to the per-type normalizer; fall back to a thin coded summary."""
    fn = _USCDI_NORMALIZERS.get(resource_type)
    if fn:
        return fn(r)
    return {
        "id": r.get("id", ""),
        "type": resource_type,
        "display": _coding_display(r.get("code") or {}),
    }


def _norm_condition(r: dict[str, Any]) -> dict[str, Any]:
    code = r.get("code") or {}
    return {
        "id": r.get("id", ""),
        "display": code.get("text") or _coding_display(code),
        "code": _first_code(code),
        "clinical_status": _coding_code(r.get("clinicalStatus") or {}),
        "category": _coding_code((r.get("category") or [{}])[0]),
        "onset": (r.get("onsetDateTime") or "")[:10],
        "recorded": (r.get("recordedDate") or "")[:10],
    }


def _norm_medication_request(r: dict[str, Any]) -> dict[str, Any]:
    med = r.get("medicationCodeableConcept") or {}
    dosage = ""
    di = r.get("dosageInstruction") or []
    if di:
        dosage = di[0].get("text") or ""
    return {
        "id": r.get("id", ""),
        "display": med.get("text") or _coding_display(med),
        "code": _first_code(med),
        "status": str(r.get("status") or ""),
        "intent": str(r.get("intent") or ""),
        "dosage": dosage,
        "authored": (r.get("authoredOn") or "")[:10],
    }


def _norm_medication_statement(r: dict[str, Any]) -> dict[str, Any]:
    med = r.get("medicationCodeableConcept") or {}
    dosage = ""
    d = r.get("dosage") or []
    if d:
        dosage = d[0].get("text") or ""
    return {
        "id": r.get("id", ""),
        "display": med.get("text") or _coding_display(med),
        "code": _first_code(med),
        "status": str(r.get("status") or ""),
        "dosage": dosage,
        "asserted": (r.get("dateAsserted") or "")[:10],
    }


def _norm_allergy(r: dict[str, Any]) -> dict[str, Any]:
    code = r.get("code") or {}
    reactions: list[str] = []
    for rx in r.get("reaction") or []:
        for m in rx.get("manifestation") or []:
            txt = m.get("text") or _coding_display(m)
            if txt:
                reactions.append(txt)
    return {
        "id": r.get("id", ""),
        "display": code.get("text") or _coding_display(code),
        "code": _first_code(code),
        "clinical_status": _coding_code(r.get("clinicalStatus") or {}),
        "criticality": str(r.get("criticality") or ""),
        "reactions": reactions,
    }


def _norm_immunization(r: dict[str, Any]) -> dict[str, Any]:
    vc = r.get("vaccineCode") or {}
    return {
        "id": r.get("id", ""),
        "display": vc.get("text") or _coding_display(vc),
        "code": _first_code(vc),
        "status": str(r.get("status") or ""),
        "occurrence": (r.get("occurrenceDateTime") or "")[:10],
    }


def _norm_observation(r: dict[str, Any]) -> dict[str, Any]:
    code = r.get("code") or {}
    value, unit = _observation_value(r)
    category = ""
    cats = r.get("category") or []
    if cats:
        category = _coding_code(cats[0])
    return {
        "id": r.get("id", ""),
        "display": code.get("text") or _coding_display(code),
        "code": _first_code(code),
        "category": category,
        "value": value,
        "unit": unit,
        "status": str(r.get("status") or ""),
        "effective": (r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("start") or "")[:10],
    }


def _norm_document_reference(r: dict[str, Any]) -> dict[str, Any]:
    type_cc = r.get("type") or {}
    category = ""
    cats = r.get("category") or []
    if cats:
        category = _coding_display(cats[0]) or _coding_code(cats[0])
    author = ""
    authors = r.get("author") or []
    if authors:
        author = authors[0].get("display") or _ref_display(authors[0])
    return {
        "id": r.get("id", ""),
        "type": type_cc.get("text") or _coding_display(type_cc),
        "category": category,
        "status": str(r.get("status") or ""),
        "doc_status": str(r.get("docStatus") or ""),
        "author": author,
        "date": (r.get("date") or "")[:10],
    }


def _norm_encounter(r: dict[str, Any]) -> dict[str, Any]:
    period = r.get("period") or {}
    type_text = ""
    types = r.get("type") or []
    if types:
        type_text = types[0].get("text") or _coding_display(types[0])
    reason = ""
    rc = r.get("reasonCode") or []
    if rc:
        reason = rc[0].get("text") or _coding_display(rc[0])
    return {
        "id": r.get("id", ""),
        "type": type_text or "Encounter",
        "class": _coding_code(r.get("class") or {}) if isinstance(r.get("class"), dict) else "",
        "status": str(r.get("status") or ""),
        "start": (period.get("start") or "")[:10],
        "end": (period.get("end") or "")[:10],
        "reason": reason,
        "facility": _ref_display(r.get("serviceProvider")),
    }


def _norm_procedure(r: dict[str, Any]) -> dict[str, Any]:
    code = r.get("code") or {}
    performed = (
        r.get("performedDateTime")
        or (r.get("performedPeriod") or {}).get("start")
        or ""
    )
    return {
        "id": r.get("id", ""),
        "display": code.get("text") or _coding_display(code),
        "code": _first_code(code),
        "status": str(r.get("status") or ""),
        "performed": str(performed)[:10],
    }


_USCDI_NORMALIZERS = {
    "Condition": _norm_condition,
    "MedicationRequest": _norm_medication_request,
    "MedicationStatement": _norm_medication_statement,
    "AllergyIntolerance": _norm_allergy,
    "Immunization": _norm_immunization,
    "Observation": _norm_observation,
    "DocumentReference": _norm_document_reference,
    "Encounter": _norm_encounter,
    "Procedure": _norm_procedure,
}


# ----------------------------------------------------------------------------------
# US Core coding helpers
# ----------------------------------------------------------------------------------


def _coding_code(field: dict) -> str:
    """First coding's `code` (e.g. clinical-status 'active')."""
    coding = (field or {}).get("coding") or []
    if coding:
        return str(coding[0].get("code") or "")
    return ""


def _first_code(field: dict) -> dict[str, str]:
    """First coding as a {system, code, display} triple (empty when absent)."""
    coding = (field or {}).get("coding") or []
    if not coding:
        return {"system": "", "code": "", "display": ""}
    c = coding[0]
    return {
        "system": str(c.get("system") or ""),
        "code": str(c.get("code") or ""),
        "display": str(c.get("display") or ""),
    }


def _observation_value(r: dict[str, Any]) -> tuple[Any, str]:
    """Extract a (value, unit) pair from a FHIR Observation's value[x]."""
    vq = r.get("valueQuantity")
    if isinstance(vq, dict):
        return vq.get("value"), str(vq.get("unit") or vq.get("code") or "")
    vcc = r.get("valueCodeableConcept")
    if isinstance(vcc, dict):
        return vcc.get("text") or _coding_display(vcc), ""
    if "valueString" in r:
        return r.get("valueString"), ""
    if "valueBoolean" in r:
        return r.get("valueBoolean"), ""
    # Component-only observations (e.g. blood pressure) — summarize components.
    comps = r.get("component") or []
    if comps:
        parts = []
        for c in comps:
            cq = c.get("valueQuantity") or {}
            disp = _coding_display(c.get("code") or {})
            if cq.get("value") is not None:
                parts.append(f"{disp}:{cq.get('value')}{cq.get('unit') or ''}".strip())
        return "; ".join(parts), ""
    return None, ""
