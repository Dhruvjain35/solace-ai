"""Vendor EHR adapter tests — guarded by ``pytest.importorskip``.

The vendor-specific adapter modules (``services.ehr_epic``,
``services.ehr_oracle``, ``services.ehr_athena``) are part of the EHR
write-back roadmap. Each adapter's tests skip cleanly when its module is
absent, so this file is safe to run before the adapters land and grows
coverage automatically once they do.

When an adapter IS present, these tests exercise its real public API against
the offline mock FHIR server (``conftest.py`` ``mock_fhir`` /
``injectable_client`` fixtures) — no network, no vendor account.
"""
from __future__ import annotations

import httpx
import pytest

PATIENT_REF = "Patient/test-patient-001"


# ==========================================================================
# Epic — services.ehr_epic.EpicAdapter
# ==========================================================================
class TestEpicAdapter:
    @pytest.fixture
    def ehr_epic(self):
        return pytest.importorskip(
            "services.ehr_epic",
            reason="services.ehr_epic adapter not implemented yet")

    def test_module_exposes_adapter(self, ehr_epic):
        assert hasattr(ehr_epic, "EpicAdapter")
        assert hasattr(ehr_epic, "EpicWriteError")

    def test_offline_mode_uses_mock_store(self, ehr_epic):
        """With no base_url the adapter falls back to fhir_writer's mock store."""
        adapter = ehr_epic.EpicAdapter()
        assert adapter.online is False
        result = adapter.write_condition_to_problem_list(
            patient_ref=PATIENT_REF, icd10="R07.9", display="Chest pain")
        assert result["stored"] == "mock"
        assert result["id"]

    def test_online_document_reference_write_201(self, ehr_epic, mock_fhir,
                                                 injectable_client):
        adapter = ehr_epic.EpicAdapter(
            base_url="https://epic.test/api/FHIR/R4",
            access_token="epic-tok", http_client=injectable_client)
        assert adapter.online is True
        result = adapter.write_document_reference(
            patient_ref=PATIENT_REF, note_text="ED triage note")
        assert result["ok"] is True
        assert result["stored"] == "epic"
        assert result["id"]
        posted = mock_fhir.last()
        assert posted.resource_type == "DocumentReference"
        assert posted.headers["Authorization"] == "Bearer epic-tok"

    def test_online_condition_carries_problem_list_category(
            self, ehr_epic, mock_fhir, injectable_client):
        adapter = ehr_epic.EpicAdapter(
            base_url="https://epic.test/api/FHIR/R4",
            access_token="epic-tok", http_client=injectable_client)
        adapter.write_condition_to_problem_list(
            patient_ref=PATIENT_REF, icd10="I10",
            display="Hypertension", snomed="38341003")
        body = mock_fhir.last().body
        assert body["category"][0]["coding"][0]["code"] == "problem-list-item"
        # SNOMED prepended as the primary coding.
        assert body["code"]["coding"][0]["system"] == "http://snomed.info/sct"

    @pytest.mark.parametrize("status", [401, 409, 422])
    def test_error_raises_epic_write_error(self, ehr_epic, mock_fhir,
                                           injectable_client, status):
        mock_fhir.fail("Condition", status)
        adapter = ehr_epic.EpicAdapter(
            base_url="https://epic.test/api/FHIR/R4",
            access_token="epic-tok", http_client=injectable_client)
        with pytest.raises(ehr_epic.EpicWriteError) as exc:
            adapter.write_condition_to_problem_list(
                patient_ref=PATIENT_REF, icd10="R07.9", display="Chest pain")
        assert exc.value.status_code == status
        assert exc.value.resource_type == "Condition"

    def test_unknown_note_type_rejected(self, ehr_epic):
        adapter = ehr_epic.EpicAdapter()
        with pytest.raises(ehr_epic.EpicWriteError):
            adapter.write_document_reference(
                patient_ref=PATIENT_REF, note_text="x", note_type="bogus")

    def test_parse_operation_outcome_401_fixture(self, ehr_epic, load_fixture):
        issues = ehr_epic.parse_operation_outcome(
            load_fixture("operation_outcome_401"))
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"
        assert issues[0]["code"] == "security"


