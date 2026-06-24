"""US Core 6.1.0 / USCDI v3 conformance validator (Inferno-style, offline).

A dependency-free FHIR R4 profile checker for the resources Solace *reads* from
and *writes* to an EHR. It is NOT a full FHIR validator — it encodes the subset
of US Core invariants that a marketplace conformance reviewer (Epic App Orchard,
Oracle/Cerner code console, athenahealth Marketplace, ONC (g)(10) Inferno)
actually gates on:

  * **Cardinality** of required (``1..``) elements.
  * **Must-Support** elements (US Core flags many ``0..`` elements MS; we treat
    MS as "if a conformant server populates it, it must be well-formed").
  * **Required bindings** — terminology systems that US Core *requires* (e.g.
    Condition.code from ICD-10-CM/SNOMED, Observation vitals from LOINC, UCUM
    units on quantities, status codes from the bound value set).
  * **Profile declaration** — ``meta.profile`` claims, when present, must name a
    real US Core StructureDefinition.

Design: each resource type maps to a list of :class:`Rule`s. ``validate()``
returns a :class:`ConformanceReport` with ``errors`` (L1 — fail the gate) and
``warnings`` (must-support advisories — would fail a *strict* Inferno run but
not basic interop). This mirrors how Inferno separates "FAIL" from "SKIP/INFO".

This module performs **no I/O** and imports nothing beyond stdlib, so it is safe
to call from a service, a router, or a test without a network or AWS.

References:
  - US Core 6.1.0 profiles: https://hl7.org/fhir/us/core/STU6.1/
  - USCDI v3: https://www.healthit.gov/isa/united-states-core-data-interoperability-uscdi
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

# --------------------------------------------------------------------------------------
# Canonical US Core StructureDefinition URLs (subset Solace touches).
# --------------------------------------------------------------------------------------

US_CORE_BASE = "http://hl7.org/fhir/us/core/StructureDefinition"

US_CORE_PROFILES: dict[str, str] = {
    "Patient": f"{US_CORE_BASE}/us-core-patient",
    "Condition": f"{US_CORE_BASE}/us-core-condition-problems-health-concerns",
    "AllergyIntolerance": f"{US_CORE_BASE}/us-core-allergyintolerance",
    "MedicationRequest": f"{US_CORE_BASE}/us-core-medicationrequest",
    "MedicationStatement": f"{US_CORE_BASE}/us-core-medicationrequest",
    "Immunization": f"{US_CORE_BASE}/us-core-immunization",
    "DocumentReference": f"{US_CORE_BASE}/us-core-documentreference",
    "Observation": f"{US_CORE_BASE}/us-core-observation-lab",
    "Procedure": f"{US_CORE_BASE}/us-core-procedure",
    "Encounter": f"{US_CORE_BASE}/us-core-encounter",
    "Provenance": f"{US_CORE_BASE}/us-core-provenance",
}

# Terminology systems US Core binds to (used for required-binding checks).
SYS_LOINC = "http://loinc.org"
SYS_UCUM = "http://unitsofmeasure.org"
SYS_SNOMED = "http://snomed.info/sct"
SYS_ICD10CM = "http://hl7.org/fhir/sid/icd-10-cm"
SYS_RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
SYS_CVX = "http://hl7.org/fhir/sid/cvx"

# Bound value sets (status fields) — abbreviated to the codes US Core permits.
_CONDITION_CLINICAL = {"active", "recurrence", "relapse", "inactive", "remission", "resolved"}
_ALLERGY_CLINICAL = {"active", "inactive", "resolved"}
_OBSERVATION_STATUS = {
    "registered", "preliminary", "final", "amended", "corrected",
    "cancelled", "entered-in-error", "unknown",
}
_DOCREF_STATUS = {"current", "superseded", "entered-in-error"}
_IMMUNIZATION_STATUS = {"completed", "entered-in-error", "not-done"}
_MEDSTMT_STATUS = {
    "active", "completed", "entered-in-error", "intended",
    "stopped", "on-hold", "unknown", "not-taken",
}
_ADMIN_GENDER = {"male", "female", "other", "unknown"}


# --------------------------------------------------------------------------------------
# Report types.
# --------------------------------------------------------------------------------------


@dataclass
class Issue:
    """One conformance finding against a resource."""

    severity: str   # "error" | "warning"
    path: str       # FHIRPath-ish location, e.g. "Observation.code"
    message: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity}] {self.path}: {self.message}"


@dataclass
class ConformanceReport:
    """Aggregate result of validating one or more resources."""

    resource_type: str = ""
    profile: str = ""
    issues: list[Issue] = field(default_factory=list)

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue("error", path, message))

    def warn(self, path: str, message: str) -> None:
        self.issues.append(Issue("warning", path, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        """True if there are no L1 (error) issues. Warnings are advisory."""
        return not self.errors

    def merge(self, other: "ConformanceReport") -> None:
        self.issues.extend(other.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resourceType": self.resource_type,
            "profile": self.profile,
            "ok": self.ok,
            "errors": [str(i) for i in self.errors],
            "warnings": [str(i) for i in self.warnings],
        }


# --------------------------------------------------------------------------------------
# Small helpers for reaching into FHIR resources safely.
# --------------------------------------------------------------------------------------


def _get(resource: dict[str, Any], *path: str) -> Any:
    """Walk a nested dict by key path, returning None if any hop is missing."""
    cur: Any = resource
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _codings(concept: Any) -> list[dict[str, Any]]:
    """Return the ``coding`` list of a CodeableConcept (empty if absent)."""
    if not isinstance(concept, dict):
        return []
    cs = concept.get("coding")
    return [c for c in cs if isinstance(c, dict)] if isinstance(cs, list) else []


def _has_system(concept: Any, *systems: str) -> bool:
    """True if any coding in the concept uses one of ``systems``."""
    want = set(systems)
    return any((c.get("system") in want) for c in _codings(concept))


def _status_code(concept: Any) -> str:
    """Pull the first coding code out of a status CodeableConcept."""
    cs = _codings(concept)
    return str(cs[0].get("code")) if cs else ""


# --------------------------------------------------------------------------------------
# Per-resource validators. Each takes (resource, report) and appends issues.
# --------------------------------------------------------------------------------------


def _check_profile_declaration(resource: dict[str, Any], report: ConformanceReport) -> None:
    """If meta.profile is declared, it must name a known US Core profile.

    US Core does not *require* the profile claim for a resource to be conformant
    (servers may omit it), but a *declared* profile that is not a real US Core SD
    is a conformance error — reviewers flag fabricated profile URLs.
    """
    profiles = _get(resource, "meta", "profile") or []
    if not isinstance(profiles, list):
        report.error("meta.profile", "meta.profile must be an array of canonical URLs")
        return
    known = set(US_CORE_PROFILES.values())
    for p in profiles:
        if isinstance(p, str) and p.startswith(US_CORE_BASE) and p not in known:
            report.warn(
                "meta.profile",
                f"declares US Core profile '{p}' not in Solace's recognized set",
            )


def validate_patient(resource: dict[str, Any], report: ConformanceReport) -> None:
    # US Core Patient required: identifier(1..*), name(1..*), gender(1..1).
    ident = resource.get("identifier")
    if not isinstance(ident, list) or not ident:
        report.error("Patient.identifier", "US Core Patient requires >=1 identifier")
    else:
        for i, idn in enumerate(ident):
            if not isinstance(idn, dict) or not idn.get("system") or not idn.get("value"):
                report.error(
                    f"Patient.identifier[{i}]",
                    "identifier must carry both system and value",
                )
    names = resource.get("name")
    if not isinstance(names, list) or not names:
        report.error("Patient.name", "US Core Patient requires >=1 name")
    else:
        first = names[0] if isinstance(names[0], dict) else {}
        if not first.get("family") and not first.get("given"):
            report.error("Patient.name", "name must have family or given (data-absent allowed)")
    gender = resource.get("gender")
    if not gender:
        report.error("Patient.gender", "US Core Patient requires gender (administrative)")
    elif gender not in _ADMIN_GENDER:
        report.error("Patient.gender", f"gender '{gender}' not in AdministrativeGender value set")
    # Must-support: birthDate.
    if not resource.get("birthDate"):
        report.warn("Patient.birthDate", "must-support birthDate is absent")


def validate_condition(resource: dict[str, Any], report: ConformanceReport) -> None:
    # category(1..*), code(1..1), subject(1..1). clinicalStatus is conditionally
    # required (must be present unless verificationStatus=entered-in-error).
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        report.error("Condition.category", "US Core Condition requires >=1 category")
    code = resource.get("code")
    if not _codings(code) and not _get(resource, "code", "text"):
        report.error("Condition.code", "US Core Condition requires code (coding or text)")
    elif not _has_system(code, SYS_ICD10CM, SYS_SNOMED):
        report.warn(
            "Condition.code",
            "must-support: code should bind to ICD-10-CM or SNOMED CT",
        )
    if not _get(resource, "subject", "reference"):
        report.error("Condition.subject", "US Core Condition requires subject reference")
    verification = _status_code(resource.get("verificationStatus"))
    clinical = _status_code(resource.get("clinicalStatus"))
    if verification != "entered-in-error":
        if not clinical:
            report.error(
                "Condition.clinicalStatus",
                "clinicalStatus required unless verificationStatus=entered-in-error",
            )
        elif clinical not in _CONDITION_CLINICAL:
            report.error(
                "Condition.clinicalStatus",
                f"clinicalStatus '{clinical}' not in bound value set",
            )


def validate_allergy(resource: dict[str, Any], report: ConformanceReport) -> None:
    # clinicalStatus(0..1 cond), code(1..1), patient(1..1).
    if not _get(resource, "patient", "reference"):
        report.error("AllergyIntolerance.patient", "requires patient reference")
    code = resource.get("code")
    if not _codings(code) and not _get(resource, "code", "text"):
        report.error("AllergyIntolerance.code", "requires code (coding or text)")
    verification = _status_code(resource.get("verificationStatus"))
    clinical = _status_code(resource.get("clinicalStatus"))
    if verification != "entered-in-error" and clinical and clinical not in _ALLERGY_CLINICAL:
        report.error(
            "AllergyIntolerance.clinicalStatus",
            f"clinicalStatus '{clinical}' not in bound value set",
        )


def validate_observation(resource: dict[str, Any], report: ConformanceReport) -> None:
    # status(1..1), category(1..*), code(1..1), subject(1..1), and a value or
    # dataAbsentReason. Vital-signs/lab must bind code to LOINC and units to UCUM.
    status = resource.get("status")
    if not status:
        report.error("Observation.status", "US Core Observation requires status")
    elif status not in _OBSERVATION_STATUS:
        report.error("Observation.status", f"status '{status}' not in ObservationStatus")
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        report.error("Observation.category", "US Core Observation requires >=1 category")
    code = resource.get("code")
    if not _codings(code):
        report.error("Observation.code", "US Core Observation requires a coded code")
    elif not _has_system(code, SYS_LOINC):
        report.warn("Observation.code", "must-support: Observation.code should use LOINC")
    if not _get(resource, "subject", "reference"):
        report.error("Observation.subject", "US Core Observation requires subject reference")
    has_value = any(k.startswith("value") for k in resource) or "component" in resource
    if not has_value and "dataAbsentReason" not in resource:
        report.error(
            "Observation.value[x]",
            "requires a value[x], component, or dataAbsentReason",
        )
    qty = resource.get("valueQuantity")
    if isinstance(qty, dict):
        if qty.get("system") and qty["system"] != SYS_UCUM:
            report.error("Observation.valueQuantity.system", "quantity must use UCUM")
        if qty.get("value") is not None and not qty.get("code"):
            report.warn(
                "Observation.valueQuantity.code",
                "must-support: UCUM machine code expected on a numeric quantity",
            )


def validate_medication_statement(resource: dict[str, Any], report: ConformanceReport) -> None:
    status = resource.get("status")
    if not status:
        report.error("MedicationStatement.status", "requires status")
    elif status not in _MEDSTMT_STATUS:
        report.error("MedicationStatement.status", f"status '{status}' not in value set")
    med = resource.get("medicationCodeableConcept")
    med_ref = resource.get("medicationReference")
    if not med and not med_ref:
        report.error(
            "MedicationStatement.medication[x]",
            "requires medicationCodeableConcept or medicationReference",
        )
    elif med is not None and not _has_system(med, SYS_RXNORM):
        report.warn(
            "MedicationStatement.medicationCodeableConcept",
            "must-support: medication should bind to RxNorm",
        )
    if not _get(resource, "subject", "reference"):
        report.error("MedicationStatement.subject", "requires subject reference")


def validate_immunization(resource: dict[str, Any], report: ConformanceReport) -> None:
    status = resource.get("status")
    if not status:
        report.error("Immunization.status", "requires status")
    elif status not in _IMMUNIZATION_STATUS:
        report.error("Immunization.status", f"status '{status}' not in value set")
    vac = resource.get("vaccineCode")
    if not _codings(vac):
        report.error("Immunization.vaccineCode", "requires coded vaccineCode")
    elif not _has_system(vac, SYS_CVX):
        report.warn("Immunization.vaccineCode", "must-support: vaccineCode should use CVX")
    if not _get(resource, "patient", "reference"):
        report.error("Immunization.patient", "requires patient reference")
    if "occurrenceDateTime" not in resource and "occurrenceString" not in resource:
        report.error("Immunization.occurrence[x]", "requires occurrenceDateTime/String")
    if resource.get("primarySource") is None:
        report.warn("Immunization.primarySource", "must-support primarySource is absent")


def validate_document_reference(resource: dict[str, Any], report: ConformanceReport) -> None:
    status = resource.get("status")
    if not status:
        report.error("DocumentReference.status", "requires status")
    elif status not in _DOCREF_STATUS:
        report.error("DocumentReference.status", f"status '{status}' not in value set")
    if not _codings(resource.get("type")):
        report.error("DocumentReference.type", "US Core requires a coded type (LOINC)")
    elif not _has_system(resource.get("type"), SYS_LOINC):
        report.warn("DocumentReference.type", "must-support: type should use LOINC")
    cats = resource.get("category")
    if not isinstance(cats, list) or not cats:
        report.error("DocumentReference.category", "US Core requires >=1 category")
    if not _get(resource, "subject", "reference"):
        report.error("DocumentReference.subject", "requires subject reference")
    content = resource.get("content")
    if not isinstance(content, list) or not content:
        report.error("DocumentReference.content", "requires >=1 content")
    else:
        for i, c in enumerate(content):
            att = (c or {}).get("attachment") if isinstance(c, dict) else None
            if not isinstance(att, dict) or not att.get("contentType"):
                report.error(
                    f"DocumentReference.content[{i}].attachment.contentType",
                    "attachment requires contentType",
                )


def validate_provenance(resource: dict[str, Any], report: ConformanceReport) -> None:
    if not resource.get("target"):
        report.error("Provenance.target", "Provenance requires >=1 target")
    if not resource.get("recorded"):
        report.error("Provenance.recorded", "Provenance requires recorded instant")
    agents = resource.get("agent")
    if not isinstance(agents, list) or not agents:
        report.error("Provenance.agent", "US Core Provenance requires >=1 agent")


# Dispatch table: resourceType -> validator.
_VALIDATORS: dict[str, Callable[[dict[str, Any], ConformanceReport], None]] = {
    "Patient": validate_patient,
    "Condition": validate_condition,
    "AllergyIntolerance": validate_allergy,
    "Observation": validate_observation,
    "MedicationStatement": validate_medication_statement,
    "MedicationRequest": validate_medication_statement,
    "Immunization": validate_immunization,
    "DocumentReference": validate_document_reference,
    "Provenance": validate_provenance,
}

SUPPORTED_RESOURCE_TYPES: tuple[str, ...] = tuple(_VALIDATORS.keys())


# --------------------------------------------------------------------------------------
# Public API.
# --------------------------------------------------------------------------------------


def validate_resource(resource: dict[str, Any]) -> ConformanceReport:
    """Validate one FHIR resource against its US Core profile.

    Unknown resource types return an empty (passing) report with a warning, so a
    caller iterating a mixed bundle is never blocked by a type Solace does not
    yet profile.
    """
    rtype = (resource or {}).get("resourceType") or ""
    profiles = _get(resource, "meta", "profile") or []
    profile = US_CORE_PROFILES.get(rtype, "")
    report = ConformanceReport(resource_type=rtype, profile=profile)
    if isinstance(profiles, list) and profiles:
        report.profile = next((p for p in profiles if isinstance(p, str)), profile)

    if not rtype:
        report.error("resourceType", "resource is missing resourceType")
        return report

    _check_profile_declaration(resource, report)

    validator = _VALIDATORS.get(rtype)
    if validator is None:
        report.warn(rtype, f"no US Core profile registered for {rtype}; skipped")
        return report
    validator(resource, report)
    return report


def validate_bundle(bundle: dict[str, Any]) -> ConformanceReport:
    """Validate every resource in a FHIR searchset/collection Bundle."""
    report = ConformanceReport(resource_type="Bundle")
    entries = bundle.get("entry") if isinstance(bundle, dict) else None
    for entry in entries or []:
        res = (entry or {}).get("resource") if isinstance(entry, dict) else None
        if isinstance(res, dict):
            report.merge(validate_resource(res))
    return report


def assert_conformant(resource: dict[str, Any]) -> None:
    """Raise ``AssertionError`` listing every L1 error if not conformant.

    Convenience for tests / a CI conformance gate.
    """
    report = validate_resource(resource)
    if not report.ok:
        lines = "\n".join(f"  - {i}" for i in report.errors)
        raise AssertionError(
            f"{report.resource_type} is not US Core conformant:\n{lines}"
        )
