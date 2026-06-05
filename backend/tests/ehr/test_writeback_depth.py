"""Write-back depth tests — ServiceRequest (orders), Procedure, clinical-note
DocumentReference, problem-list Condition — plus the confirm-before-write gate.

All offline against the mock FHIR server. Confirms the new builders produce
valid US Core-shaped resources and that the vendor adapters (Epic / Oracle /
athena) can write a ServiceRequest order reusing the single shared builder.
"""
from __future__ import annotations

import pytest

from services import fhir_writer

PATIENT_REF = "Patient/test-patient-001"


# ==========================================================================
# fhir_writer builders — new write-back resource types
# ==========================================================================
class TestServiceRequestBuilder:
    def test_order_defaults_active(self):
        r = fhir_writer.build_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel")
        assert r["resourceType"] == "ServiceRequest"
        assert r["status"] == "active"      # an order is live
        assert r["intent"] == "order"
        assert r["code"]["coding"][0]["code"] == "58410-2"
        assert r["subject"]["reference"] == PATIENT_REF
        assert r["priority"] == "routine"

    def test_proposal_is_draft(self):
        """An AI-suggested (unsigned) order must never look live."""
        r = fhir_writer.build_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel",
            intent="proposal")
        assert r["intent"] == "proposal"
        assert r["status"] == "draft"

    def test_reason_and_encounter(self):
        r = fhir_writer.build_service_request(
            patient_ref=PATIENT_REF, code="71020", display="Chest X-ray",
            system="http://www.ama-assn.org/go/cpt",
            reason_text="Rule out pneumonia",
            encounter_ref="Encounter/e1")
        assert r["reasonCode"][0]["text"] == "Rule out pneumonia"
        assert r["encounter"]["reference"] == "Encounter/e1"
        assert r["code"]["coding"][0]["system"] == "http://www.ama-assn.org/go/cpt"


class TestProcedureBuilder:
    def test_procedure_defaults(self):
        r = fhir_writer.build_procedure(
            patient_ref=PATIENT_REF, code="80146002", display="Appendectomy")
        assert r["resourceType"] == "Procedure"
        assert r["status"] == "completed"
        assert r["code"]["coding"][0]["system"] == "http://snomed.info/sct"
        assert "performedDateTime" in r


# ==========================================================================
# Confirm-before-write gate
# ==========================================================================
class TestConfirmBeforeWrite:
    def setup_method(self):
        fhir_writer.clear_local()

    def teardown_method(self):
        fhir_writer.clear_local()

    def test_preview_performs_no_io(self):
        resource = fhir_writer.build_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel")
        preview = fhir_writer.preview_write(resource)
        assert preview["confirm_required"] is True
        assert preview["resource_type"] == "ServiceRequest"
        assert "CBC panel" in preview["label"]
        # Nothing was written.
        assert fhir_writer.list_local("ServiceRequest") == []

    def test_unconfirmed_returns_preview_no_write(self):
        resource = fhir_writer.build_condition(
            patient_ref=PATIENT_REF, icd10="I10", display="Hypertension")
        out = fhir_writer.confirm_and_write(resource, confirmed=False)
        assert out["confirm_required"] is True
        assert fhir_writer.list_local("Condition") == []

    def test_confirmed_writes_with_provenance(self, monkeypatch):
        monkeypatch.delenv("FHIR_BASE_URL", raising=False)
        resource = fhir_writer.build_condition(
            patient_ref=PATIENT_REF, icd10="I10", display="Hypertension")
        out = fhir_writer.confirm_and_write(
            resource, confirmed=True,
            signing_clinician_ref="Practitioner/dr-1",
            signing_clinician_display="Dr. Smith")
        assert out["resource"]["stored"] == "mock"
        assert out["provenance"]["stored"] == "mock"
        # Condition + Provenance both landed.
        assert fhir_writer.list_local("Condition")
        assert fhir_writer.list_local("Provenance")

    def test_document_reference_preview_label(self):
        resource = fhir_writer.build_document_reference(
            patient_ref=PATIENT_REF, note_text="ED note")
        preview = fhir_writer.preview_write(resource)
        assert preview["resource_type"] == "DocumentReference"
        assert "note" in preview["label"].lower()


# ==========================================================================
# Vendor adapters — ServiceRequest order write-back
# ==========================================================================
class TestVendorServiceRequestWrite:
    def test_epic_write_service_request(self, injectable_client, mock_fhir):
        ehr_epic = pytest.importorskip("services.ehr_epic")
        adapter = ehr_epic.EpicAdapter(
            base_url="https://epic.test/api/FHIR/R4",
            access_token="epic-tok", http_client=injectable_client)
        result = adapter.write_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel",
            encounter_ref="Encounter/e1")
        assert result["ok"] is True
        assert result["stored"] == "epic"
        posted = mock_fhir.last()
        assert posted.resource_type == "ServiceRequest"
        assert posted.body["encounter"]["reference"] == "Encounter/e1"

    def test_oracle_write_service_request(self, injectable_client, mock_fhir):
        ehr_oracle = pytest.importorskip("services.ehr_oracle")
        client = ehr_oracle.OracleEHRClient(
            base_url="https://fhir-ehr.cerner.com/r4/tenant",
            access_token="oracle-tok", http_client=injectable_client)
        result = client.write_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel",
            intent="proposal")
        assert result["stored"] == "oracle"
        body = mock_fhir.last().body
        assert body["resourceType"] == "ServiceRequest"
        assert body["intent"] == "proposal"
        assert body["status"] == "draft"

    def test_oracle_service_request_local_mode(self):
        ehr_oracle = pytest.importorskip("services.ehr_oracle")
        client = ehr_oracle.OracleEHRClient()
        result = client.write_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel")
        assert result["stored"] == "mock"
        assert result["id"]

    def test_athena_write_service_request(self, injectable_client, mock_fhir):
        ehr_athena = pytest.importorskip("services.ehr_athena")
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        result = client.write_service_request(
            patient_ref=PATIENT_REF, code="58410-2", display="CBC panel")
        assert result["ok"] is True
        assert result["surface"] == "fhir"
        assert result["resourceType"] == "ServiceRequest"
        posts = mock_fhir.of_type("ServiceRequest")
        assert posts and "/fhir/r4/ServiceRequest" in posts[0].url