# ==========================================================================
# Oracle Health — services.ehr_oracle.OracleEHRClient
# ==========================================================================
class TestOracleAdapter:
    @pytest.fixture
    def ehr_oracle(self):
        return pytest.importorskip(
            "services.ehr_oracle",
            reason="services.ehr_oracle adapter not implemented yet")

    def test_module_exposes_client(self, ehr_oracle):
        assert hasattr(ehr_oracle, "OracleEHRClient")
        assert hasattr(ehr_oracle, "OracleWriteError")

    def test_local_mode_uses_mock_store(self, ehr_oracle):
        client = ehr_oracle.OracleEHRClient()
        assert client.is_local is True
        result = client.write_condition(
            patient_ref=PATIENT_REF, icd10="R07.9", display="Chest pain")
        assert result["stored"] == "mock"
        assert result["id"]

    def test_remote_condition_write_parses_location_header(
            self, ehr_oracle, mock_fhir, injectable_client):
        client = ehr_oracle.OracleEHRClient(
            base_url="https://fhir-ehr.cerner.com/r4/tenant-guid",
            access_token="oracle-tok", http_client=injectable_client)
        assert client.is_local is False
        result = client.write_condition(
            patient_ref=PATIENT_REF, icd10="R07.9", display="Chest pain")
        assert result["ok"] is True
        assert result["stored"] == "oracle"
        # Oracle id comes from the Location header, not the body.
        assert result["id"]
        body = mock_fhir.last().body
        assert body["category"][0]["coding"][0]["code"] == "problem-list-item"

    def test_remote_write_sends_fhir_content_type_and_bearer(
            self, ehr_oracle, mock_fhir, injectable_client):
        client = ehr_oracle.OracleEHRClient(
            base_url="https://fhir-ehr.cerner.com/r4/tenant-guid",
            access_token="oracle-tok", http_client=injectable_client)
        client.write_document_reference(
            patient_ref=PATIENT_REF, note_text="consult note")
        headers = mock_fhir.last().headers
        assert headers["Content-Type"] == "application/fhir+json"
        assert headers["Accept"] == "application/fhir+json"
        assert headers["Authorization"] == "Bearer oracle-tok"

    def test_allergy_promotes_rxnorm_code(self, ehr_oracle, mock_fhir,
                                          injectable_client):
        client = ehr_oracle.OracleEHRClient(
            base_url="https://fhir-ehr.cerner.com/r4/tenant-guid",
            access_token="oracle-tok", http_client=injectable_client)
        client.write_allergy(
            patient_ref=PATIENT_REF, substance_display="Penicillin",
            rxnorm_code="7980")
        body = mock_fhir.last().body
        codings = body["code"]["coding"]
        assert any(c["system"] == ehr_oracle.RXNORM_SYSTEM
                   and c["code"] == "7980" for c in codings)

    @pytest.mark.parametrize("status", [401, 409, 422])
    def test_error_raises_oracle_write_error(self, ehr_oracle, mock_fhir,
                                             injectable_client, status):
        mock_fhir.fail("Observation", status)
        client = ehr_oracle.OracleEHRClient(
            base_url="https://fhir-ehr.cerner.com/r4/tenant-guid",
            access_token="oracle-tok", http_client=injectable_client)
        with pytest.raises(ehr_oracle.OracleWriteError) as exc:
            client.write_observation(
                patient_ref=PATIENT_REF, code_loinc="8867-4",
                display="Heart rate", value=88, unit="beats/minute")
        assert exc.value.status_code == status
        assert exc.value.resource_type == "Observation"


