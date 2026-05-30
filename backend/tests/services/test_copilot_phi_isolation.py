"""PHI-isolation guarantees for the EHR Copilot.

The headline test is ``TestLeakBoundary`` — it captures EVERY payload sent to
``claude.messages_create`` while answering a question / building a summary and
asserts that no known PHI token ever appears in a model-bound payload. If a
patient name or raw drug string ever reaches the model, this suite fails the
build. That makes "the AI can't touch PHI" a CI gate, not a design intention.
"""
from __future__ import annotations

import json

import pytest

gate = pytest.importorskip("services.copilot.gate")
registry = pytest.importorskip("services.copilot.registry")
executor = pytest.importorskip("services.copilot.executor")
artifacts = pytest.importorskip("services.copilot.artifacts")
pipeline = pytest.importorskip("services.copilot.pipeline")
context = pytest.importorskip("services.copilot.context")

from lib import claude  # noqa: E402
from services import differential  # noqa: E402

# --- Synthetic patient carrying obvious PHI --------------------------------

PHI_NAME = "Marcus Welby"
PHI_MEDS = ["warfarin 5mg", "metoprolol 50mg"]
PHI_ALLERGY = "penicillin"
PHI_EHR_MED = "lisinopril 10mg"
PHI_VISIT_DATE = "2024-03-15"

# Every token that must NEVER appear in a model-bound payload.
PHI_TOKENS = ["marcus", "welby", "warfarin", "metoprolol", "penicillin",
              "lisinopril", "2024-03-15"]

_PATIENT = {
    "patient_id": "p1",
    "name": PHI_NAME,
    "chief_complaint": "chest pain radiating to the left arm",
    "transcript": f"{PHI_NAME} reports crushing chest pain for two hours.",
    "esi_level": 2,
    "ehr_fhir_id": "fhir-123",
    "vitals": {"abnormal": True},
    "medical_info": json.dumps({
        "age": 67, "sex": "male",
        "conditions": ["atrial fibrillation", "hypertension"],
        "medications": PHI_MEDS, "allergies": [PHI_ALLERGY],
    }),
}

_EHR_RECORD = {
    "source": "Epic (sandbox)",
    "name": PHI_NAME, "dob": "1957-02-02", "sex": "male",
    "conditions": [{"display": "atrial fibrillation", "code": "I48.91"}],
    "medications": [{"display": PHI_EHR_MED}],
    "allergies": [{"display": PHI_ALLERGY}],
    "prior_visits": [{"date": PHI_VISIT_DATE, "reason": "cardiac follow-up"}],
}

# A plan that exercises EVERY adapter, so the leak test covers them all.
_FULL_PLAN = {
    "reasoning": "cover all primitives",
    "steps": [
        {"id": "s1", "primitive": "feature.flag", "params": {"name": "on_anticoagulant"}},
        {"id": "s2", "primitive": "feature.category", "params": {"field": "age_band"}},
        {"id": "s3", "primitive": "engine.drug_interactions", "params": {}},
        {"id": "s4", "primitive": "engine.care_gaps", "params": {}},
        {"id": "s5", "primitive": "ehr.problem_history", "params": {"category": "cardiac"}},
        {"id": "s6", "primitive": "ehr.prior_visits", "params": {}},
        {"id": "s7", "primitive": "ehr.med_history", "params": {}},
        {"id": "s8", "primitive": "clinical.differential", "params": {}},
    ],
}

_NARRATE_TREE = {
    "blocks": [
        {"type": "callout", "text": "Yes — on an anticoagulant: {S1}. Bleeding risk noted."},
        {"type": "table", "title": "Interactions", "rows_ref": "s3.items",
         "columns": ["severity", "a_class"]},
        {"type": "differential", "title": "Differential", "ranked_ref": "s8.ranked"},
        {"type": "timeline", "title": "Prior visits", "events_ref": "s6.items"},
        {"type": "evil_script", "text": "<script>alert(1)</script>"},  # must be dropped
    ],
}


@pytest.fixture
def captured(monkeypatch):
    """Stub the model + data layer offline; capture every model-bound payload."""
    payloads: list[dict] = []

    def fake_create(*, model, max_tokens, system="", messages, purpose, **kw):
        payloads.append({"purpose": purpose, "system": system, "messages": messages})
        if purpose == "copilot_plan":
            text = json.dumps(_FULL_PLAN)
        elif purpose == "copilot_narrate":
            text = json.dumps(_NARRATE_TREE)
        else:
            text = "{}"
        return claude.Response(content=[claude.TextBlock(text=text)])

    monkeypatch.setattr(claude, "available", lambda: True)
    monkeypatch.setattr(claude, "messages_create", fake_create)
    monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT))
    monkeypatch.setattr(executor, "_crawl_ehr", lambda ctx: dict(_EHR_RECORD))
    monkeypatch.setattr(differential, "generate", lambda **kw: [
        {"diagnosis": "Acute coronary syndrome", "icd10": "I24.9",
         "likelihood": "high", "must_not_miss": True, "discriminator": "troponin"},
    ])
    return payloads


