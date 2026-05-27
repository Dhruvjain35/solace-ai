"""athenahealth write-back adapter.

athenahealth exposes two surfaces and Solace needs both:

  1. **FHIR R4** under ``{base}/fhir/r4/`` — used here for clinical *documents*
     (DocumentReference). athena's FHIR write surface is the cleanest path for
     attaching a scribe note / progress note to the chart.
  2. **Proprietary practice-scoped REST** under ``{base}/v1/{practiceid}/`` —
     athena never fully exposed problems / allergies / vitals as FHIR writes,
     so the problem list, allergy list, and vitals all go through athena's
     legacy REST endpoints. Vitals in particular use athena's own
     ``clinicalelementid`` code vocabulary rather than LOINC.

Both surfaces share one OAuth2 token: athena issues access tokens via the
``client_credentials`` grant against ``{base}/oauth2/v1/token`` using HTTP Basic
auth (client_id / client_secret). Tokens are cached until shortly before expiry.

Design notes
------------
* This module deliberately does **not** edit ``fhir_writer.py``. It imports and
  reuses :func:`services.fhir_writer.build_document_reference` so the FHIR
  DocumentReference shape stays defined in exactly one place.
* All network I/O goes through an injectable :class:`HttpClient` protocol.
  Production passes a thin ``httpx``-backed client; tests pass an in-memory
  fake, so the whole adapter is exercisable fully offline.
* :class:`AthenaConfig` builds from environment in production
  (:meth:`AthenaConfig.from_env`) and from explicit kwargs in tests
  (:meth:`AthenaConfig.for_testing`).

Wiring (for ``routers/ehr.py`` — not edited by this change): see the module
footer ``ROUTER_WIRING`` docstring constant.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from services.fhir_writer import build_document_reference

log = logging.getLogger(__name__)

# athena tokens live ~1h; refresh a minute early to avoid edge-of-expiry 401s.
_TOKEN_SKEW_S = 60.0
# SEC-010: external HTTP timeouts must be <= 30s.
_HTTP_TIMEOUT_S = 20.0


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class AthenaWriteError(RuntimeError):
    """A write to athenahealth failed (non-2xx response, transport error)."""

    def __init__(self, message: str, *, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class AthenaAuthError(AthenaWriteError):
    """OAuth2 token acquisition against athenahealth failed."""


# --------------------------------------------------------------------------
# Injectable HTTP client
# --------------------------------------------------------------------------
@dataclass
class HttpResponse:
    """Minimal transport-agnostic response."""

    status_code: int
    text: str = ""
    _json: Any = None

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        import json as _json  # noqa: PLC0415

        return _json.loads(self.text) if self.text else None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@runtime_checkable
class HttpClient(Protocol):
    """Transport seam. Production uses :class:`HttpxClient`; tests inject a fake."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: Any = None,
    ) -> HttpResponse:
        ...

    def put(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> HttpResponse:
        ...


class HttpxClient:
    """Default :class:`HttpClient` backed by ``httpx``.

    Imported lazily so the module imports cleanly even where ``httpx`` is
    absent (and so the import-check in CI does not require it).
    """

    def __init__(self, timeout: float = _HTTP_TIMEOUT_S):
        self._timeout = timeout

    def _do(self, method: str, url: str, **kw: Any) -> HttpResponse:
        import httpx  # noqa: PLC0415

        try:
            with httpx.Client(timeout=self._timeout) as c:
                r = c.request(method, url, **kw)
            return HttpResponse(status_code=r.status_code, text=r.text)
        except httpx.HTTPError as e:  # transport / timeout
            raise AthenaWriteError(f"athena transport error: {e}") from e

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json: Any = None,
    ) -> HttpResponse:
        return self._do("POST", url, headers=headers, data=data, json=json)

    def put(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> HttpResponse:
        return self._do("PUT", url, headers=headers, json=json)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
@dataclass
class AthenaConfig:
    """athenahealth connection settings.

    Use :meth:`from_env` in production and :meth:`for_testing` in unit tests.
    """

    base_url: str
    client_id: str
    client_secret: str
    practice_id: str
    # athena's "preview" sandbox vs production share the same code paths; the
    # only difference is base_url, so nothing else is needed here.

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    @classmethod
    def from_env(cls) -> "AthenaConfig":
        """Build from ``SOLACE_ATHENA_*`` environment variables.

        Raises :class:`AthenaAuthError` if a required variable is missing —
        consistent with SEC-001's "missing keys must crash" posture, surfaced
        to the caller rather than silently degrading.
        """
        base = os.getenv("SOLACE_ATHENA_BASE_URL", "").strip()
        cid = os.getenv("SOLACE_ATHENA_CLIENT_ID", "").strip()
        secret = os.getenv("SOLACE_ATHENA_CLIENT_SECRET", "").strip()
        practice = os.getenv("SOLACE_ATHENA_PRACTICE_ID", "").strip()
        missing = [
            name
            for name, val in (
                ("SOLACE_ATHENA_BASE_URL", base),
                ("SOLACE_ATHENA_CLIENT_ID", cid),
                ("SOLACE_ATHENA_CLIENT_SECRET", secret),
                ("SOLACE_ATHENA_PRACTICE_ID", practice),
            )
            if not val
        ]
        if missing:
            raise AthenaAuthError(
                "athenahealth not configured — missing env: " + ", ".join(missing)
            )
        return cls(base_url=base, client_id=cid, client_secret=secret, practice_id=practice)

    @classmethod
    def for_testing(
        cls,
        *,
        base_url: str = "https://athena.test",
        client_id: str = "test-client",
        client_secret: str = "test-secret",
        practice_id: str = "999999",
    ) -> "AthenaConfig":
        """Explicit constructor for unit tests — no environment dependency."""
        return cls(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            practice_id=practice_id,
        )

    @staticmethod
    def is_configured() -> bool:
        """Cheap check the router can use to decide whether to surface athena."""
        return all(
            os.getenv(k, "").strip()
            for k in (
                "SOLACE_ATHENA_BASE_URL",
                "SOLACE_ATHENA_CLIENT_ID",
                "SOLACE_ATHENA_CLIENT_SECRET",
                "SOLACE_ATHENA_PRACTICE_ID",
            )
        )


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------
@dataclass
class _CachedToken:
    value: str
    expires_at: float  # epoch seconds

    def valid(self) -> bool:
        return bool(self.value) and time.monotonic() < (self.expires_at - _TOKEN_SKEW_S)


class AthenaWriteClient:
    """Write-back client for athenahealth.

    Holds one cached OAuth2 token shared by the FHIR and proprietary-REST
    surfaces. Construct once per request (or reuse) and call the ``write_*``
    methods.

    Example::

        client = AthenaWriteClient(AthenaConfig.from_env())
        result = client.write_document(patient_ref="Patient/a-1", note_text="...")
    """

    def __init__(self, config: AthenaConfig, http: HttpClient | None = None):
        self.config = config
        self._http: HttpClient = http or HttpxClient()
        self._token: _CachedToken | None = None

    # ---- OAuth2 ----------------------------------------------------------
    def _token_endpoint(self) -> str:
        return f"{self.config.base_url}/oauth2/v1/token"

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid bearer token, acquiring/caching via client_credentials.

        athena's token endpoint expects ``grant_type=client_credentials`` as a
        form body and the client_id/client_secret as HTTP Basic credentials.
        """
        if not force_refresh and self._token and self._token.valid():
            return self._token.value

        basic = base64.b64encode(
            f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # athena scopes write surfaces; request the broad athena scope.
        body = {"grant_type": "client_credentials", "scope": "athena/service/Athenanet.MDP.*"}

        try:
            resp = self._http.post(self._token_endpoint(), headers=headers, data=body)
        except AthenaWriteError as e:
            raise AthenaAuthError(f"token request failed: {e}") from e

        if not resp.ok:
            raise AthenaAuthError(
                f"athena token endpoint returned {resp.status_code}",
                status=resp.status_code,
                body=resp.text,
            )
        payload = resp.json() or {}
        token = payload.get("access_token")
        if not token:
            raise AthenaAuthError("athena token response had no access_token", body=resp.text)
        expires_in = float(payload.get("expires_in", 3600))
        self._token = _CachedToken(value=token, expires_at=time.monotonic() + expires_in)
        log.info("athena access token acquired (expires_in=%ss)", int(expires_in))
        return token

    def _auth_headers(self, *, content_type: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": content_type,
        }

    # ---- FHIR R4 surface -------------------------------------------------
    def _fhir_url(self, resource_type: str) -> str:
        return f"{self.config.base_url}/fhir/r4/{resource_type}"

    def write_document(
        self,
        *,
        patient_ref: str,
        note_text: str,
        note_pdf_bytes: bytes | None = None,
        type_code: str = "11506-3",
        type_display: str = "Progress note",
        author_display: str = "Solace AI scribe",
    ) -> dict[str, Any]:
        """Attach a clinical note to the chart as a FHIR R4 DocumentReference.

        Reuses :func:`fhir_writer.build_document_reference` for the resource
        shape; only the dispatch is athena-specific.
        """
        resource = build_document_reference(
            patient_ref=patient_ref,
            note_text=note_text,
            note_pdf_bytes=note_pdf_bytes,
            type_code=type_code,
            type_display=type_display,
            author_display=author_display,
        )
        url = self._fhir_url("DocumentReference")
        resp = self._post(url, headers=self._auth_headers(content_type="application/fhir+json"), json=resource)
        body = resp.json() or {}
        return {
            "ok": True,
            "surface": "fhir",
            "resourceType": "DocumentReference",
            "id": body.get("id"),
            "location": _location_of(resp, url),
            "stored": "athena",
        }

    # ---- Proprietary practice-scoped REST surface ------------------------
    def _v1_url(self, path: str) -> str:
        return f"{self.config.base_url}/v1/{self.config.practice_id}/{path.lstrip('/')}"

    def write_problem(
        self,
        *,
        athena_patient_id: str,
        icd10: str,
        display: str,
        status: str = "active",
    ) -> dict[str, Any]:
        """Add a problem to a patient's problem list via athena REST.

        athena exposes the problem list at
        ``/v1/{practiceid}/chart/{patientid}/problems`` and accepts a form-style
        POST keyed on the ICD-10 code.
        """
        url = self._v1_url(f"chart/{athena_patient_id}/problems")
        payload = {
            "icd10code": icd10,
            "snomedcode": "",
            "status": status,
            "note": display,
        }
        resp = self._post(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=payload,
        )
        body = resp.json() or {}
        return {
            "ok": True,
            "surface": "athena-rest",
            "resource": "problem",
            "patient": athena_patient_id,
            "icd10": icd10,
            "problemid": body.get("problemid") or body.get("id"),
            "stored": "athena",
        }

    def write_allergies(
        self,
        *,
        athena_patient_id: str,
        allergies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace the patient's full allergy list (athena PUT semantics).

        athena's allergy endpoint
        ``/v1/{practiceid}/chart/{patientid}/allergies`` is a *replace-list* PUT:
        the body's array is the new complete list, so callers must pass every
        allergy that should remain, not just additions.

        ``allergies`` items use athena's shape, e.g.::

            {"allergenid": 12345, "reactions": [{"reactionname": "hives",
             "severity": "moderate"}]}

        Plain ``{"name": "penicillin"}`` items are accepted and forwarded as-is
        for callers that only have free text.
        """
        url = self._v1_url(f"chart/{athena_patient_id}/allergies")
        payload = {"allergies": allergies}
        resp = self._put(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=payload,
        )
        return {
            "ok": True,
            "surface": "athena-rest",
            "resource": "allergies",
            "patient": athena_patient_id,
            "count": len(allergies),
            "replaced": True,
            "stored": "athena",
        }

    def write_vitals(
        self,
        *,
        athena_patient_id: str,
        encounter_id: str,
        vitals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Record vital signs via athena's clinicalelementid vocabulary.

        athena does not take LOINC for vitals — it uses its own
        ``clinicalelementid`` codes posted to
        ``/v1/{practiceid}/chart/encounter/{encounterid}/vitals``.

        Each ``vitals`` item must be ``{"clinicalelementid": "VITALS.BLOODPRESSURE.SYSTOLIC",
        "value": "120"}``. Common athena clinicalelementids:

          * ``VITALS.HEIGHT``
          * ``VITALS.WEIGHT``
          * ``VITALS.BLOODPRESSURE.SYSTOLIC`` / ``.DIASTOLIC``
          * ``VITALS.PULSE``
          * ``VITALS.TEMPERATURE``
          * ``VITALS.RESPIRATIONRATE``
          * ``VITALS.O2SATURATION``

        See :data:`VITAL_LOINC_TO_ATHENA` for a LOINC → clinicalelementid map.
        """
        url = self._v1_url(f"chart/encounter/{encounter_id}/vitals")
        # athena wants vitals as a JSON-array string under the `vitals` key.
        import json as _json  # noqa: PLC0415

        payload = {"vitals": _json.dumps([[v] for v in vitals])}
        resp = self._post(
            url,
            headers=self._auth_headers(content_type="application/json"),
            json=payload,
        )
        return {
            "ok": True,
            "surface": "athena-rest",
            "resource": "vitals",
            "patient": athena_patient_id,
            "encounter": encounter_id,
            "count": len(vitals),
            "stored": "athena",
        }

    # ---- low-level dispatch ---------------------------------------------
    def _post(self, url: str, *, headers: dict[str, str], json: Any) -> HttpResponse:
        resp = self._http.post(url, headers=headers, json=json)
        _raise_for_status(resp, "POST", url)
        return resp

    def _put(self, url: str, *, headers: dict[str, str], json: Any) -> HttpResponse:
        resp = self._http.put(url, headers=headers, json=json)
        _raise_for_status(resp, "PUT", url)
        return resp


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _raise_for_status(resp: HttpResponse, method: str, url: str) -> None:
    if not resp.ok:
        raise AthenaWriteError(
            f"athena {method} {url} returned {resp.status_code}",
            status=resp.status_code,
            body=resp.text,
        )


def _location_of(resp: HttpResponse, fallback: str) -> str:
    body = resp.json() or {}
    rid = body.get("id")
    return f"{fallback}/{rid}" if rid else fallback


#: LOINC vital code → athena clinicalelementid. Lets callers that already speak
#: LOINC (e.g. the FHIR builders in fhir_writer.py) translate before write_vitals.
VITAL_LOINC_TO_ATHENA: dict[str, str] = {
    "8480-6": "VITALS.BLOODPRESSURE.SYSTOLIC",
    "8462-4": "VITALS.BLOODPRESSURE.DIASTOLIC",
    "8867-4": "VITALS.PULSE",
    "8310-5": "VITALS.TEMPERATURE",
    "9279-1": "VITALS.RESPIRATIONRATE",
    "2708-6": "VITALS.O2SATURATION",
    "59408-5": "VITALS.O2SATURATION",
    "8302-2": "VITALS.HEIGHT",
    "29463-7": "VITALS.WEIGHT",
}


def loinc_vital_to_athena(code_loinc: str, value: float | str) -> dict[str, str]:
    """Translate a LOINC-coded vital into an athena clinicalelementid item.

    Raises :class:`AthenaWriteError` if the LOINC code has no athena mapping.
    """
    cid = VITAL_LOINC_TO_ATHENA.get(code_loinc)
    if not cid:
        raise AthenaWriteError(f"no athena clinicalelementid for LOINC {code_loinc}")
    return {"clinicalelementid": cid, "value": str(value)}


# --------------------------------------------------------------------------
# Router wiring guidance (routers/ehr.py is intentionally NOT edited here)
# --------------------------------------------------------------------------
ROUTER_WIRING = """
Wiring into backend/routers/ehr.py (do this in a follow-up — not done here):

1. Import at top of routers/ehr.py:
       from services import ehr_athena

2. Add a guarded write endpoint, e.g.:

       @router.post("/ehr/{hospital_id}/athena/document")
       def athena_write_document(
           hospital_id: str = Path(...),
           body: dict = Body(...),
           caller: dict = Depends(require_clinician),
       ) -> dict[str, Any]:
           audit(caller, "ehr.athena.write_document", patient_id=body.get("patient_ref"))
           if not ehr_athena.AthenaConfig.is_configured():
               raise HTTPException(status_code=503, detail="athenahealth not configured")
           try:
               client = ehr_athena.AthenaWriteClient(ehr_athena.AthenaConfig.from_env())
               return client.write_document(
                   patient_ref=body["patient_ref"], note_text=body["note_text"],
               )
           except ehr_athena.AthenaAuthError as e:
               log.warning("athena auth failed: %s", e)
               raise HTTPException(status_code=502, detail="athenahealth auth failed")
           except ehr_athena.AthenaWriteError as e:
               log.warning("athena write failed: %s", e)
               raise HTTPException(status_code=502, detail="athenahealth write failed")

   Mirror the same pattern for write_problem / write_allergies / write_vitals.

Notes for the wiring step:
  * routers/ehr.py already imports `audit` + `require_clinician` (lib.auth) and
    `HTTPException` — satisfies QUAL-003 (clinician routes audit + raise).
  * `Body` must be added to the existing `from fastapi import ...` line.
  * No boto3 is introduced, so ARCH-001 is unaffected.
  * AthenaWriteError/AthenaAuthError are caught and never leaked raw to the UI
    (USAB-001 / QUAL-003) — map detail strings to t("error_*") keys frontend-side.
"""
