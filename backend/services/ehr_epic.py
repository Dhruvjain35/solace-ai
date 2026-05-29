"""Epic FHIR R4 write-back adapter.

Epic-specific layer on top of the vendor-abstract `fhir_writer`. This module
owns the quirks that differ from a plain FHIR R4 server:

  - Epic responds to a successful create with HTTP 201 and an empty body; the
    new resource id is carried in the `Location` response header
    (`.../Resource/{id}/_history/{vid}`), not in a JSON payload.
  - Epic returns errors as a FHIR `OperationOutcome` resource — this adapter
    parses the `issue[].diagnostics` text into a single `EpicWriteError`.
  - Epic prefers LOINC document type codes for `DocumentReference` and expects
    problem-list `Condition` resources to carry `category = problem-list-item`
    plus dual coding (SNOMED CT *and* ICD-10-CM).
  - `Observation` vitals must carry a LOINC code and a UCUM-coded unit.

It does NOT re-implement resource construction: every resource is built with
`fhir_writer.build_*` so the FHIR shape stays in one place. The adapter only
adds Epic-required fields and handles transport.

Offline-testable: construct `EpicAdapter()` with no arguments and it falls back
to `fhir_writer`'s in-process mock store — no network, no Epic account. Pass a
`base_url` + `access_token` (and optionally an `http_client`) to hit a real
Epic sandbox. The `http_client` is fully injectable so unit tests can supply a
fake without monkeypatching.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any, Protocol

from services import fhir_writer

log = logging.getLogger(__name__)

# Epic's interconnect FHIR R4 base honors the standard create verb.
DEFAULT_TIMEOUT_S = 15.0

# Epic note-type codes (LOINC) accepted by DocumentReference write-back.
EPIC_NOTE_TYPES: dict[str, tuple[str, str]] = {
    "progress": ("11506-3", "Progress note"),
    "consult": ("11488-4", "Consult note"),
    "discharge": ("18842-5", "Discharge summary"),
    "ed": ("28568-4", "Emergency department note"),
    "history_physical": ("34117-2", "History and physical note"),
    "nursing": ("34746-8", "Nursing note"),
}

# FHIR terminology systems Epic expects.
_SYS_SNOMED = "http://snomed.info/sct"
_SYS_ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
_SYS_LOINC = "http://loinc.org"
_SYS_UCUM = "http://unitsofmeasure.org"
_SYS_OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
_SYS_DOC_CATEGORY = "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category"


class EpicWriteError(Exception):
    """Raised when an Epic FHIR write fails.

    Carries the HTTP status, the parsed OperationOutcome issues (if any), and
    the resource type that was being written so callers can surface an
    actionable message and audit the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        resource_type: str | None = None,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.resource_type = resource_type
        self.issues = issues or []

    def __str__(self) -> str:
        bits = [self.message]
        if self.status_code is not None:
            bits.append(f"status={self.status_code}")
        if self.resource_type:
            bits.append(f"resource={self.resource_type}")
        return " | ".join(bits)


class _HttpClient(Protocol):
    """Minimal structural type for an injectable HTTP client.

    Any object exposing a `post(url, *, headers, json, timeout)` returning an
    object with `status_code`, `headers`, `text`, and `json()` satisfies this —
    `httpx.Client` and `requests.Session` both do.
    """

    def post(self, url: str, **kwargs: Any) -> Any: ...  # noqa: D102


def _now_iso() -> str:
    return fhir_writer._now_iso()


def parse_operation_outcome(body: Any) -> list[dict[str, Any]]:
    """Flatten an Epic `OperationOutcome` resource into a list of issue dicts.

    Returns `[]` when the body is not an OperationOutcome. Each issue dict has
    `severity`, `code`, and `diagnostics` keys for human-readable reporting.
    """
    if not isinstance(body, dict) or body.get("resourceType") != "OperationOutcome":
        return []
    out: list[dict[str, Any]] = []
    for issue in body.get("issue", []) or []:
        if not isinstance(issue, dict):
            continue
        details = issue.get("details") or {}
        diagnostics = (
            issue.get("diagnostics")
            or (details.get("text") if isinstance(details, dict) else None)
            or ""
        )
        out.append(
            {
                "severity": issue.get("severity", "error"),
                "code": issue.get("code", "processing"),
                "diagnostics": diagnostics,
            }
        )
    return out


