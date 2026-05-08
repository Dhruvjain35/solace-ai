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
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from lib import claude
from lib.config import settings

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"


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