# ---------------------------------------------------------------------------
# THE leak test
# ---------------------------------------------------------------------------

class TestLeakBoundary:
    def _assert_clean(self, payloads):
        assert payloads, "no model calls were captured"
        for p in payloads:
            blob = (p["system"] + json.dumps(p["messages"])).lower()
            for tok in PHI_TOKENS:
                assert tok not in blob, (
                    f"PHI token '{tok}' leaked into the {p['purpose']} model payload"
                )

    def test_ask_sends_no_phi_to_model(self, captured):
        result = pipeline.answer_question("h1", "p1",
                                          "Is the patient on anticoagulants — bleeding risk?")
        self._assert_clean(captured)
        # ...and the real values DID reach the clinician via slots / hydrated blocks
        all_slot_values = " ".join(s["value"] for s in result["slots"].values()).lower()
        assert "warfarin" in all_slot_values
        assert result["plan"] is not None  # auditable plan recorded

    def test_summary_sends_no_phi_to_model(self, captured):
        pipeline.catch_me_up("h1", "p1")
        self._assert_clean(captured)

    def test_both_passes_were_exercised(self, captured):
        pipeline.answer_question("h1", "p1", "anything")
        purposes = {p["purpose"] for p in captured}
        assert purposes == {"copilot_plan", "copilot_narrate"}


# ---------------------------------------------------------------------------
# Executor down-projection + boundary linter
# ---------------------------------------------------------------------------

class TestExecutorDownProjection:
    def _exec(self, monkeypatch):
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT))
        monkeypatch.setattr(executor, "_crawl_ehr", lambda ctx: dict(_EHR_RECORD))
        ctx = context.build_chart("h1", "p1")
        return executor.Executor(ctx)

    def test_feature_flag_anticoagulant_true(self, monkeypatch):
        ex = self._exec(monkeypatch)
        out = registry.PRIMITIVES["feature.flag"]["adapter"](ex, {"name": "on_anticoagulant"})
        assert out["feature"] == "on_anticoagulant"
        assert out["flag"] is True

    def test_drug_interactions_codes_not_names(self, monkeypatch):
        ex = self._exec(monkeypatch)
        out = registry.PRIMITIVES["engine.drug_interactions"]["adapter"](ex, {})
        blob = json.dumps(out).lower()
        # The boundary property: no raw drug product string in the coded output.
        for tok in ("warfarin", "metoprolol"):
            assert tok not in blob

    def test_feature_flag_slots_the_matching_med(self, monkeypatch):
        ex = self._exec(monkeypatch)
        out = registry.PRIMITIVES["feature.flag"]["adapter"](ex, {"name": "on_anticoagulant"})
        assert out["flag"] is True
        assert "warfarin" not in json.dumps(out).lower()       # coded output has no raw name
        slot_vals = " ".join(s["value"].lower() for s in ex.slots.as_dict().values())
        assert "warfarin" in slot_vals                          # but the clinician can see it

    def test_age_band_buckets(self, monkeypatch):
        ex = self._exec(monkeypatch)
        out = registry.PRIMITIVES["feature.category"]["adapter"](ex, {"field": "age_band"})
        assert out["category"] == "65-89"

    def test_boundary_linter_catches_leak(self):
        chart = {"name": PHI_NAME, "medications": PHI_MEDS, "allergies": [PHI_ALLERGY]}
        # raw drug name outside a slot -> violation
        with pytest.raises(AssertionError):
            executor._assert_no_raw_phi("x", {"note": "patient on warfarin"}, chart)
        # same value inside a slot marker -> allowed
        executor._assert_no_raw_phi("x", {"v": {"$slot": "S1", "label": "med"}}, chart)


# ---------------------------------------------------------------------------
# Artifact hydration
# ---------------------------------------------------------------------------

class TestArtifactHydration:
    def test_ref_resolves_and_slot_fills(self):
        results = [{"id": "s1", "primitive": "x",
                    "data": {"items": [{"sev": "high", "name": {"$slot": "S1", "label": "med"}}]}}]
        slots = {"S1": {"label": "med", "value": "warfarin 5mg"}}
        tree = {"blocks": [
            {"type": "table", "title": "T", "rows_ref": "s1.items", "columns": ["sev"]},
            {"type": "callout", "text": "on {S1} now"},
        ]}
        blocks = artifacts.hydrate(tree, results, slots)
        assert blocks[0]["rows"][0]["name"] == "warfarin 5mg"  # slot filled in bound data
        assert blocks[1]["text"] == "on warfarin 5mg now"      # slot token filled in prose

    def test_unknown_component_dropped(self):
        blocks = artifacts.hydrate({"blocks": [{"type": "evil", "text": "x"}]}, [], {})
        assert blocks == []

    def test_invented_ref_and_slot_are_safe(self):
        tree = {"blocks": [
            {"type": "table", "title": "T", "rows_ref": "nope.items", "columns": []},
            {"type": "callout", "text": "value is {S99}"},
        ]}
        blocks = artifacts.hydrate(tree, [], {})
        assert blocks[0].get("rows") is None          # missing ref -> empty, never fabricated
        assert blocks[1]["text"] == "value is [unavailable]"


