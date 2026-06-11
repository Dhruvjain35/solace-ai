"""The primitive registry — the allowlist of things the planner can run.

Each primitive is a thin deterministic adapter over an existing Solace service
that DOWN-PROJECTS the result to coded output (flags / codes / counts / scores)
plus slot refs for any real value the clinician must see. A plan may only call
primitives that appear here, with params that match the declared (vocab-bound)
schema — there is deliberately no free-string param type, so a plan cannot carry
a raw patient value.

To extend the prediction surface (risk models, operational predictors), register
another entry here pointing at the existing service; the gate, executor, and
artifact layer pick it up with no other changes.
"""
from __future__ import annotations

from typing import Any, Callable

from services import drug_interactions, hedis
from services.copilot import catalog

Adapter = Callable[[Any, dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Deterministic helpers (drug-class detection, bucketing) — coded, PHI-free out
# ---------------------------------------------------------------------------

_CLASS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "anticoagulant": ("warfarin", "coumadin", "apixaban", "eliquis", "rivaroxaban",
                       "xarelto", "dabigatran", "edoxaban", "heparin", "enoxaparin", "lovenox"),
    "antiplatelet": ("aspirin", "asa", "clopidogrel", "plavix", "ticagrelor",
                     "prasugrel", "dipyridamole"),
    "nsaid": ("ibuprofen", "advil", "motrin", "naproxen", "aleve", "diclofenac",
              "ketorolac", "toradol", "celecoxib", "meloxicam", "indomethacin"),
    "beta_blocker": ("metoprolol", "atenolol", "carvedilol", "bisoprolol",
                     "propranolol", "labetalol", "nadolol"),
    "opioid": ("oxycodone", "hydrocodone", "morphine", "fentanyl", "tramadol",
               "codeine", "hydromorphone", "dilaudid", "percocet", "norco"),
    "insulin": ("insulin", "lantus", "humalog", "novolog", "glargine", "lispro"),
}


def _classes_of(med: str) -> list[str]:
    low = med.lower()
    return [cls for cls, kws in _CLASS_KEYWORDS.items() if any(k in low for k in kws)]


def _med_classes(meds: list[str]) -> set[str]:
    out: set[str] = set()
    for m in meds:
        out.update(_classes_of(m))
    return out


def _age_band(age: Any) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return "unknown"
    if a < 1:
        return "infant"
    if a < 18:
        return "pediatric"
    if a < 40:
        return "18-39"
    if a < 65:
        return "40-64"
    if a < 90:
        return "65-89"
    return "90+"  # HIPAA Safe Harbor: ages 90+ aggregated


_COMPLAINT_CATEGORIES: dict[str, tuple[str, ...]] = {
    "cardiac": ("chest pain", "palpitation", "cardiac", "angina"),
    "respiratory": ("shortness of breath", "sob", "dyspnea", "cough", "wheez"),
    "neurologic": ("headache", "weakness", "numbness", "seizure", "dizz", "stroke"),
    "gastrointestinal": ("abdominal", "nausea", "vomit", "diarrhea", "belly"),
    "musculoskeletal": ("sprain", "fracture", "back pain", "joint", "injury"),
    "psychiatric": ("anxiety", "depression", "suicid", "psych"),
    "infectious": ("fever", "infection", "flu", "covid"),
}

_CONDITION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cardiac": ("hypertension", "htn", "afib", "atrial", "chf", "heart", "coronary",
                "mi", "angina", "cardiac"),
    "renal": ("ckd", "kidney", "renal", "esrd", "dialysis"),
    "endocrine": ("diabetes", "dm", "thyroid", "hypothyroid", "hyperthyroid"),
    "respiratory": ("copd", "asthma", "pulmonary", "emphysema"),
    "neurologic": ("stroke", "seizure", "epilepsy", "parkinson", "neuropathy", "migraine"),
    "psychiatric": ("depression", "anxiety", "bipolar", "schizo", "ptsd"),
    "gastrointestinal": ("gerd", "ulcer", "ibd", "crohn", "colitis", "cirrhosis", "hepat"),
    "oncologic": ("cancer", "carcinoma", "tumor", "malignancy", "lymphoma", "leukemia"),
    "infectious": ("hiv", "hepatitis", "tuberculosis", "tb"),
    "musculoskeletal": ("arthritis", "osteoporosis", "fracture"),
}


