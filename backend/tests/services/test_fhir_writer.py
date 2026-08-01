"""Unit tests for ``services.fhir_writer`` — FHIR R4 resource builders.

Scope is the pure builder functions plus the local mock-store dispatcher
(``write`` with no FHIR_BASE_URL). Remote HTTP write paths are not exercised.
This file lives under ``tests/services/`` and is independent of the EHR
agent's ``tests/ehr/test_fhir_writer.py``; it focuses on resource structure.
"""
from __future__ import annotations

import base64

import pytest

# Imported directly rather than via pytest.importorskip. A guard turns
# "this module is broken" into "these tests were skipped" and lets a red
# build report green, which is how a genuine import failure went unnoticed.
import services.fhir_writer as fw


@pytest.fixture(autouse=True)
def _clean_store():
    """Each test gets a fresh local mock store."""
    fw.clear_local()
    yield
    fw.clear_local()


PATIENT = "Patient/abc-123"


# ---- _now_iso --------------------------------------------------------------
def test_now_iso_is_utc_z():
    ts = fw._now_iso()
    assert ts.endswith("Z")
    assert "T" in ts


# ---- DocumentReference -----------------------------------------------------
class TestDocumentReference:
    def test_basic_structure(self):
        r = fw.build_document_reference(patient_ref=PATIENT, note_text="hello note")
        assert r["resourceType"] == "DocumentReference"
        assert r["status"] == "current"
        assert r["subject"]["reference"] == PATIENT

    def test_text_content_is_base64(self):
        r = fw.build_document_reference(patient_ref=PATIENT, note_text="hello note")
        text_att = [c["attachment"] for c in r["content"]
                    if c["attachment"]["contentType"] == "text/plain"][0]
        decoded = base64.b64decode(text_att["data"]).decode("utf-8")
        assert decoded == "hello note"

    def test_pdf_attachment_added(self):
        r = fw.build_document_reference(
            patient_ref=PATIENT, note_text="n", note_pdf_bytes=b"%PDF-1.4",
        )
        types = {c["attachment"]["contentType"] for c in r["content"]}
        assert "application/pdf" in types
        assert "text/plain" in types

    def test_us_core_category_present(self):
        r = fw.build_document_reference(patient_ref=PATIENT, note_text="n")
        assert r["category"][0]["coding"][0]["code"] == "clinical-note"

    def test_loinc_type_default(self):
        r = fw.build_document_reference(patient_ref=PATIENT, note_text="n")
        assert r["type"]["coding"][0]["code"] == "11506-3"
        assert r["type"]["coding"][0]["system"] == "http://loinc.org"


# ---- Condition -------------------------------------------------------------
class TestCondition:
    def test_structure(self):
        r = fw.build_condition(patient_ref=PATIENT, icd10="K35.80",
                               display="Acute appendicitis")
        assert r["resourceType"] == "Condition"
        assert r["code"]["coding"][0]["code"] == "K35.80"
        assert r["code"]["coding"][0]["system"] == "http://hl7.org/fhir/sid/icd-10-cm"

    def test_problem_list_category(self):
        r = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2")
        assert r["category"][0]["coding"][0]["code"] == "problem-list-item"

    def test_clinical_status_default_active(self):
        r = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2")
        assert r["clinicalStatus"]["coding"][0]["code"] == "active"

    def test_verification_status_provisional(self):
        r = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2")
        assert r["verificationStatus"]["coding"][0]["code"] == "provisional"

    def test_custom_clinical_status(self):
        r = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2",
                               clinical_status="resolved")
        assert r["clinicalStatus"]["coding"][0]["code"] == "resolved"


# ---- AllergyIntolerance ----------------------------------------------------
class TestAllergy:
    def test_structure(self):
        r = fw.build_allergy(patient_ref=PATIENT, substance_display="Penicillin")
        assert r["resourceType"] == "AllergyIntolerance"
        assert r["patient"]["reference"] == PATIENT
        assert r["code"]["text"] == "Penicillin"

    def test_no_reaction_empty_list(self):
        r = fw.build_allergy(patient_ref=PATIENT, substance_display="Penicillin")
        assert r["reaction"] == []

    def test_reaction_populated(self):
        r = fw.build_allergy(patient_ref=PATIENT, substance_display="Penicillin",
                             reaction="hives", severity="severe")
        assert r["reaction"][0]["manifestation"][0]["text"] == "hives"
        assert r["reaction"][0]["severity"] == "severe"


# ---- Observation vital -----------------------------------------------------
class TestObservationVital:
    def test_structure(self):
        r = fw.build_observation_vital(patient_ref=PATIENT, code_loinc="8867-4",
                                       display="Heart rate", value=72, unit="bpm")
        assert r["resourceType"] == "Observation"
        assert r["category"][0]["coding"][0]["code"] == "vital-signs"
        assert r["valueQuantity"]["value"] == 72

    def test_ucum_code_mapped(self):
        r = fw.build_observation_vital(patient_ref=PATIENT, code_loinc="8867-4",
                                       display="HR", value=72, unit="bpm")
        assert r["valueQuantity"]["code"] == "/min"

    def test_ucum_mmhg_mapped(self):
        r = fw.build_observation_vital(patient_ref=PATIENT, code_loinc="8480-6",
                                       display="SBP", value=120, unit="mmHg")
        assert r["valueQuantity"]["code"] == "mm[Hg]"

    def test_unknown_unit_falls_back_to_raw(self):
        r = fw.build_observation_vital(patient_ref=PATIENT, code_loinc="x",
                                       display="d", value=1, unit="widgets")
        assert r["valueQuantity"]["code"] == "widgets"


