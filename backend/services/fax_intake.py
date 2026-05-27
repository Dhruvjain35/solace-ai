"""Inbound fax → digitization.

Accept faxed PDFs / images, extract structured data with Claude vision, and
classify the document type. Phreesia and Notable both ship this; Solace
democratizes it for the long-tail SMB practice.

Document types we classify and parse:
  - Outbound referral request (specialist asking patient to come in)
  - External record release (hospital discharge / outside chart)
  - Lab / imaging result
  - Payer correspondence (denial, PA approval, eligibility)
  - Patient form (signed consent, intake)
  - Other / unknown

Each parsed document gets routed to the appropriate worklist:
  - Referrals -> referral inbox
  - Records -> chart import queue
  - Results -> result triage
  - Payer -> RCM
  - Forms -> patient registration

Webhook seam
------------
Fax providers (Concord, Documo, Phaxio, Twilio Programmable Fax, plus a
generic fallback) each POST a different JSON shape when a fax lands. The
backend router owns the HTTP request and any network/boto3 work — it hands
this service the *already-decoded* webhook body plus the provider name.
`normalize_webhook()` maps every vendor dialect onto one uniform
`InboundFax` envelope; `ingest_provider_webhook()` then routes the page
payload (PDF or image) into the parsing + classification + worklist
pipeline. No HTTP, no boto3 here — see ARCH-002.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from lib import claude, content_guard
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


# --- Document classification ------------------------------------------------
# document_type -> worklist queue. Single source of truth for routing.
_ROUTE_MAP: dict[str, str] = {
    "referral_request": "referrals",
    "external_record": "records",
    "lab_result": "results",
    "imaging_report": "results",
    "payer_correspondence": "rcm",
    "patient_form": "registration",
    "unknown": "unknown",
}

# Worklist priority: how quickly a human should look at the item.
#   stat   -> critical results / urgent referral, surface immediately
#   high   -> time-sensitive payer or referral work
#   routine-> normal queue
_PRIORITY_BY_ROUTE: dict[str, str] = {
    "results": "high",
    "referrals": "high",
    "rcm": "routine",
    "records": "routine",
    "registration": "routine",
    "unknown": "routine",
}

# Keywords that escalate any document to STAT regardless of route.
_STAT_KEYWORDS = (
    "critical", "panic value", "stat", "urgent", "abnormal",
    "stroke", "myocardial", "sepsis", "positive blood culture",
    "embolism", "hemorrhage", "malignan",
)


_VISION_SYSTEM = """You parse an inbound clinical document image and return a structured digitization.

Return JSON ONLY:
{
  "document_type": "referral_request | external_record | lab_result | imaging_report | payer_correspondence | patient_form | unknown",
  "confidence": 0.0-1.0,
  "patient": {"name": "...", "dob": "YYYY-MM-DD or empty", "mrn": ""},
  "sender": {"organization": "...", "provider_name": "", "phone": "", "fax": ""},
  "subject": "1-line subject of the document",
  "key_facts": ["short fact 1", "short fact 2"],
  "icd10_mentioned": ["..."],
  "cpt_or_loinc_mentioned": ["..."],
  "action_required": "1-2 sentence imperative for the receiving practice",
  "route_to": "referrals | records | results | rcm | registration | unknown"
}

Rules:
- Be conservative — leave fields empty if you cannot extract them.
- Never hallucinate a name, DOB, or MRN.
- 'route_to' must match the document_type.
"""


# ============================================================================
# Webhook normalization seam
# ============================================================================

def _first(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    """Return the first present, non-empty value among `keys`."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _normalize_concord(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "fax_id": _first(body, "TransmissionID", "transmissionId", "id"),
        "from_number": _first(body, "CallingNumber", "fromNumber"),
        "to_number": _first(body, "CalledNumber", "toNumber"),
        "page_count": int(_first(body, "Pages", "pageCount", default=0) or 0),
        "status": _first(body, "Status", "status", default="received"),
        "received_at": _first(body, "ReceivedDate", "timestamp"),
        "media_url": _first(body, "DocumentURL", "documentUrl"),
        "media_b64": _first(body, "DocumentData", "documentBase64"),
        "content_type": _first(body, "ContentType", default="application/pdf"),
    }