# ---------------------------------------------------------------------------
# Plan gate
# ---------------------------------------------------------------------------

class TestRiskOpPrimitives:
    VITALS_PATIENT = {
        "patient_id": "p2", "name": "Jane Roe", "chief_complaint": "fever and confusion",
        "transcript": "febrile, hypotensive.", "esi_level": 2,
        "vitals": {"systolic_bp": 85, "heart_rate": 122, "respiratory_rate": 24,
                   "spo2": 89, "temperature": 38.7},
        "medical_info": json.dumps({"age": 72, "sex": "female", "conditions": [], "medications": []}),
    }

    def _exec(self, monkeypatch):
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(self.VITALS_PATIENT))
        return executor.Executor(context.build_chart("h1", "p2"))

    def test_all_registered(self):
        for p in ["risk.esi_refine", "risk.sepsis", "risk.early_warning",
                  "op.no_show", "op.disposition"]:
            assert p in registry.PRIMITIVES

    def test_sepsis_returns_coded_score(self, monkeypatch):
        out = registry.PRIMITIVES["risk.sepsis"]["adapter"](self._exec(monkeypatch), {})
        assert "score" in out and "band" in out

    def test_disposition_slots_vital_red_flags(self, monkeypatch):
        ex = self._exec(monkeypatch)
        out = registry.PRIMITIVES["op.disposition"]["adapter"](ex, {})
        assert out["disposition"] in ("admit", "observe", "discharge")
        # the SBP value (85) must not appear in the coded output — it's slotted
        assert "85" not in json.dumps({k: v for k, v in out.items() if k != "detail_slot"})

    def test_esi_refine_is_graceful_without_model(self, monkeypatch):
        out = registry.PRIMITIVES["risk.esi_refine"]["adapter"](self._exec(monkeypatch), {})
        assert "available" in out  # true if artifacts present, else graceful false

    def test_no_show_inapplicable_without_appointment(self, monkeypatch):
        out = registry.PRIMITIVES["op.no_show"]["adapter"](self._exec(monkeypatch), {})
        assert out["applicable"] is False


class TestReplanning:
    def test_one_bounded_replan_round(self, monkeypatch):
        narrate = {"n": 0}

        def fake(*, model, max_tokens, system="", messages, purpose, **k):
            if purpose == "copilot_plan":
                text = json.dumps({"steps": [
                    {"id": "s1", "primitive": "feature.flag", "params": {"name": "on_anticoagulant"}}]})
            else:
                narrate["n"] += 1
                if narrate["n"] == 1:  # first narrate: ask for more data
                    text = json.dumps({"need": [{"primitive": "clinical.differential", "params": {}}]})
                else:                  # second narrate: produce blocks from the new result
                    text = json.dumps({"blocks": [
                        {"type": "differential", "title": "DDx", "ranked_ref": "r1.ranked"}]})
            return claude.Response(content=[claude.TextBlock(text=text)])

        monkeypatch.setattr(claude, "available", lambda: True)
        monkeypatch.setattr(claude, "messages_create", fake)
        monkeypatch.setattr("db.storage.get_patient", lambda pid: dict(_PATIENT))
        monkeypatch.setattr(executor, "_crawl_ehr", lambda ctx: dict(_EHR_RECORD))
        monkeypatch.setattr(differential, "generate", lambda **k: [
            {"diagnosis": "Acute coronary syndrome", "icd10": "I24.9",
             "likelihood": "high", "must_not_miss": True, "discriminator": "troponin"}])

        r = pipeline.answer_question("h1", "p1", "what's the differential?")
        assert narrate["n"] == 2  # the bounded replan round fired exactly once
        # the follow-up primitive is recorded in the auditable plan
        assert any(s["primitive"] == "clinical.differential" for s in r["plan"]["steps"])
        # and the differential block rendered from the replanned result (r1)
        assert any(b["type"] == "differential" and b.get("ranked") for b in r["blocks"])


class TestPlanGate:
    def test_valid_plan_passes(self):
        p = gate.validate(_FULL_PLAN)
        assert len(p["steps"]) == 8

    def test_rejects_smuggled_value_in_enum_param(self):
        with pytest.raises(gate.PlanRejected):
            gate.validate({"steps": [{"id": "s1", "primitive": "feature.category",
                                      "params": {"field": "Marcus Welby has afib"}}]})

    def test_rejects_unknown_primitive(self):
        with pytest.raises(gate.PlanRejected):
            gate.validate({"steps": [{"id": "s1", "primitive": "drop.table", "params": {}}]})

    def test_rejects_over_budget(self):
        steps = [{"id": f"s{i}", "primitive": "engine.care_gaps", "params": {}} for i in range(20)]
        with pytest.raises(gate.PlanRejected):
            gate.validate({"steps": steps})

    def test_rejects_missing_required_param(self):
        with pytest.raises(gate.PlanRejected):
            gate.validate({"steps": [{"id": "s1", "primitive": "feature.flag", "params": {}}]})

    def test_rejects_none(self):
        with pytest.raises(gate.PlanRejected):
            gate.validate(None)
