"""Public JWKS endpoint for EHR confidential-client (private_key_jwt) auth.

When Solace authenticates to an EHR as a confidential client, it signs an RS384
``private_key_jwt`` assertion with a private key (held only in Secrets Manager).
The vendor (Epic, Oracle Health) verifies that signature against Solace's PUBLIC
key, which it fetches from a JWKS URL. This endpoint IS that URL:

    GET /.well-known/jwks.json  ->  {"keys": [ <public RSA JWK>, ... ]}

The served key set comes from the ``SOLACE_EHR_JWKS`` env var (a JSON
``{"keys": [...]}`` produced by ``scripts/setup_ehr_signing_key.py``). It contains
ONLY public key material — never the private key, never PHI — so the route is
intentionally unauthenticated and cacheable. A missing/malformed value yields an
empty key set (200) rather than an error, so the route never 500s.
"""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Response

log = logging.getLogger(__name__)

router = APIRouter()


def _load_jwks() -> dict:
    raw = os.environ.get("SOLACE_EHR_JWKS", "").strip()
    if not raw:
        return {"keys": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("SOLACE_EHR_JWKS is not valid JSON — serving empty key set")
        return {"keys": []}
    # Accept either a full {"keys": [...]} doc or a bare list of JWKs.
    keys = data.get("keys") if isinstance(data, dict) else data
    if not isinstance(keys, list):
        return {"keys": []}
    # Defense in depth: never echo private-key fields even if misconfigured.
    _private = {"d", "p", "q", "dp", "dq", "qi"}
    public = [
        {k: v for k, v in jwk.items() if k not in _private}
        for jwk in keys if isinstance(jwk, dict)
    ]
    return {"keys": public}


@router.get("/.well-known/jwks.json", tags=["ehr-jwks"])
def jwks() -> Response:
    body = json.dumps(_load_jwks())
    return Response(
        content=body,
        media_type="application/json",
        # Vendors poll this; cache for an hour but allow rotation to propagate.
        headers={"Cache-Control": "public, max-age=3600"},
    )
