"""Oracle Health (Cerner Millennium) FHIR R4 write-back adapter.

Solace's vendor-abstract write client lives in `services/fhir_writer.py`. That
module owns the canonical FHIR *resource builders* (`build_document_reference`,
`build_condition`, `build_allergy`, `build_observation_*`) and a local mock
store used for offline demos. This module is a thin **Oracle-specific dispatch
layer** that reuses those builders unchanged and applies the wire-level quirks
that Oracle's FHIR server (Cerner Millennium) imposes.

Design goals
------------
- **Injectable**: `OracleEHRClient(base_url=..., access_token=..., http_client=...)`
  takes an HTTP client so tests can pass a fake. Nothing here reads global
  state at import time.
- **Offline-testable**: when no `base_url` is configured (and no client is
  injected) every write transparently falls back to `fhir_writer`'s local mock
  store, so the demo and unit tests run with zero network.
- **No duplication**: resource JSON is always produced by `fhir_writer.build_*`.
  We only mutate the result to satisfy Oracle's stricter requirements.

Oracle vs Epic divergences (see per-function docstrings for detail)
-------------------------------------------------------------------
1. **Create semantics.** Oracle is a plain FHIR `POST {base}/{ResourceType}`.
   It does NOT use Epic's special operations (Epic exposes `Condition` writes
   through an `$add`-style problem-list flow). Standard create only.
2. **201 with empty body.** Oracle returns `201 Created` with an *empty* response
   body. The new resource id is ONLY in the `Location` /  `Content-Location`
   header (`.../ResourceType/<id>/_history/1`). Epic typically echoes the
   created resource as JSON. We must parse the header, not the body.
3. **Tenant-embedded URLs.** Oracle FHIR base URLs embed the tenant (millennium
   "tenant id") in the path, e.g.
   `https://fhir-ehr.cerner.com/r4/<tenant-guid>`. The adapter never strips or
   rewrites the tenant — callers pass the full tenant-scoped base URL.
4. **Stricter required fields.** Oracle rejects resources that Epic/SMART
   sandboxes accept loosely:
     - `Condition` requires `category` and `clinicalStatus`.
     - `AllergyIntolerance` requires `clinicalStatus`, `verificationStatus`,
       and a `category`; the substance should be coded with **RxNorm** for
       medication allergies (not free `code.text`).
     - `Observation` requires a `category`, a `status`, and an `effective[x]`.
5. **RxNorm allergies.** Oracle's allergy reconciliation keys off RxNorm codes
   for drug allergies. `write_allergy` accepts an optional `rxnorm_code` and
   promotes it into `code.coding` alongside the human-readable text.
6. **Auth + headers.** Oracle wants `Authorization: Bearer <token>` plus a
   `Content-Type: application/fhir+json` body and `Accept: application/fhir+json`.

This module raises `OracleWriteError` for any non-success Oracle response so
callers (e.g. `routers/ehr.py`) can surface an actionable HTTPException.

Wiring note (no router edits made here): see the module-level WIRING block at
the bottom of this file for the exact lines to add to `routers/ehr.py`.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

from services import fhir_writer

log = logging.getLogger(__name__)

_HISTORY_RE = re.compile(r"/([A-Za-z]+)/([^/]+)(?:/_history/.*)?$")

# Oracle reconciliation keys drug allergies off RxNorm; this is the canonical URI.
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
_ALLERGY_CATEGORY_SYSTEM = "http://hl7.org/fhir/allergy-intolerance-category"
_CONDITION_CATEGORY_SYSTEM = (
    "http://terminology.hl7.org/CodeSystem/condition-category"
)


class OracleWriteError(RuntimeError):
    """Raised when an Oracle Health FHIR write fails.

    Attributes
    ----------
    status_code : int | None
        HTTP status returned by Oracle (None for transport-level failures).
    resource_type : str
        FHIR resource type that failed to write.
    detail : str
        Human-readable failure reason (Oracle OperationOutcome text when available).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        resource_type: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.resource_type = resource_type
        self.detail = detail or message