# ---- Observation social ----------------------------------------------------
class TestObservationSocial:
    def test_structure(self):
        r = fw.build_observation_social(patient_ref=PATIENT, code_loinc="76437-3",
                                        display="Housing", value_text="stable")
        assert r["category"][0]["coding"][0]["code"] == "social-history"
        assert r["valueString"] == "stable"


# ---- Immunization ----------------------------------------------------------
class TestImmunization:
    def test_structure(self):
        r = fw.build_immunization(patient_ref=PATIENT, vaccine_cvx="140",
                                  vaccine_display="Influenza")
        assert r["resourceType"] == "Immunization"
        assert r["vaccineCode"]["coding"][0]["code"] == "140"

    def test_primary_source_false(self):
        r = fw.build_immunization(patient_ref=PATIENT, vaccine_cvx="140",
                                  vaccine_display="Influenza")
        assert r["primarySource"] is False


# ---- MedicationStatement ---------------------------------------------------
class TestMedicationStatement:
    def test_structure(self):
        r = fw.build_medication_statement(patient_ref=PATIENT, rxnorm="860975",
                                          display="Metformin 500mg")
        assert r["resourceType"] == "MedicationStatement"
        assert r["medicationCodeableConcept"]["coding"][0]["code"] == "860975"

    def test_default_status_active(self):
        r = fw.build_medication_statement(patient_ref=PATIENT, rxnorm="x", display="d")
        assert r["status"] == "active"

    def test_reconciliation_category(self):
        r = fw.build_medication_statement(patient_ref=PATIENT, rxnorm="x", display="d")
        assert r["category"]["coding"][0]["code"] == "patientspecified"

    def test_dosage_omitted_when_blank(self):
        r = fw.build_medication_statement(patient_ref=PATIENT, rxnorm="x", display="d")
        assert "dosage" not in r

    def test_dosage_included_when_provided(self):
        r = fw.build_medication_statement(patient_ref=PATIENT, rxnorm="x", display="d",
                                          dosage_text="1 tab daily")
        assert r["dosage"][0]["text"] == "1 tab daily"


# ---- Provenance ------------------------------------------------------------
class TestProvenance:
    def test_device_agent_present(self):
        prov = fw.build_provenance(target_refs=["Condition/1"])
        assert prov["resourceType"] == "Provenance"
        assemblers = [a for a in prov["agent"]
                      if a["type"]["coding"][0]["code"] == "assembler"]
        assert len(assemblers) == 1

    def test_no_verifier_without_clinician(self):
        prov = fw.build_provenance(target_refs=["Condition/1"])
        verifiers = [a for a in prov["agent"]
                     if a["type"]["coding"][0]["code"] == "verifier"]
        assert verifiers == []

    def test_verifier_added_with_clinician(self):
        prov = fw.build_provenance(target_refs=["Condition/1"],
                                   signing_clinician_ref="Practitioner/9",
                                   signing_clinician_display="Dr. Who")
        verifiers = [a for a in prov["agent"]
                     if a["type"]["coding"][0]["code"] == "verifier"]
        assert len(verifiers) == 1
        assert verifiers[0]["who"]["reference"] == "Practitioner/9"

    def test_dsi_source_extension(self):
        prov = fw.build_provenance(target_refs=["Condition/1"])
        ext = prov["extension"][0]
        assert ext["url"] == fw._DSI_SOURCE_EXT_URL
        sub = {e["url"]: e for e in ext["extension"]}
        assert sub["sourceType"]["valueCode"] == "predictive-dsi"

    def test_targets_mapped(self):
        prov = fw.build_provenance(target_refs=["Condition/1", "Observation/2"])
        refs = [t["reference"] for t in prov["target"]]
        assert refs == ["Condition/1", "Observation/2"]


# ---- Local mock-store dispatcher -------------------------------------------
class TestLocalStore:
    def test_write_falls_back_to_local(self):
        cond = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2")
        result = fw.write(cond)
        assert result["stored"] == "mock"
        assert result["resourceType"] == "Condition"
        assert result["id"]

    def test_list_local_filtered(self):
        fw.write(fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2"))
        fw.write(fw.build_allergy(patient_ref=PATIENT, substance_display="Latex"))
        conds = fw.list_local("Condition")
        assert len(conds) == 1
        assert len(fw.list_local("AllergyIntolerance")) == 1

    def test_list_local_all(self):
        fw.write(fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2"))
        fw.write(fw.build_allergy(patient_ref=PATIENT, substance_display="Latex"))
        assert len(fw.list_local()) == 2

    def test_clear_local(self):
        fw.write(fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2"))
        fw.clear_local()
        assert fw.list_local() == []

    def test_write_with_provenance_local(self):
        cond = fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2")
        out = fw.write_with_provenance(cond)
        assert out["resource"]["stored"] == "mock"
        assert out["provenance"]["stored"] == "mock"
        assert len(fw.list_local("Provenance")) == 1

    def test_write_bundle_with_provenance_single_attestation(self):
        resources = [
            fw.build_condition(patient_ref=PATIENT, icd10="E11.9", display="DM2"),
            fw.build_allergy(patient_ref=PATIENT, substance_display="Latex"),
        ]
        out = fw.write_bundle_with_provenance(resources)
        assert len(out["resources"]) == 2
        prov_list = fw.list_local("Provenance")
        assert len(prov_list) == 1
        assert len(prov_list[0]["target"]) == 2
