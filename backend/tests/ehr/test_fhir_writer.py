"""Offline tests for ``backend/services/fhir_writer.py``.

Covers the resource builders, the local mock-store fallback, and the remote
dispatch branch via an injected fake ``requests`` module + an httpx
``MockTransport`` exercising the same recording core.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from services import fhir_writer


# --------------------------------------------------------------------------
# Resource builders
# --------------------------------------------------------------------------
class TestResourceBuilders:
    def test_document_reference_text_only(self):
        r = fhir_writer.build_document_reference(
            patient_ref="Patient/p1", note_text="hello note")
        assert r["resourceType"] == "DocumentReference"
        assert r["status"] == "current"
        assert r["subject"]["reference"] == "Patient/p1"
        assert len(r["content"]) == 1
        decoded = base64.b64decode(r["content"][0]["attachment"]["data"])
        assert decoded == b"hello note"
        assert r["content"][0]["attachment"]["contentType"] == "text/plain"

    def test_document_reference_with_pdf(self):
        r = fhir_writer.build_document_reference(
            patient_ref="Patient/p1", note_text="note", note_pdf_bytes=b"%PDF-1.4")
        assert len(r["content"]) == 2
        pdf_part = r["content"][0]["attachment"]
        assert pdf_part["contentType"] == "application/pdf"
        assert base64.b64decode(pdf_part["data"]) == b"%PDF-1.4"

    def test_condition(self):
        r = fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain")
        assert r["resourceType"] == "Condition"
        coding = r["code"]["coding"][0]
        assert coding["code"] == "R07.9"
        assert coding["system"] == "http://hl7.org/fhir/sid/icd-10-cm"
        assert r["clinicalStatus"]["coding"][0]["code"] == "active"
        assert r["verificationStatus"]["coding"][0]["code"] == "provisional"

    def test_condition_custom_clinical_status(self):
        r = fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="I10", display="HTN",
            clinical_status="resolved")
        assert r["clinicalStatus"]["coding"][0]["code"] == "resolved"

    def test_allergy_with_reaction(self):
        r = fhir_writer.build_allergy(
            patient_ref="Patient/p1", substance_display="Penicillin",
            reaction="Hives", severity="severe")
        assert r["resourceType"] == "AllergyIntolerance"
        assert r["patient"]["reference"] == "Patient/p1"
        assert r["code"]["text"] == "Penicillin"
        assert r["reaction"][0]["severity"] == "severe"
        assert r["reaction"][0]["manifestation"][0]["text"] == "Hives"

    def test_allergy_without_reaction(self):
        r = fhir_writer.build_allergy(
            patient_ref="Patient/p1", substance_display="Latex")
        assert r["reaction"] == []

    def test_observation_vital(self):
        r = fhir_writer.build_observation_vital(
            patient_ref="Patient/p1", code_loinc="8867-4",
            display="Heart rate", value=88.0, unit="beats/minute")
        assert r["resourceType"] == "Observation"
        assert r["category"][0]["coding"][0]["code"] == "vital-signs"
        assert r["valueQuantity"]["value"] == 88.0
        assert r["valueQuantity"]["unit"] == "beats/minute"

    def test_observation_social(self):
        r = fhir_writer.build_observation_social(
            patient_ref="Patient/p1", code_loinc="76513-1",
            display="Housing status", value_text="stable")
        assert r["category"][0]["coding"][0]["code"] == "social-history"
        assert r["valueString"] == "stable"

    def test_immunization(self):
        r = fhir_writer.build_immunization(
            patient_ref="Patient/p1", vaccine_cvx="207", vaccine_display="COVID-19")
        assert r["resourceType"] == "Immunization"
        assert r["status"] == "completed"
        assert r["vaccineCode"]["coding"][0]["code"] == "207"


# --------------------------------------------------------------------------
# Local mock-store fallback (no FHIR_BASE_URL)
# --------------------------------------------------------------------------
class TestLocalStore:
    def setup_method(self):
        fhir_writer.clear_local()

    def teardown_method(self):
        fhir_writer.clear_local()

    def test_write_falls_back_to_local_when_no_base_url(self, monkeypatch):
        monkeypatch.delenv("FHIR_BASE_URL", raising=False)
        resource = fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain")
        result = fhir_writer.write(resource)
        assert result["stored"] == "mock"
        assert result["resourceType"] == "Condition"
        assert result["id"]
        assert result["url"].startswith("local://Condition/")

    def test_local_store_assigns_id_and_meta(self, monkeypatch):
        monkeypatch.delenv("FHIR_BASE_URL", raising=False)
        resource = fhir_writer.build_allergy(
            patient_ref="Patient/p1", substance_display="Latex")
        fhir_writer.write(resource)
        stored = fhir_writer.list_local("AllergyIntolerance")
        assert len(stored) == 1
        assert stored[0]["id"]
        assert "lastUpdated" in stored[0]["meta"]

    def test_list_local_all_types(self, monkeypatch):
        monkeypatch.delenv("FHIR_BASE_URL", raising=False)
        fhir_writer.write(fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain"))
        fhir_writer.write(fhir_writer.build_immunization(
            patient_ref="Patient/p1", vaccine_cvx="207", vaccine_display="COVID-19"))
        everything = fhir_writer.list_local()
        types = {r["resourceType"] for r in everything}
        assert types == {"Condition", "Immunization"}

    def test_clear_local(self, monkeypatch):
        monkeypatch.delenv("FHIR_BASE_URL", raising=False)
        fhir_writer.write(fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain"))
        assert fhir_writer.list_local()
        fhir_writer.clear_local()
        assert fhir_writer.list_local() == []


# --------------------------------------------------------------------------
# Remote dispatch — fake-requests path
# --------------------------------------------------------------------------
class TestRemoteWriteFakeRequests:
    def setup_method(self):
        fhir_writer.clear_local()

    def teardown_method(self):
        fhir_writer.clear_local()

    def test_remote_write_success_201(self, fake_requests):
        resource = fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain")
        result = fhir_writer.write(
            resource, fhir_base_url="https://mock-fhir.test/r4",
            access_token="tok-123")
        assert result["ok"] is True
        assert result["stored"] == "remote"
        assert result["id"]
        assert result["url"].endswith("/_history/1")
        assert fake_requests.post_count == 1

    def test_remote_write_sends_bearer_token(self, fake_requests):
        resource = fhir_writer.build_observation_vital(
            patient_ref="Patient/p1", code_loinc="8867-4",
            display="Heart rate", value=72, unit="beats/minute")
        fhir_writer.write(resource, fhir_base_url="https://mock-fhir.test/r4",
                          access_token="secret-token")
        captured = fake_requests.last()
        assert captured.headers["Authorization"] == "Bearer secret-token"
        assert captured.headers["Content-Type"] == "application/fhir+json"

    def test_remote_write_posts_to_resource_type_path(self, fake_requests):
        resource = fhir_writer.build_allergy(
            patient_ref="Patient/p1", substance_display="Penicillin")
        fhir_writer.write(resource, fhir_base_url="https://mock-fhir.test/r4/")
        assert fake_requests.last().url == "https://mock-fhir.test/r4/AllergyIntolerance"

    def test_remote_write_records_resource_body(self, fake_requests):
        resource = fhir_writer.build_document_reference(
            patient_ref="Patient/p99", note_text="triage note")
        fhir_writer.write(resource, fhir_base_url="https://mock-fhir.test/r4")
        captured = fake_requests.last()
        assert captured.body["resourceType"] == "DocumentReference"
        assert captured.body["subject"]["reference"] == "Patient/p99"

    @pytest.mark.parametrize("status", [401, 409, 422])
    def test_remote_write_error_falls_back_to_local(self, fake_requests, status):
        fake_requests.fail("Condition", status)
        resource = fhir_writer.build_condition(
            patient_ref="Patient/p1", icd10="R07.9", display="Chest pain")
        result = fhir_writer.write(
            resource, fhir_base_url="https://mock-fhir.test/r4")
        # raise_for_status() trips -> writer catches -> local fallback.
        assert result["stored"] == "mock"
        assert fhir_writer.list_local("Condition")
        assert fake_requests.post_count == 1

    def test_remote_write_fail_next_then_recovers(self, fake_requests):
        fake_requests.fail_next(409)
        first = fhir_writer.write(
            fhir_writer.build_condition(
                patient_ref="Patient/p1", icd10="R07.9", display="Chest pain"),
            fhir_base_url="https://mock-fhir.test/r4")
        assert first["stored"] == "mock"  # 409 -> fallback
        second = fhir_writer.write(
            fhir_writer.build_condition(
                patient_ref="Patient/p1", icd10="I10", display="HTN"),
            fhir_base_url="https://mock-fhir.test/r4")
        assert second["stored"] == "remote"  # error cleared


# --------------------------------------------------------------------------
# httpx.MockTransport path — exercises the same recording core
# --------------------------------------------------------------------------
class TestMockTransportPath:
    def test_httpx_transport_records_201(self, mock_fhir, load_fixture):
        transport = mock_fhir.httpx_transport()
        with httpx.Client(transport=transport) as client:
            resp = client.post(
                "https://mock-fhir.test/r4/Patient",
                json=load_fixture("patient"),
                headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 201
        assert resp.headers["Location"].endswith("/_history/1")
        assert resp.json()["id"]
        assert mock_fhir.post_count == 1
        assert mock_fhir.last().resource_type == "Patient"

    @pytest.mark.parametrize("status", [401, 409, 422])
    def test_httpx_transport_error_returns_operation_outcome(self, mock_fhir, status):
        mock_fhir.fail("Condition", status)
        transport = mock_fhir.httpx_transport()
        with httpx.Client(transport=transport) as client:
            resp = client.post("https://mock-fhir.test/r4/Condition",
                                json={"resourceType": "Condition"})
        assert resp.status_code == status
        body = resp.json()
        assert body["resourceType"] == "OperationOutcome"
        assert body["issue"][0]["severity"] == "error"

    def test_httpx_transport_of_type_filter(self, mock_fhir):
        transport = mock_fhir.httpx_transport()
        with httpx.Client(transport=transport) as client:
            client.post("https://mock-fhir.test/r4/Condition",
                        json={"resourceType": "Condition"})
            client.post("https://mock-fhir.test/r4/Observation",
                        json={"resourceType": "Observation"})
        assert len(mock_fhir.of_type("Condition")) == 1
        assert len(mock_fhir.of_type("Observation")) == 1

    def test_mock_server_reset(self, mock_fhir):
        transport = mock_fhir.httpx_transport()
        with httpx.Client(transport=transport) as client:
            client.post("https://mock-fhir.test/r4/Patient",
                        json={"resourceType": "Patient"})
        assert mock_fhir.post_count == 1
        mock_fhir.reset()
        assert mock_fhir.post_count == 0
        assert mock_fhir.requests == []


# --------------------------------------------------------------------------
# Fixture integrity
# --------------------------------------------------------------------------
class TestFixtures:
    @pytest.mark.parametrize("name,resource_type", [
        ("patient", "Patient"),
        ("document_reference", "DocumentReference"),
        ("condition", "Condition"),
        ("allergy_intolerance", "AllergyIntolerance"),
        ("observation", "Observation"),
        ("provenance", "Provenance"),
    ])
    def test_fixture_resource_type(self, load_fixture, name, resource_type):
        assert load_fixture(name)["resourceType"] == resource_type

    @pytest.mark.parametrize("name,status", [
        ("operation_outcome_401", "401"),
        ("operation_outcome_409", "409"),
        ("operation_outcome_422", "422"),
    ])
    def test_operation_outcome_fixtures(self, load_fixture, name, status):
        oo = load_fixture(name)
        assert oo["resourceType"] == "OperationOutcome"
        assert oo["issue"][0]["severity"] == "error"
        assert status in oo["issue"][0]["details"]["text"]

    def test_writer_output_round_trips_through_mock(self, mock_fhir, load_fixture):
        """A builder-produced resource posts cleanly to the mock server."""
        resource = fhir_writer.build_condition(
            patient_ref="Patient/test-patient-001", icd10="R07.9",
            display="Chest pain, unspecified")
        transport = mock_fhir.httpx_transport()
        with httpx.Client(transport=transport) as client:
            resp = client.post("https://mock-fhir.test/r4/Condition", json=resource)
        assert resp.status_code == 201
        assert resp.json()["code"]["coding"][0]["code"] == "R07.9"