def _normalize_documo(body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data", body) if isinstance(body.get("data"), dict) else body
    return {
        "fax_id": _first(data, "faxId", "id"),
        "from_number": _first(data, "from", "sourceNumber"),
        "to_number": _first(data, "to", "destinationNumber"),
        "page_count": int(_first(data, "pages", "pageCount", default=0) or 0),
        "status": _first(data, "status", default="received"),
        "received_at": _first(data, "createdAt", "completedAt"),
        "media_url": _first(data, "downloadUrl", "fileUrl"),
        "media_b64": _first(data, "fileBase64"),
        "content_type": _first(data, "mimeType", default="application/pdf"),
    }


def _normalize_phaxio(body: dict[str, Any]) -> dict[str, Any]:
    fax = body.get("fax", body) if isinstance(body.get("fax"), dict) else body
    return {
        "fax_id": str(_first(fax, "id", "fax_id")),
        "from_number": _first(fax, "from_number", "caller_id"),
        "to_number": _first(fax, "to_number", "recipient"),
        "page_count": int(_first(fax, "num_pages", "pages", default=0) or 0),
        "status": _first(fax, "status", "direction", default="received"),
        "received_at": _first(fax, "completed_at", "created_at"),
        "media_url": _first(fax, "media_url", "file_url"),
        "media_b64": _first(fax, "file"),
        "content_type": _first(fax, "content_type", default="application/pdf"),
    }


def _normalize_twilio(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "fax_id": _first(body, "FaxSid", "MessageSid"),
        "from_number": _first(body, "From"),
        "to_number": _first(body, "To"),
        "page_count": int(_first(body, "NumPages", "NumMedia", default=0) or 0),
        "status": _first(body, "FaxStatus", "Status", default="received"),
        "received_at": _first(body, "DateCreated", "DateUpdated"),
        "media_url": _first(body, "MediaUrl", "OriginalMediaUrl"),
        "media_b64": "",  # Twilio always serves media by URL
        "content_type": _first(body, "MediaContentType", default="application/pdf"),
    }


def _normalize_generic(body: dict[str, Any]) -> dict[str, Any]:
    """Best-effort fallback for an unrecognized vendor or a hand-rolled POST."""
    return {
        "fax_id": _first(body, "fax_id", "id", "transmission_id"),
        "from_number": _first(body, "from", "from_number", "sender"),
        "to_number": _first(body, "to", "to_number", "recipient"),
        "page_count": int(_first(body, "page_count", "pages", default=0) or 0),
        "status": _first(body, "status", default="received"),
        "received_at": _first(body, "received_at", "timestamp", "created_at"),
        "media_url": _first(body, "media_url", "url", "document_url"),
        "media_b64": _first(body, "media_b64", "document_b64", "file_base64"),
        "content_type": _first(body, "content_type", "mime_type", default="application/pdf"),
    }


_VENDOR_MAPS = {
    "concord": _normalize_concord,
    "documo": _normalize_documo,
    "mfax": _normalize_documo,        # mFax is Documo's product name
    "phaxio": _normalize_phaxio,
    "twilio": _normalize_twilio,
}


def normalize_webhook(provider: str, body: dict[str, Any]) -> dict[str, Any]:
    """Map any fax-vendor webhook body onto a uniform InboundFax envelope.

    The router decodes the HTTP request and passes `provider` (lowercased
    vendor slug) plus the parsed JSON `body`. Unknown providers fall back to
    the generic field map.

    Returns an InboundFax dict:
      {
        "provider": str, "fax_id": str,
        "from_number": str, "to_number": str,
        "page_count": int, "status": str, "received_at": str,
        "media_url": str, "media_b64": str, "content_type": str,
        "is_complete": bool,        # status indicates a fully received fax
        "has_media": bool,          # media_url or media_b64 present
      }
    """
    slug = (provider or "").strip().lower()
    mapper = _VENDOR_MAPS.get(slug, _normalize_generic)
    if not isinstance(body, dict):
        body = {}
    env = mapper(body)
    env["provider"] = slug or "generic"
    status = str(env.get("status", "")).lower()
    env["is_complete"] = status in (
        "received", "completed", "success", "delivered", "inbound", "ok",
    ) or not status
    env["has_media"] = bool(env.get("media_url") or env.get("media_b64"))
    return env


# ============================================================================
# Document-type classification + worklist routing
# ============================================================================

def classify_document(parsed: dict[str, Any]) -> dict[str, Any]:
    """Map a parsed digitization onto worklist + priority.

    Deterministic: trusts the model's `document_type` but recomputes
    `route_to` from `_ROUTE_MAP` (never trust the model's own routing) and
    derives priority from the route plus STAT keyword scan.

    Returns {document_type, route_to, priority, escalated, low_confidence}.
    """
    doc_type = str(parsed.get("document_type", "unknown")).strip().lower()
    if doc_type not in _ROUTE_MAP:
        doc_type = "unknown"
    route_to = _ROUTE_MAP[doc_type]
    priority = _PRIORITY_BY_ROUTE.get(route_to, "routine")

    # STAT escalation — scan model-extracted text fields for critical keywords.
    haystack = " ".join(
        str(x) for x in (
            parsed.get("subject", ""),
            parsed.get("action_required", ""),
            *(parsed.get("key_facts", []) or []),
        )
    ).lower()
    escalated = any(kw in haystack for kw in _STAT_KEYWORDS)
    if escalated:
        priority = "stat"

    try:
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    low_confidence = confidence < 0.55 or doc_type == "unknown"

    return {
        "document_type": doc_type,
        "route_to": route_to,
        "priority": priority,
        "escalated": escalated,
        "low_confidence": low_confidence,
        "confidence": confidence,
    }


def parse_image_b64(image_b64: str, *, content_type: str = "image/png") -> dict[str, Any]:
    """Image must be base64-encoded WITHOUT the data:URL prefix."""
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "no_anthropic_key"}
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": image_b64}},
                    {"type": "text", "text": "Parse this faxed clinical document. Return the JSON now."},
                ],
            }],
            purpose="fax_intake",
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, **json.loads(text)}
    except Exception as e:
        log.warning("fax_intake parse failed: %s", e)
        return {"available": False, "error": str(e)}


