"""C3 regression — SSRF guard on outbound EHR/OAuth URLs.

A clinician-writable EHR config must not be able to point Solace's server-side
OAuth/discovery/bulk fetches at the cloud metadata endpoint or an internal VPC
host. ``lib.url_guard`` rejects non-public hosts; ``ehr_config`` surfaces that as
an InvalidEHRConfig on the config write path.
"""
from __future__ import annotations

import os

os.environ["SOLACE_MODE"] = "local"

import pytest  # noqa: E402

from lib import url_guard  # noqa: E402
from services import ehr_config as ehr_config_service  # noqa: E402

# IP literals that must be blocked in EVERY mode (incl. local) — these are the
# real SSRF targets a config-rewrite attack would aim at.
_BLOCKED = [
    "https://169.254.169.254/latest/meta-data/iam/security-credentials/",  # AWS IMDS
    "https://10.0.0.5/fhir",            # private (RFC 1918)
    "https://172.16.4.4/fhir",          # private
    "https://192.168.1.10/fhir",        # private
    "https://0.0.0.0/fhir",             # unspecified
]


@pytest.mark.parametrize("url", _BLOCKED)
def test_guard_blocks_non_public_ip_literals(url):
    with pytest.raises(url_guard.UnsafeURL):
        url_guard.assert_public_https(url, "token_url")


def test_guard_rejects_plain_http_public_host():
    with pytest.raises(url_guard.UnsafeURL):
        url_guard.assert_public_https("http://fhir.epic.com/api", "fhir_base_url")


def test_guard_allows_public_https_placeholder_in_local_mode():
    # Local/test mode validates scheme but skips live DNS resolution so fixtures
    # using placeholder hosts keep working.
    assert url_guard.assert_public_https("https://fhir.epic.com/api/FHIR/R4", "fhir_base_url")


def test_ehr_config_rejects_metadata_token_url():
    # The config write path must surface the guard as a validation error, not 500.
    with pytest.raises(ehr_config_service.InvalidEHRConfig):
        ehr_config_service._require_https(
            "https://169.254.169.254/token", "token_url"
        )