# ==========================================================================
# athenahealth — services.ehr_athena.AthenaWriteClient
# ==========================================================================
class TestAthenaAdapter:
    @pytest.fixture
    def ehr_athena(self):
        return pytest.importorskip(
            "services.ehr_athena",
            reason="services.ehr_athena adapter not implemented yet")

    def test_module_exposes_client(self, ehr_athena):
        assert hasattr(ehr_athena, "AthenaWriteClient")
        assert hasattr(ehr_athena, "AthenaConfig")
        assert hasattr(ehr_athena, "AthenaWriteError")

    def test_oauth_token_acquisition(self, ehr_athena, injectable_client):
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        token = client.get_access_token()
        assert token == "mock-access-token"

    def test_token_failure_raises_auth_error(self, ehr_athena, mock_fhir,
                                             injectable_client):
        mock_fhir.fail_next(401)
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        with pytest.raises(ehr_athena.AthenaAuthError):
            client.get_access_token()

    def test_write_document_via_fhir_surface(self, ehr_athena, mock_fhir,
                                             injectable_client):
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        result = client.write_document(
            patient_ref=PATIENT_REF, note_text="scribe progress note")
        assert result["ok"] is True
        assert result["surface"] == "fhir"
        assert result["stored"] == "athena"
        doc_posts = mock_fhir.of_type("DocumentReference")
        assert len(doc_posts) == 1
        assert "/fhir/r4/DocumentReference" in doc_posts[0].url

    def test_write_problem_via_proprietary_rest(self, ehr_athena, mock_fhir,
                                                injectable_client):
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        result = client.write_problem(
            athena_patient_id="A-123", icd10="R07.9", display="Chest pain")
        assert result["ok"] is True
        assert result["surface"] == "athena-rest"
        problem_post = mock_fhir.of_type("problems")[0]
        assert "/v1/999999/chart/A-123/problems" in problem_post.url
        assert problem_post.body["icd10code"] == "R07.9"

    def test_write_allergies_uses_put_replace_semantics(
            self, ehr_athena, mock_fhir, injectable_client):
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        result = client.write_allergies(
            athena_patient_id="A-123",
            allergies=[{"name": "penicillin"}])
        assert result["replaced"] is True
        assert result["count"] == 1
        allergy_req = mock_fhir.of_type("allergies")[0]
        assert allergy_req.method == "PUT"

    def test_write_error_raised_on_non_2xx(self, ehr_athena, mock_fhir,
                                           injectable_client):
        config = ehr_athena.AthenaConfig.for_testing()
        client = ehr_athena.AthenaWriteClient(config, http=injectable_client)
        client.get_access_token()  # succeed token first
        mock_fhir.fail("DocumentReference", 422)
        with pytest.raises(ehr_athena.AthenaWriteError) as exc:
            client.write_document(patient_ref=PATIENT_REF, note_text="x")
        assert exc.value.status == 422

    def test_loinc_vital_translation(self, ehr_athena):
        item = ehr_athena.loinc_vital_to_athena("8867-4", 72)
        assert item["clinicalelementid"] == "VITALS.PULSE"
        assert item["value"] == "72"
        with pytest.raises(ehr_athena.AthenaWriteError):
            ehr_athena.loinc_vital_to_athena("0000-0", 1)


# ==========================================================================
# Vendor registry — lib/ehr_vendors.py (this module exists today)
# ==========================================================================
class TestEHRVendorRegistry:
    def test_vendor_registry_importable(self):
        ehr_vendors = pytest.importorskip("lib.ehr_vendors")
        assert hasattr(ehr_vendors, "EHRVendor")

    def test_ehr_vendor_to_public_dict_hides_secrets(self):
        ehr_vendors = pytest.importorskip("lib.ehr_vendors")
        vendor = ehr_vendors.EHRVendor(
            id="smart", label="SMART Sandbox", color="#0a84ff",
            fhir_base_url="https://launch.smarthealthit.org/v/r4/fhir",
            authorize_url="https://launch.smarthealthit.org/v/r4/auth/authorize",
            token_url="https://launch.smarthealthit.org/v/r4/auth/token",
            client_id="solace-demo", scopes=("openid", "fhirUser"),
            sandbox=True)
        public = vendor.to_public_dict()
        assert public == {
            "id": "smart", "label": "SMART Sandbox",
            "color": "#0a84ff", "sandbox": True,
        }
        # Secrets must never reach the frontend.
        assert "client_id" not in public
        assert "token_url" not in public


# ==========================================================================
# ehr_gateway — vendor dispatch facade (importorskip-guarded)
# ==========================================================================
class TestEHRGateway:
    def test_gateway_importable_or_skip(self):
        gateway = pytest.importorskip(
            "services.ehr_gateway",
            reason="services.ehr_gateway not present")
        assert gateway is not None