def _category_of(text: str, table: dict[str, tuple[str, ...]]) -> str | None:
    low = text.lower()
    for cat, kws in table.items():
        if any(k in low for k in kws):
            return cat
    return None


def _hedis_patient(chart: dict[str, Any], ehr: dict[str, Any] | None) -> dict[str, Any]:
    conditions = list(chart["conditions"])
    if ehr:
        conditions += [c.get("display") if isinstance(c, dict) else str(c)
                       for c in (ehr.get("conditions") or [])]
    return {
        "age": chart.get("age") or 0,
        "sex": chart.get("sex") or "",
        "history": {"conditions": [c for c in conditions if c]},
    }


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

_FLAG_CLASS = {
    "on_anticoagulant": "anticoagulant", "on_antiplatelet": "antiplatelet",
    "on_nsaid": "nsaid", "on_beta_blocker": "beta_blocker",
    "on_opioid": "opioid", "on_insulin": "insulin",
}


def _feature_flag(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = params["name"]
    chart = ex.chart
    meds = chart["medications"]
    vitals = chart.get("vitals") or {}

    # Drug-class flags: the model sees only flag=true, but we slot the matching
    # real meds so the clinician can see WHICH drug behind the flag.
    if name in _FLAG_CLASS:
        cls = _FLAG_CLASS[name]
        matches = [m for m in meds if cls in _classes_of(m)]
        out: dict[str, Any] = {"feature": name, "flag": bool(matches)}
        if matches:
            out["matches_slot"] = ex.slot(cls, ", ".join(matches))
        return out

    if name == "polypharmacy":
        flag = len(meds) >= 5
    elif name == "allergies_documented":
        flag = bool(chart["allergies"])
    elif name == "vitals_recorded":
        flag = bool(vitals)
    elif name == "abnormal_vitals_present":
        flag = bool(vitals.get("abnormal")) if isinstance(vitals, dict) else False
    elif name == "has_linked_ehr":
        flag = bool(ex.ehr_record())
    else:
        return {"error": f"unknown feature flag {name}"}
    return {"feature": name, "flag": flag}


def _feature_category(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    field = params["field"]
    chart = ex.chart
    if field == "age_band":
        return {"field": field, "category": _age_band(chart.get("age"))}
    if field == "sex":
        s = (chart.get("sex") or "").strip().lower()
        return {"field": field, "category": s or "unknown"}
    if field == "esi_level":
        return {"field": field, "category": chart.get("esi_level") or "unknown"}
    if field == "chief_complaint_category":
        cat = _category_of(chart.get("chief_complaint") or "", _COMPLAINT_CATEGORIES)
        return {"field": field, "category": cat or "other"}
    if field == "medication_burden":
        n = len(chart["medications"])
        band = "none" if n == 0 else "low" if n <= 2 else "moderate" if n <= 4 else "high"
        return {"field": field, "category": band, "count": n}
    return {"error": f"unknown category field {field}"}


def _engine_drug_interactions(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    chart = ex.chart
    meds = list(chart["medications"])
    if not meds:
        return {"highest_severity": "none", "counts": {}, "items": []}
    di = drug_interactions.check(meds, allergies=chart["allergies"],
                                 complaint=chart["chief_complaint"])
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    def _add(kind: str, sev: str, a: str, b: str | None, reason: str) -> None:
        counts[sev] = counts.get(sev, 0) + 1
        a_cls = (_classes_of(a) or ["other"])[0]
        b_cls = (_classes_of(b) or ["other"])[0] if b else None
        pair = f"{a} + {b}" if b else a
        items.append({
            "kind": kind, "severity": sev,
            "a_class": a_cls, "b_class": b_cls,
            "pair_slot": ex.slot("interaction", pair),
            "detail_slot": ex.slot("interaction detail", reason or ""),
        })

    for it in (di.get("drug_drug") or []):
        _add("drug_drug", it.get("severity", "moderate"), it.get("a", "?"),
             it.get("b", "?"), it.get("reason", ""))
    for it in (di.get("drug_allergy") or []):
        _add("drug_allergy", it.get("severity", "high"),
             it.get("med") or it.get("a", "?"), None, it.get("reason", ""))
    for it in (di.get("renal") or []):
        _add("renal", it.get("severity", "moderate"), it.get("med", "?"), None,
             it.get("guidance") or it.get("reason", ""))

    return {
        "highest_severity": (di.get("summary") or {}).get("highest_severity")
        or ("high" if di.get("any_high") else ("low" if items else "none")),
        "counts": counts,
        "items": items,
    }


def _engine_care_gaps(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    gaps = hedis.evaluate(_hedis_patient(ex.chart, ex.ehr_record()))
    coded = [{
        "measure": g.get("measure"), "icd10": g.get("icd10"),
        "priority": g.get("priority", "medium"), "domain": g.get("domain"),
        "name": g.get("name") or g.get("measure"),  # generic measure label (not PHI)
        "overdue_by_months": g.get("overdue_by_months"),
    } for g in gaps]
    return {"count": len(coded), "gaps": coded}


def _ehr_problem_history(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    category = params["category"]
    rec = ex.ehr_record()
    if not rec:
        return {"linked": False, "category": category, "count": 0, "items": []}
    items = []
    for c in rec.get("conditions") or []:
        display = c.get("display") if isinstance(c, dict) else str(c)
        code = c.get("code") if isinstance(c, dict) else None
        if _category_of(display or "", _CONDITION_KEYWORDS) == category:
            items.append({"icd10": code, "display_slot": ex.slot("condition", display or "")})
    return {"linked": True, "category": category, "count": len(items), "items": items}


def _ehr_prior_visits(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    rec = ex.ehr_record()
    if not rec:
        return {"linked": False, "count": 0, "items": []}
    items = []
    for v in rec.get("prior_visits") or []:
        if isinstance(v, dict):
            items.append({
                "type_category": _category_of(str(v.get("reason") or v.get("type") or ""),
                                              _CONDITION_KEYWORDS) or "other",
                "date_slot": ex.slot("visit date", str(v.get("date") or v.get("when") or "")),
                "reason_slot": ex.slot("visit reason", str(v.get("reason") or "")),
            })
    return {"linked": True, "count": len(items), "items": items}


def _ehr_med_history(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    rec = ex.ehr_record()
    if not rec:
        return {"linked": False, "count": 0, "items": []}
    items, classes = [], set()
    for m in rec.get("medications") or []:
        name = m.get("display") or m.get("name") if isinstance(m, dict) else str(m)
        cls = (_classes_of(name or "") or ["other"])[0]
        classes.add(cls)
        items.append({"class": cls, "name_slot": ex.slot("medication", name or "")})
    return {"linked": True, "count": len(items), "classes": sorted(classes), "items": items}


def _clinical_differential(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import differential  # noqa: PLC0415 (heavy import, lazy)
    chart = ex.chart
    esi = chart.get("esi_level")
    try:
        esi = int(esi)
    except (TypeError, ValueError):
        esi = 3
    # PHI-ISOLATION (C2): the copilot must never send the raw free-text transcript
    # (it carries the patient name + narrative) or raw medication / allergy / vital
    # VALUES to the model. Feed the differential a CODED clinical context only — the
    # chief complaint + coded problem list + ESI. Medication/allergy/vital context is
    # deliberately withheld from this model call (those values still reach the
    # clinician via slots in other primitives), keeping clinical.differential inside
    # the "coded metadata only" guarantee. The leak test exercises this real call.
    conditions = [c for c in (chart.get("conditions") or [])
                  if isinstance(c, str) and c.strip()]
    cc = (chart.get("chief_complaint") or "").strip()
    context_parts = []
    if cc:
        context_parts.append(f"Chief complaint: {cc}.")
    if conditions:
        context_parts.append("Known conditions: " + ", ".join(conditions) + ".")
    coded_context = " ".join(context_parts)
    ranked = differential.generate(
        transcript=coded_context,  # coded summary, NOT the raw transcript
        esi_level=esi,
        medical_info={"conditions": conditions, "age": chart.get("age"),
                      "sex": chart.get("sex")},
        vitals={},  # raw vitals are PHI under the copilot guarantee — withheld
    )
    coded = [{
        "diagnosis": d.get("diagnosis"),        # coded clinical label (not an identifier)
        "icd10": d.get("icd10", ""),
        "likelihood": d.get("likelihood", ""),
        "must_not_miss": bool(d.get("must_not_miss")),
        "discriminator": d.get("discriminator", ""),
    } for d in (ranked or [])]
    return {"count": len(coded), "ranked": coded}


# ---------------------------------------------------------------------------
# Risk / operational prediction adapters
# ---------------------------------------------------------------------------

def _vnum(vitals: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = vitals.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def _patient_for_ml(ex: Any) -> dict[str, Any]:
    chart = ex.chart
    return {
        "patient_id": ex.ctx.get("patient_id", "unknown"),
        "transcript": chart.get("transcript", ""),
        "language": "en",
        "medical_info": {
            "age": chart.get("age"), "sex": chart.get("sex"),
            "conditions": chart["conditions"], "medications": chart["medications"],
        },
    }


def _risk_esi_refine(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import triage_ml  # noqa: PLC0415 (heavy import)
    out = triage_ml.predict(_patient_for_ml(ex), ex.chart.get("vitals") or {})
    if not out:
        return {"available": False, "note": "ESI refinement model not loaded"}
    return {
        "available": True,
        "refined_esi": out.get("esi_level"),
        "confidence": round(out.get("confidence", 0.0), 3),
        "conformal_set": out.get("conformal_set"),
        # feature names are coded model features; raw numeric value is dropped.
        "top_features": [{"feature": f.get("feature"), "direction": f.get("direction")}
                         for f in (out.get("top_features") or [])[:5]],
        "source": out.get("source"),
    }


def _risk_sepsis(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import early_warning  # noqa: PLC0415
    v = ex.chart.get("vitals") or {}
    out = early_warning.sepsis_ews(
        hr=_vnum(v, "heart_rate", "hr", "pulse"),
        rr=_vnum(v, "respiratory_rate", "rr", "resp_rate"),
        temp_c=_vnum(v, "temperature", "temp", "temp_c"),
        sbp=_vnum(v, "systolic_bp", "systolic", "sbp"),
        dbp=_vnum(v, "diastolic_bp", "diastolic", "dbp"),
        spo2=_vnum(v, "spo2", "o2_sat", "oxygen_saturation"),
    )
    return {"score": out.get("score"), "band": out.get("band"),
            "qsofa": out.get("qsofa"), "sirs": out.get("sirs"),
            "action": out.get("action")}


def _risk_early_warning(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import early_warning  # noqa: PLC0415
    v = ex.chart.get("vitals") or {}
    now = {
        "heart_rate": _vnum(v, "heart_rate", "hr", "pulse"),
        "respiratory_rate": _vnum(v, "respiratory_rate", "rr", "resp_rate"),
        "systolic_bp": _vnum(v, "systolic_bp", "systolic", "sbp"),
        "spo2": _vnum(v, "spo2", "o2_sat", "oxygen_saturation"),
        "temperature": _vnum(v, "temperature", "temp"),
    }
    now = {k: val for k, val in now.items() if val is not None}
    out = early_warning.deterioration_index(vitals_now=now)
    return {"score": out.get("score"), "band": out.get("band"), "action": out.get("action")}


def _op_no_show(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import no_show  # noqa: PLC0415
    patient = ex.ctx.get("patient") or {}
    appt = patient.get("next_appointment") or patient.get("appointment_iso")
    if not appt:
        return {"applicable": False, "note": "No scheduled appointment on record"}
    out = no_show.predict(appt, age=ex.chart.get("age"))
    prob = out.get("probability")
    return {"applicable": True,
            "probability": round(prob, 3) if isinstance(prob, (int, float)) else None,
            "band": out.get("tier") or out.get("band"), "model": out.get("model")}


def _op_disposition(ex: Any, params: dict[str, Any]) -> dict[str, Any]:
    from services import disposition  # noqa: PLC0415
    esi = ex.chart.get("esi_level")
    try:
        esi = int(esi)
    except (TypeError, ValueError):
        esi = 3
    out = disposition.safety_net(esi, ex.chart.get("vitals") or {})
    red_flags = out.get("red_flags") or []
    res: dict[str, Any] = {
        "disposition": out.get("disposition"),
        "level_of_care": out.get("level_of_care"),
        "red_flag_count": len(red_flags),
    }
    if red_flags:  # red flags embed vital numbers -> slot for the clinician
        res["detail_slot"] = ex.slot("disposition red flags", "; ".join(red_flags))
    return res


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

PRIMITIVES: dict[str, dict[str, Any]] = {
    "feature.flag": {
        "group": "feature",
        "summary": "Evaluate a derived boolean about the current chart (e.g. on_anticoagulant).",
        "params": {"name": {"type": "enum", "values": catalog.FEATURE_FLAGS, "required": True}},
        "returns": "{feature, flag: bool}",
        "adapter": _feature_flag,
    },
    "feature.category": {
        "group": "feature",
        "summary": "Bucket a categorical field (age_band, esi_level, chief_complaint_category, ...).",
        "params": {"field": {"type": "enum", "values": catalog.CATEGORY_FIELDS, "required": True}},
        "returns": "{field, category}",
        "adapter": _feature_category,
    },
    "engine.drug_interactions": {
        "group": "engine",
        "summary": "Run the drug-interaction / allergy / renal panel on current meds. Returns coded severities; real drug pairs are slotted.",
        "params": {},
        "returns": "{highest_severity, counts, items:[{kind, severity, a_class, b_class, pair_slot, detail_slot}]}",
        "adapter": _engine_drug_interactions,
    },
    "engine.care_gaps": {
        "group": "engine",
        "summary": "Evaluate open HEDIS preventive/chronic care gaps. Returns coded measures + ICD-10.",
        "params": {},
        "returns": "{count, gaps:[{measure, icd10, priority, domain, name, overdue_by_months}]}",
        "adapter": _engine_care_gaps,
    },
    "ehr.problem_history": {
        "group": "ehr",
        "summary": "Slice the linked longitudinal record's problem list by clinical category. ICD-10 coded; displays slotted.",
        "params": {"category": {"type": "enum", "values": catalog.CONDITION_CATEGORIES, "required": True}},
        "returns": "{linked, category, count, items:[{icd10, display_slot}]}",
        "adapter": _ehr_problem_history,
    },
    "ehr.prior_visits": {
        "group": "ehr",
        "summary": "List prior encounters from the linked record. Type categories coded; dates/reasons slotted.",
        "params": {},
        "returns": "{linked, count, items:[{type_category, date_slot, reason_slot}]}",
        "adapter": _ehr_prior_visits,
    },
    "ehr.med_history": {
        "group": "ehr",
        "summary": "Longitudinal medication history from the linked record, coded by drug class; product names slotted.",
        "params": {},
        "returns": "{linked, count, classes, items:[{class, name_slot}]}",
        "adapter": _ehr_med_history,
    },
    "clinical.differential": {
        "group": "clinical",
        "summary": "Generate the ranked differential diagnosis for this encounter (coded Dx labels + ICD-10 + likelihood).",
        "params": {},
        "returns": "{count, ranked:[{diagnosis, icd10, likelihood, must_not_miss, discriminator}]}",
        "adapter": _clinical_differential,
    },
    "risk.esi_refine": {
        "group": "risk",
        "summary": "Run the LightGBM ESI-refinement ensemble on coded features + vitals. Returns refined acuity + conformal set + top contributing features (coded).",
        "params": {},
        "returns": "{available, refined_esi, confidence, conformal_set, top_features:[{feature, direction}]}",
        "adapter": _risk_esi_refine,
    },
    "risk.sepsis": {
        "group": "risk",
        "summary": "Sepsis early-warning score (NEWS2/qSOFA/SIRS hybrid) from vitals. Returns coded score + band; no raw vitals.",
        "params": {},
        "returns": "{score, band, qsofa, sirs, action}",
        "adapter": _risk_sepsis,
    },
    "risk.early_warning": {
        "group": "risk",
        "summary": "Rothman-style deterioration index from vitals trend. Returns coded score + band.",
        "params": {},
        "returns": "{score, band, action}",
        "adapter": _risk_early_warning,
    },
    "op.no_show": {
        "group": "op",
        "summary": "No-show risk for a scheduled appointment (if one is on record). Returns coded probability + band.",
        "params": {},
        "returns": "{applicable, probability, band, model}",
        "adapter": _op_no_show,
    },
    "op.disposition": {
        "group": "op",
        "summary": "Deterministic physiologic disposition floor (admit/observe/discharge + level of care). Vital-bearing red flags are slotted.",
        "params": {},
        "returns": "{disposition, level_of_care, red_flag_count, detail_slot?}",
        "adapter": _op_disposition,
    },
}


def planner_catalog() -> list[dict[str, Any]]:
    """The PHI-free primitive descriptions shown to the planner in Pass 1."""
    return [
        {"primitive": name, "group": spec["group"], "summary": spec["summary"],
         "params": {k: {kk: vv for kk, vv in v.items() if kk != "required"}
                    for k, v in spec["params"].items()},
         "returns": spec["returns"]}
        for name, spec in PRIMITIVES.items()
    ]