def parse_pdf_bytes(pdf_bytes: bytes) -> dict[str, Any]:
    """Convert first page of a PDF to PNG and parse via vision. Best-effort with Pillow + pypdf."""
    try:
        # Try pdf2image-equivalent: use Pillow + PyMuPDF if available, else fall back to text extraction.
        from io import BytesIO
        try:
            import fitz  # type: ignore  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc.load_page(0)
            pix = page.get_pixmap(dpi=150)
            png = pix.tobytes("png")
            return parse_image_b64(base64.b64encode(png).decode("ascii"), content_type="image/png")
        except Exception:
            pass
        # Final fallback: pull text and parse via text-only model
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(BytesIO(pdf_bytes))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:3])[:14000]
            return parse_text(text)
        except Exception as e:
            return {"available": False, "error": f"pdf parsing unavailable: {e}"}
    except Exception as e:
        return {"available": False, "error": str(e)}


def parse_text(text: str) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        return {"available": False, "reason": "no_anthropic_key"}
    # Content guard before the AI call — strips LLM control tokens / PII and
    # rejects prompt-injection payloads embedded in OCR'd fax text (SEC-005).
    safe, cleaned, findings = content_guard.scan(text, label="fax_intake_text")
    if not safe:
        log.warning("fax_intake parse_text rejected by content guard: %s", findings)
        return {"available": False, "error": "content_guard_rejected", "findings": findings}
    text = cleaned
    try:
        resp = claude.messages_create(
            model=_MODEL,
            max_tokens=900,
            system=_VISION_SYSTEM,
            messages=[{"role": "user", "content": f"Document text:\n\"\"\"\n{text[:14000]}\n\"\"\"\n\nReturn JSON now."}],
            purpose="fax_intake_text",
        )
        out = "".join(getattr(b, "text", "") for b in resp.content).strip()
        out = out.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return {"available": True, **json.loads(out)}
    except Exception as e:
        log.warning("fax_intake parse_text failed: %s", e)
        return {"available": False, "error": str(e)}


# ============================================================================
# Provider webhook ingestion — the public seam the router calls
# ============================================================================

def ingest_provider_webhook(
    provider: str,
    body: dict[str, Any],
    *,
    media_bytes: bytes | None = None,
    media_b64: str | None = None,
) -> dict[str, Any]:
    """Normalize a fax-provider webhook, parse the document, and route it.

    The router owns all network/boto3 work: it normalizes via this function,
    and if the resulting envelope reports `media_url` (no inline media) the
    router downloads the bytes and re-invokes with `media_bytes` set.

    Args:
      provider: vendor slug ("concord" | "documo" | "phaxio" | "twilio" | ...).
      body: decoded webhook JSON.
      media_bytes: raw fax document bytes, if the router fetched them.
      media_b64: base64 document data (no data:URL prefix), if available.

    Returns:
      {
        "envelope": InboundFax,         # from normalize_webhook()
        "status": "parsed" | "needs_media_fetch" | "incomplete" | "parse_failed",
        "parsed": {...} | None,         # digitization from the vision model
        "routing": {...} | None,        # classify_document() output
      }
    """
    env = normalize_webhook(provider, body)

    if not env["is_complete"]:
        return {"envelope": env, "status": "incomplete", "parsed": None, "routing": None}

    # Resolve the document payload. Prefer caller-supplied bytes, then inline
    # base64 (from the webhook or the caller), then signal a fetch is needed.
    b64 = media_b64 or env.get("media_b64") or ""
    content_type = str(env.get("content_type", "application/pdf")).lower()

    if media_bytes is not None:
        parsed = _parse_payload(media_bytes, content_type)
    elif b64:
        try:
            payload = base64.b64decode(b64)
        except Exception as e:
            return {
                "envelope": env, "status": "parse_failed",
                "parsed": {"available": False, "error": f"bad base64: {e}"},
                "routing": None,
            }
        parsed = _parse_payload(payload, content_type)
    elif env.get("media_url"):
        # Router must download env["media_url"] and re-call with media_bytes.
        return {"envelope": env, "status": "needs_media_fetch", "parsed": None, "routing": None}
    else:
        return {
            "envelope": env, "status": "parse_failed",
            "parsed": {"available": False, "error": "no media in webhook"},
            "routing": None,
        }

    if not parsed.get("available"):
        return {"envelope": env, "status": "parse_failed", "parsed": parsed, "routing": None}

    routing = classify_document(parsed)
    return {"envelope": env, "status": "parsed", "parsed": parsed, "routing": routing}


def _parse_payload(payload: bytes, content_type: str) -> dict[str, Any]:
    """Dispatch raw document bytes to the PDF or image parser by content type."""
    if "pdf" in content_type:
        return parse_pdf_bytes(payload)
    media_type = content_type if content_type.startswith("image/") else "image/png"
    return parse_image_b64(base64.b64encode(payload).decode("ascii"), content_type=media_type)
