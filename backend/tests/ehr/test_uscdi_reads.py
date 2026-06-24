"""USCDI v3 / US Core read-path tests.

Exercises the breadth of `services.fhir_patient_search.read_uscdi_*` and the
uniform `services.ehr_gateway.read_resource` / `read_uscdi_summary` vendor
routing, all against the offline mock FHIR server (no network, no vendor
account). The mock server's GET face returns seeded resources as searchset
Bundles; the readers normalize them into flat, PHI-minimal Solace dicts.
"""
from __future__ import annotations

import pytest

from services import ehr_gateway, fhir_patient_search

PATIENT_ID = "patient-uscdi-001"
BASE_URL = "https://mock-fhir.test/r4"


# --- fixtures: seeded US Core resources -------------------------------------------


def _condition(cid: str, icd10: str, display: str, status: str = "active") -> dict:
    return {
        "resourceType": "Condition",
        "id": cid,
        "clinicalStatus": {"coding": [{"code": status}]},
        "category": [{"coding": [{"code": "problem-list-item"}]}],
        "code": {"text": display, "coding": [
            {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": icd10, "display": display}]},
        "recordedDate": "2026-01-02",
    }


def _observation(oid: str, loinc: str, display: str, category: str,
                 value: float, unit: str) -> dict:
    return {
        "resourceType": "Observation",
        "id": oid,
        "status": "final",
        "category": [{"coding": [{"code": category}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": "2026-03-04T10:00:00Z",
    }


@pytest.fixture
def read_client(injectable_client):
    """The injectable mock client, usable as `http_client=` for reads."""
    return injectable_client


# ==========================================================================
# fhir_patient_search.read_uscdi_resources — per-type reads
# ==========================================================================
class TestReadUscdiResources:
    def test_unsupported_type_returns_empty(self, mock_fhir, read_client):
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "DiagnosticReport", base_url=BASE_URL, http_client=read_client)
        assert out == []

    def test_missing_patient_id_returns_empty(self, mock_fhir, read_client):
        assert fhir_patient_search.read_uscdi_resources(
            "", "Condition", base_url=BASE_URL, http_client=read_client) == []

    def test_read_conditions_normalized(self, mock_fhir, read_client):
        mock_fhir.seed("Condition", [
            _condition("c1", "I10", "Hypertension"),
            _condition("c2", "E11.9", "Type 2 diabetes"),
        ])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Condition", base_url=BASE_URL, http_client=read_client)
        assert len(out) == 2
        first = out[0]
        assert first["display"] == "Hypertension"
        assert first["code"]["code"] == "I10"
        assert first["clinical_status"] == "active"
        assert first["category"] == "problem-list-item"
        # Flat normalized dict — no raw FHIR resourceType leaking through.
        assert "resourceType" not in first

    def test_read_observations_filtered_by_category(self, mock_fhir, read_client):
        mock_fhir.seed("Observation", [
            _observation("o1", "8867-4", "Heart rate", "vital-signs", 72, "/min"),
            _observation("o2", "718-7", "Hemoglobin", "laboratory", 13.5, "g/dL"),
        ])
        labs = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Observation", base_url=BASE_URL,
            observation_category="labs", http_client=read_client)
        assert [o["display"] for o in labs] == ["Hemoglobin"]
        assert labs[0]["value"] == 13.5
        assert labs[0]["unit"] == "g/dL"

        vitals = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Observation", base_url=BASE_URL,
            observation_category="vitals", http_client=read_client)
        assert [o["display"] for o in vitals] == ["Heart rate"]

    def test_read_medication_request(self, mock_fhir, read_client):
        mock_fhir.seed("MedicationRequest", [{
            "resourceType": "MedicationRequest", "id": "m1", "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"text": "Lisinopril 10mg"},
            "dosageInstruction": [{"text": "1 tab daily"}],
            "authoredOn": "2026-02-01",
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "MedicationRequest", base_url=BASE_URL, http_client=read_client)
        assert out[0]["display"] == "Lisinopril 10mg"
        assert out[0]["dosage"] == "1 tab daily"
        assert out[0]["status"] == "active"

    def test_read_allergy_with_reactions(self, mock_fhir, read_client):
        mock_fhir.seed("AllergyIntolerance", [{
            "resourceType": "AllergyIntolerance", "id": "a1",
            "clinicalStatus": {"coding": [{"code": "active"}]},
            "criticality": "high",
            "code": {"text": "Penicillin"},
            "reaction": [{"manifestation": [{"text": "Hives"}]}],
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "AllergyIntolerance", base_url=BASE_URL, http_client=read_client)
        assert out[0]["display"] == "Penicillin"
        assert out[0]["criticality"] == "high"
        assert out[0]["reactions"] == ["Hives"]

    def test_read_immunization(self, mock_fhir, read_client):
        mock_fhir.seed("Immunization", [{
            "resourceType": "Immunization", "id": "i1", "status": "completed",
            "vaccineCode": {"coding": [{"system": "http://hl7.org/fhir/sid/cvx",
                                        "code": "207", "display": "COVID-19"}]},
            "occurrenceDateTime": "2025-10-01",
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Immunization", base_url=BASE_URL, http_client=read_client)
        assert out[0]["display"] == "COVID-19"
        assert out[0]["code"]["code"] == "207"

    def test_read_document_reference(self, mock_fhir, read_client):
        mock_fhir.seed("DocumentReference", [{
            "resourceType": "DocumentReference", "id": "d1", "status": "current",
            "docStatus": "final",
            "type": {"coding": [{"display": "Progress note"}]},
            "category": [{"coding": [{"display": "Clinical Note"}]}],
            "author": [{"display": "Dr. Smith"}],
            "date": "2026-04-01",
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "DocumentReference", base_url=BASE_URL, http_client=read_client)
        assert out[0]["type"] == "Progress note"
        assert out[0]["author"] == "Dr. Smith"

    def test_read_encounter(self, mock_fhir, read_client):
        mock_fhir.seed("Encounter", [{
            "resourceType": "Encounter", "id": "e1", "status": "finished",
            "type": [{"text": "ED visit"}],
            "period": {"start": "2026-01-01T08:00:00Z", "end": "2026-01-01T12:00:00Z"},
            "reasonCode": [{"text": "Chest pain"}],
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Encounter", base_url=BASE_URL, http_client=read_client)
        assert out[0]["type"] == "ED visit"
        assert out[0]["start"] == "2026-01-01"
        assert out[0]["reason"] == "Chest pain"

    def test_read_procedure(self, mock_fhir, read_client):
        mock_fhir.seed("Procedure", [{
            "resourceType": "Procedure", "id": "p1", "status": "completed",
            "code": {"text": "Appendectomy", "coding": [
                {"system": "http://snomed.info/sct", "code": "80146002"}]},
            "performedDateTime": "2025-06-15",
        }])
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Procedure", base_url=BASE_URL, http_client=read_client)
        assert out[0]["display"] == "Appendectomy"
        assert out[0]["performed"] == "2025-06-15"

    def test_read_error_fails_soft_to_empty(self, mock_fhir, read_client):
        mock_fhir.fail("Condition", 500)
        out = fhir_patient_search.read_uscdi_resources(
            PATIENT_ID, "Condition", base_url=BASE_URL, http_client=read_client)
        assert out == []


# ==========================================================================
# fhir_patient_search.read_uscdi_summary — fan-out
# ==========================================================================
class TestReadUscdiSummary:
    def test_summary_fans_out_all_sections(self, mock_fhir, read_client):
        mock_fhir.seed("Condition", [_condition("c1", "I10", "Hypertension")])
        mock_fhir.seed("Observation", [
            _observation("o1", "8867-4", "Heart rate", "vital-signs", 72, "/min"),
            _observation("o2", "718-7", "Hemoglobin", "laboratory", 13.5, "g/dL"),
        ])
        summary = fhir_patient_search.read_uscdi_summary(
            PATIENT_ID, base_url=BASE_URL, http_client=read_client)
        # Every section key present.
        for key in ("problems", "medications", "allergies", "immunizations",
                    "labs", "vitals", "documents", "encounters", "procedures"):
            assert key in summary
        assert summary["problems"][0]["display"] == "Hypertension"
        assert [o["display"] for o in summary["labs"]] == ["Hemoglobin"]
        assert [o["display"] for o in summary["vitals"]] == ["Heart rate"]

    def test_summary_missing_patient_empty(self, mock_fhir, read_client):
        assert fhir_patient_search.read_uscdi_summary(
            "", base_url=BASE_URL, http_client=read_client) == {}


# ==========================================================================
# ehr_gateway uniform vendor read routing
# ==========================================================================
class TestGatewayReads:
    @pytest.mark.parametrize("vendor", ["epic", "oracle", "athena"])
    def test_read_resource_routes_all_vendors(self, vendor, mock_fhir, monkeypatch):
        """All three vendors share one read path through fhir_patient_search."""
        mock_fhir.seed("Condition", [_condition("c1", "I10", "Hypertension")])

        captured = {}

        def _fake_read(patient_id, resource_type, **kw):
            captured["patient_id"] = patient_id
            captured["resource_type"] = resource_type
            captured["base_url"] = kw.get("base_url")
            captured["token"] = kw.get("access_token")
            return [{"id": "c1", "display": "Hypertension"}]

        monkeypatch.setattr(fhir_patient_search, "read_uscdi_resources", _fake_read)
        cfg = {"vendor": vendor, "base_url": BASE_URL, "access_token": "tok"}
        out = ehr_gateway.read_resource(
            "Condition", ehr_config=cfg, patient_id=PATIENT_ID)
        assert out == [{"id": "c1", "display": "Hypertension"}]
        assert captured["base_url"] == BASE_URL
        assert captured["token"] == "tok"
        assert captured["resource_type"] == "Condition"

    def test_read_resource_hl7v2_returns_empty(self):
        out = ehr_gateway.read_resource(
            "Condition", ehr_config={"vendor": "hl7v2"}, patient_id=PATIENT_ID)
        assert out == []

    def test_read_resource_without_patient_uses_local_store(self):
        # No patient_id + epic vendor -> falls through to local mock store ([]).
        out = ehr_gateway.read_resource(
            "Condition", ehr_config={"vendor": "epic", "base_url": BASE_URL})
        assert out == []

    def test_read_resource_mock_vendor_local_store(self):
        from services import fhir_writer
        fhir_writer.clear_local()
        fhir_writer.write(fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain"))
        out = ehr_gateway.read_resource("Condition", ehr_config={"vendor": "mock"})
        assert any(r.get("code") for r in out)
        fhir_writer.clear_local()

    def test_read_uscdi_summary_routes_through_search(self, monkeypatch):
        def _fake_summary(patient_id, **kw):
            return {"problems": [{"display": "HTN"}], "labs": []}
        monkeypatch.setattr(fhir_patient_search, "read_uscdi_summary", _fake_summary)
        cfg = {"vendor": "oracle", "base_url": BASE_URL, "access_token": "tok"}
        out = ehr_gateway.read_uscdi_summary(PATIENT_ID, ehr_config=cfg)
        assert out["problems"][0]["display"] == "HTN"

    def test_read_uscdi_summary_no_base_url_empty(self):
        assert ehr_gateway.read_uscdi_summary(
            PATIENT_ID, ehr_config={"vendor": "mock"}) == {}