class EpicAdapter:
    """Epic FHIR R4 write-back client.

    Construct with no arguments for offline mode (writes land in
    `fhir_writer`'s mock store). Construct with `base_url` + `access_token` to
    target a real Epic sandbox. `http_client` is optional and injectable for
    tests.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_token: str | None = None,
        http_client: _HttpClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        # base_url / token resolve from env when not passed, mirroring
        # fhir_patient_search's EHR_FHIR_* convention.
        self.base_url = (base_url or os.environ.get("EPIC_FHIR_BASE_URL", "")).rstrip("/")
        self.access_token = access_token or os.environ.get("EPIC_FHIR_ACCESS_TOKEN", "").strip()
        self.http_client = http_client
        self.timeout_s = timeout_s

    # -- mode ---------------------------------------------------------------
    @property
    def online(self) -> bool:
        """True when a real Epic base URL is configured; False = mock store."""
        return bool(self.base_url)

    # -- transport ----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _client(self) -> _HttpClient:
        if self.http_client is not None:
            return self.http_client
        import httpx  # noqa: PLC0415

        return httpx.Client(timeout=self.timeout_s)

    def _post(self, resource: dict[str, Any]) -> dict[str, Any]:
        """POST a resource to Epic. Offline mode falls back to the mock store.

        Returns `{ok, id, url, stored}`. Raises `EpicWriteError` on a remote
        failure (non-2xx response or transport error).
        """
        rt = resource.get("resourceType") or "Resource"
        if not self.online:
            return fhir_writer._store_local(rt, resource)

        url = f"{self.base_url}/{rt}"
        try:
            resp = self._client().post(
                url, headers=self._headers(), json=resource, timeout=self.timeout_s
            )
        except EpicWriteError:
            raise
        except Exception as e:  # noqa: BLE001 — transport-layer failure
            raise EpicWriteError(
                f"Epic transport error writing {rt}: {e}", resource_type=rt
            ) from e
        return self._handle_response(resp, rt, url)

    @staticmethod
    def _handle_response(resp: Any, resource_type: str, url: str) -> dict[str, Any]:
        """Interpret an Epic FHIR create response.

        Epic convention: 200/201 on success with the new id in the `Location`
        header (body is often empty). Any 4xx/5xx returns an OperationOutcome.
        """
        status = getattr(resp, "status_code", 0)

        # Best-effort JSON parse — Epic returns an empty body on 201.
        body: Any = None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001 — empty / non-JSON body is expected on 201
            body = None

        if status not in (200, 201):
            issues = parse_operation_outcome(body)
            detail = "; ".join(i["diagnostics"] for i in issues if i["diagnostics"])
            raise EpicWriteError(
                detail or f"Epic returned HTTP {status} for {resource_type}",
                status_code=status,
                resource_type=resource_type,
                issues=issues,
            )

        # Success — extract id from the Location header per Epic's convention.
        location = ""
        try:
            location = resp.headers.get("Location") or resp.headers.get("location") or ""
        except Exception:  # noqa: BLE001
            location = ""

        resource_id = ""
        if location:
            # Location looks like .../DocumentReference/{id}/_history/{vid}
            parts = [p for p in location.split("/") if p]
            if "_history" in parts:
                hidx = parts.index("_history")
                if hidx >= 1:
                    resource_id = parts[hidx - 1]
            elif parts:
                resource_id = parts[-1]
        if not resource_id and isinstance(body, dict):
            resource_id = body.get("id", "")

        return {
            "ok": True,
            "id": resource_id,
            "url": location or url,
            "stored": "epic",
            "status": status,
        }

    # -- write operations ---------------------------------------------------
    def write_document_reference(
        self,
        *,
        patient_ref: str,
        note_text: str,
        note_pdf_bytes: bytes | None = None,
        pdf_base64: str | None = None,
        note_type: str = "progress",
        author_display: str = "Solace AI scribe",
        encounter_ref: str | None = None,
    ) -> dict[str, Any]:
        """Write a clinical note to Epic as a `DocumentReference`.

        `note_type` is a key into `EPIC_NOTE_TYPES`; the PDF may be supplied as
        raw `note_pdf_bytes` or a pre-encoded `pdf_base64` string. The plain
        text is always attached alongside.
        """
        if note_type not in EPIC_NOTE_TYPES:
            raise EpicWriteError(
                f"unknown Epic note type {note_type!r}; "
                f"expected one of {sorted(EPIC_NOTE_TYPES)}",
                resource_type="DocumentReference",
            )
        type_code, type_display = EPIC_NOTE_TYPES[note_type]

        pdf_bytes = note_pdf_bytes
        if pdf_bytes is None and pdf_base64:
            try:
                pdf_bytes = base64.b64decode(pdf_base64)
            except Exception as e:  # noqa: BLE001
                raise EpicWriteError(
                    f"invalid base64 PDF payload: {e}",
                    resource_type="DocumentReference",
                ) from e

        resource = fhir_writer.build_document_reference(
            patient_ref=patient_ref,
            note_text=note_text,
            note_pdf_bytes=pdf_bytes,
            type_code=type_code,
            type_display=type_display,
            author_display=author_display,
        )
        # Epic-required: a US Core category and a docStatus.
        resource["docStatus"] = "final"
        resource["category"] = [
            {
                "coding": [
                    {
                        "system": _SYS_DOC_CATEGORY,
                        "code": "clinical-note",
                        "display": "Clinical Note",
                    }
                ]
            }
        ]
        if encounter_ref:
            resource["context"] = {"encounter": [{"reference": encounter_ref}]}
        return self._post(resource)

    def write_condition_to_problem_list(
        self,
        *,
        patient_ref: str,
        icd10: str,
        display: str,
        snomed: str | None = None,
        clinical_status: str = "active",
        encounter_ref: str | None = None,
    ) -> dict[str, Any]:
        """Add a `Condition` to Epic's problem list.

        Epic problem-list adds require `category = problem-list-item`. SNOMED CT
        is the primary coding Epic indexes on; ICD-10-CM is added as a second
        coding for billing crosswalk. Pass `snomed` whenever it is known.
        """
        resource = fhir_writer.build_condition(
            patient_ref=patient_ref,
            icd10=icd10,
            display=display,
            clinical_status=clinical_status,
        )
        # Epic problem-list marker.
        resource["category"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "problem-list-item",
                        "display": "Problem List Item",
                    }
                ]
            }
        ]
        # Prepend SNOMED so it is the primary coding Epic indexes.
        if snomed:
            codings = resource.setdefault("code", {}).setdefault("coding", [])
            codings.insert(
                0,
                {"system": _SYS_SNOMED, "code": snomed, "display": display},
            )
        if encounter_ref:
            resource["encounter"] = {"reference": encounter_ref}
        return self._post(resource)

    def write_allergy_intolerance(
        self,
        *,
        patient_ref: str,
        substance_display: str,
        reaction: str = "",
        severity: str = "moderate",
        substance_snomed: str | None = None,
        criticality: str = "low",
    ) -> dict[str, Any]:
        """Write an `AllergyIntolerance` to Epic.

        `substance_snomed` adds a coded substance alongside the free-text name;
        `criticality` is the Epic-surfaced low/high/unable-to-assess flag.
        """
        resource = fhir_writer.build_allergy(
            patient_ref=patient_ref,
            substance_display=substance_display,
            reaction=reaction,
            severity=severity,
        )
        resource["type"] = "allergy"
        resource["criticality"] = criticality
        if substance_snomed:
            resource["code"] = {
                "coding": [
                    {
                        "system": _SYS_SNOMED,
                        "code": substance_snomed,
                        "display": substance_display,
                    }
                ],
                "text": substance_display,
            }
        return self._post(resource)

    def write_observation_vital(
        self,
        *,
        patient_ref: str,
        code_loinc: str,
        display: str,
        value: float,
        unit: str,
        ucum_code: str | None = None,
        encounter_ref: str | None = None,
    ) -> dict[str, Any]:
        """Write a vital-sign `Observation` to Epic.

        The value is coded with LOINC; the unit carries a UCUM `code`
        (defaulting to the display `unit` string when `ucum_code` is omitted).
        """
        resource = fhir_writer.build_observation_vital(
            patient_ref=patient_ref,
            code_loinc=code_loinc,
            display=display,
            value=value,
            unit=unit,
        )
        # Ensure the UCUM code is explicit — Epic validates the `code` field.
        vq = resource.get("valueQuantity") or {}
        vq["system"] = _SYS_UCUM
        vq["code"] = ucum_code or unit
        resource["valueQuantity"] = vq
        if encounter_ref:
            resource["encounter"] = {"reference": encounter_ref}
        return self._post(resource)


def make_adapter(
    *,
    base_url: str | None = None,
    access_token: str | None = None,
    http_client: _HttpClient | None = None,
) -> EpicAdapter:
    """Convenience factory mirroring fhir_patient_search's env-driven defaults.

    With no arguments the adapter runs offline against fhir_writer's mock
    store, so callers (and routers/ehr.py) can construct it unconditionally.
    """
    return EpicAdapter(
        base_url=base_url, access_token=access_token, http_client=http_client
    )