# ----------------------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------------------
class OracleEHRClient:
    """Oracle Health FHIR R4 write client.

    Parameters
    ----------
    base_url : str | None
        Tenant-scoped Oracle FHIR base, e.g.
        ``https://fhir-ehr.cerner.com/r4/<tenant-guid>``. The tenant guid is
        part of the path and must NOT be stripped. When falsy (and no
        ``http_client`` is injected) the client operates in **local mode** and
        every write goes to ``fhir_writer``'s in-process mock store.
    access_token : str | None
        SMART-on-FHIR bearer token with the relevant ``user/<Resource>.write``
        scopes. Required for real Oracle writes; ignored in local mode.
    http_client : object | None
        Optional injected HTTP client exposing a ``post(url, *, headers, json,
        timeout)`` method returning an object with ``.status_code``,
        ``.headers`` (mapping) and ``.json()`` / ``.text``. When omitted a
        lazily-constructed ``httpx.Client`` is used. Inject a fake for offline
        unit tests without touching the network.
    timeout : float
        Per-request timeout in seconds (constitution SEC-010: <= 30s).
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        access_token: str | None = None,
        http_client: Any | None = None,
        timeout: float = 15.0,
    ) -> None:
        # Allow env fallback so the adapter mirrors fhir_patient_search conventions.
        self.base_url = (base_url or os.environ.get("ORACLE_FHIR_BASE_URL") or "").rstrip("/")
        self.access_token = access_token or os.environ.get("ORACLE_FHIR_ACCESS_TOKEN") or ""
        self._injected_client = http_client
        self.timeout = min(float(timeout), 30.0)

    # -- mode -----------------------------------------------------------------
    @property
    def is_local(self) -> bool:
        """True when writes fall back to the local mock store.

        Local mode is active when there is neither a configured ``base_url``
        nor an injected HTTP client. An injected client always means "perform
        a (possibly faked) HTTP call" so tests can exercise the real path.
        """
        return not self.base_url and self._injected_client is None

    # -- internals ------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        """Oracle requires fhir+json content negotiation and a bearer token.

        Divergence from Epic: Oracle is strict about ``Content-Type``; a plain
        ``application/json`` body is rejected with 400. Epic sandboxes accept
        either.
        """
        headers = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _client(self) -> Any:
        if self._injected_client is not None:
            return self._injected_client
        import httpx  # noqa: PLC0415 — lazy so import works without httpx in pure-builder use

        return httpx.Client(timeout=self.timeout)

    @staticmethod
    def _id_from_location(location: str) -> str:
        """Extract the resource id from an Oracle ``Location`` header.

        Oracle returns ``201 Created`` with an *empty body*; the canonical
        resource reference is only in the ``Location`` (or ``Content-Location``)
        header, shaped ``.../<ResourceType>/<id>/_history/1``. This is the key
        divergence from Epic, which echoes the created resource as JSON.
        """
        if not location:
            return ""
        m = _HISTORY_RE.search(location.strip())
        return m.group(2) if m else ""

    def _post(self, resource: dict[str, Any]) -> dict[str, Any]:
        """POST a fully-built FHIR resource to Oracle (plain create).

        Returns ``{ok, id, url, stored, resource_type}``. Raises
        ``OracleWriteError`` on any non-2xx response or transport failure.

        Local mode short-circuits to ``fhir_writer._store_local`` so offline
        tests and demos never touch the network.
        """
        resource_type = resource.get("resourceType", "")

        if self.is_local:
            stored = fhir_writer._store_local(resource_type, resource)
            return {
                "ok": True,
                "id": stored.get("id"),
                "url": stored.get("url"),
                "stored": "mock",
                "resource_type": resource_type,
            }

        # Oracle create == plain POST {base}/{ResourceType}. No $-operations,
        # no Bundle transaction — unlike Epic's problem-list $add path.
        url = f"{self.base_url}/{resource_type}"
        client = self._client()
        try:
            resp = client.post(
                url,
                headers=self._headers(),
                json=resource,
                timeout=self.timeout,
            )
        except Exception as e:  # noqa: BLE001 — transport-level failure
            raise OracleWriteError(
                f"Oracle FHIR transport error writing {resource_type}: {e}",
                resource_type=resource_type,
            ) from e

        status = getattr(resp, "status_code", 0)
        if status not in (200, 201):
            detail = _extract_outcome_detail(resp)
            raise OracleWriteError(
                f"Oracle rejected {resource_type} write (HTTP {status})",
                status_code=status,
                resource_type=resource_type,
                detail=detail,
            )

        # Divergence: parse the id from the Location header, not the body.
        headers = getattr(resp, "headers", {}) or {}
        location = headers.get("Location") or headers.get("Content-Location") or ""
        rid = self._id_from_location(location)
        if not rid:
            # 200 responses (rare for Oracle creates) may carry a JSON body.
            body = _safe_json(resp)
            rid = body.get("id", "") if isinstance(body, dict) else ""

        return {
            "ok": True,
            "id": rid,
            "url": location or f"{url}/{rid}" if rid else url,
            "stored": "oracle",
            "resource_type": resource_type,
        }

    # -- public write API -----------------------------------------------------
    def write_document_reference(
        self,
        *,
        patient_ref: str,
        note_text: str,
        note_pdf_bytes: bytes | None = None,
        type_code: str = "11506-3",
        type_display: str = "Progress note",
        author_display: str = "Solace AI scribe",
    ) -> dict[str, Any]:
        """Write a clinical note as a FHIR ``DocumentReference``.

        Reuses ``fhir_writer.build_document_reference`` verbatim, then applies
        Oracle requirements:
          - Oracle requires an explicit ``DocumentReference.category``; Epic
            infers it. We add the IHE/LOINC clinical-note category.
          - ``content[].attachment`` already carries base64 data + contentType
            from the builder, which Oracle accepts.

        Divergence from Epic: Epic frequently wants the note tied to an
        ``Encounter`` via ``context.encounter``; Oracle accepts a patient-only
        DocumentReference, so we keep the builder's subject-only shape.
        """
        resource = fhir_writer.build_document_reference(
            patient_ref=patient_ref,
            note_text=note_text,
            note_pdf_bytes=note_pdf_bytes,
            type_code=type_code,
            type_display=type_display,
            author_display=author_display,
        )
        resource.setdefault(
            "category",
            [
                {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "11488-4",
                            "display": "Consult note",
                        }
                    ]
                }
            ],
        )
        return self._post(resource)

    def write_condition(
        self,
        *,
        patient_ref: str,
        icd10: str,
        display: str,
        clinical_status: str = "active",
        category_code: str = "problem-list-item",
    ) -> dict[str, Any]:
        """Write a problem/diagnosis as a FHIR ``Condition``.

        Reuses ``fhir_writer.build_condition``, then satisfies Oracle's
        stricter validation:
          - Oracle **requires** ``Condition.category``; the builder omits it.
            We add ``problem-list-item`` (or caller-supplied) so the condition
            lands on the patient's problem list.
          - ``clinicalStatus`` is already set by the builder (Oracle requires
            it too).

        Divergence from Epic: Epic exposes problem-list writes through a
        dedicated ``Condition`` create that behaves like an ``$add`` against
        the problem list and rejects ``encounter-diagnosis`` category writes
        from external apps. Oracle uses a **plain create** and honors the
        ``category`` you send — so the category is a real, caller-controlled
        field here, not a fixed Epic behavior.
        """
        resource = fhir_writer.build_condition(
            patient_ref=patient_ref,
            icd10=icd10,
            display=display,
            clinical_status=clinical_status,
        )
        resource.setdefault(
            "category",
            [
                {
                    "coding": [
                        {
                            "system": _CONDITION_CATEGORY_SYSTEM,
                            "code": category_code,
                        }
                    ]
                }
            ],
        )
        return self._post(resource)

    def write_allergy(
        self,
        *,
        patient_ref: str,
        substance_display: str,
        reaction: str = "",
        severity: str = "moderate",
        rxnorm_code: str = "",
        category: str = "medication",
    ) -> dict[str, Any]:
        """Write an allergy as a FHIR ``AllergyIntolerance``.

        Reuses ``fhir_writer.build_allergy``, then applies Oracle requirements:
          - Oracle **requires** ``AllergyIntolerance.category`` (e.g.
            ``medication``, ``food``, ``environment``); the builder omits it.
          - For **drug allergies Oracle keys reconciliation off RxNorm codes**.
            When ``rxnorm_code`` is supplied we promote it into
            ``code.coding`` (RxNorm system) while keeping the builder's
            human-readable ``code.text``. Without an RxNorm code Oracle will
            still accept a text-only substance but won't reconcile it against
            the medication list.
          - ``clinicalStatus`` / ``verificationStatus`` are set by the builder
            (Oracle requires both).

        Divergence from Epic: Epic's sandbox tolerates a text-only ``code`` for
        any allergy. Oracle is stricter — text-only drug allergies are accepted
        but flagged "unreconciled"; RxNorm coding is the expected path.
        """
        resource = fhir_writer.build_allergy(
            patient_ref=patient_ref,
            substance_display=substance_display,
            reaction=reaction,
            severity=severity,
        )
        resource.setdefault("category", [category])
        if rxnorm_code:
            code = resource.setdefault("code", {})
            coding = code.setdefault("coding", [])
            coding.append(
                {
                    "system": RXNORM_SYSTEM,
                    "code": rxnorm_code,
                    "display": substance_display,
                }
            )
            code.setdefault("text", substance_display)
        return self._post(resource)

    def write_observation(
        self,
        *,
        patient_ref: str,
        code_loinc: str,
        display: str,
        value: float | None = None,
        unit: str = "",
        value_text: str = "",
    ) -> dict[str, Any]:
        """Write an ``Observation`` (vital sign or social-history value).

        Delegates to the matching ``fhir_writer`` builder:
          - numeric ``value`` + ``unit``  -> ``build_observation_vital``
          - ``value_text``                -> ``build_observation_social``

        Both builders already emit ``status``, ``category`` and
        ``effectiveDateTime``, which are the three fields Oracle requires.

        Divergence from Epic: Epic restricts external Observation writes to a
        small allowlist of LOINC codes (mostly vitals) and rejects others with
        a 400. Oracle accepts a broader LOINC set, but is strict that an
        ``effective[x]`` and a ``category`` are always present — the builders
        guarantee that, so no extra patching is needed here.
        """
        if value is not None:
            resource = fhir_writer.build_observation_vital(
                patient_ref=patient_ref,
                code_loinc=code_loinc,
                display=display,
                value=value,
                unit=unit,
            )
        elif value_text:
            resource = fhir_writer.build_observation_social(
                patient_ref=patient_ref,
                code_loinc=code_loinc,
                display=display,
                value_text=value_text,
            )
        else:
            raise OracleWriteError(
                "write_observation requires either numeric value+unit or value_text",
                resource_type="Observation",
            )
        return self._post(resource)

    def write_service_request(
        self,
        *,
        patient_ref: str,
        code: str,
        display: str,
        system: str = "http://loinc.org",
        intent: str = "order",
        priority: str = "routine",
        reason_text: str = "",
        encounter_ref: str | None = None,
    ) -> dict[str, Any]:
        """Write a ``ServiceRequest`` (order) to Oracle Health.

        Reuses ``fhir_writer.build_service_request``; Oracle uses a plain
        ``POST {base}/ServiceRequest`` create (no $-operation). Oracle requires
        ``status``, ``intent`` and ``code`` — all supplied by the builder — and
        accepts a patient-scoped order without an encounter, so ``encounter_ref``
        stays optional.

        Divergence from Epic: Oracle does not require the order to be tied to an
        Encounter, and honors the ``intent`` you send (``proposal`` vs
        ``order``) rather than forcing ``order`` for external apps.
        """
        resource = fhir_writer.build_service_request(
            patient_ref=patient_ref,
            code=code,
            display=display,
            system=system,
            intent=intent,
            priority=priority,
            reason_text=reason_text,
            encounter_ref=encounter_ref,
        )
        return self._post(resource)


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------
def _safe_json(resp: Any) -> Any:
    """Best-effort ``resp.json()`` that never raises."""
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {}


def _extract_outcome_detail(resp: Any) -> str:
    """Pull a human-readable message out of an Oracle ``OperationOutcome``.

    On failure Oracle returns an ``OperationOutcome`` resource describing the
    validation error. Falls back to raw response text.
    """
    body = _safe_json(resp)
    if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
        issues = body.get("issue") or []
        parts: list[str] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            text = (
                (issue.get("details") or {}).get("text")
                or issue.get("diagnostics")
                or issue.get("code")
                or ""
            )
            if text:
                parts.append(str(text))
        if parts:
            return "; ".join(parts)
    return (getattr(resp, "text", "") or "")[:500]


# ----------------------------------------------------------------------------------
# WIRING — routers/ehr.py (NOT applied here; this file does not edit routers)
# ----------------------------------------------------------------------------------
# To expose Oracle write-back from the clinician EHR router, add to
# backend/routers/ehr.py:
#
#   from services.ehr_oracle import OracleEHRClient, OracleWriteError
#
#   def _oracle_client(caller: dict) -> OracleEHRClient:
#       # caller carries the SMART session's FHIR base + token (see ehr_auth.py
#       # JWT claims: ehr_fhir_base / fhir_access_token). Falls back to local
#       # mock store when those are absent.
#       return OracleEHRClient(
#           base_url=caller.get("ehr_fhir_base"),
#           access_token=caller.get("fhir_access_token"),
#       )
#
#   @router.post("/ehr/{patient_id}/write-condition")
#   def write_condition(
#       hospital_id: str = Path(...),
#       patient_id: str = Path(...),
#       body: dict = Body(...),                       # inline Pydantic per ARCH-005
#       caller: dict = Depends(require_clinician),
#   ) -> dict[str, Any]:
#       audit(caller, "ehr.write_condition", patient_id=patient_id)  # COMP-002
#       try:
#           return _oracle_client(caller).write_condition(
#               patient_ref=f"Patient/{patient_id}",
#               icd10=body["icd10"], display=body["display"],
#           )
#       except OracleWriteError as e:
#           raise HTTPException(status_code=502, detail=e.detail)    # QUAL-003
#
# Mirror the same pattern for write_document_reference / write_allergy /
# write_observation. The router stays the single place that calls audit() and
# raises HTTPException; ehr_oracle never imports fastapi or boto3 (ARCH-002).
