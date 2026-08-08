"""CONSTITUTION COMP-001 — the Safe Harbor identifiers, checked one at a time.

COMP-001 requires all 15 identifiers named at 45 CFR 164.514(b)(2) to be redacted
from text sent to AI providers, via ``content_guard._PII_REDACTIONS``.

The list looked complete. Running it did not agree. Four identifiers passed
through byte-identical while the module's own comments claimed to cover them:

    # 5. Date of birth patterns (MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, ...)
        neither pattern beneath it matches YYYY-MM-DD

    # 7. ZIP codes (5-digit and ZIP+4)
        the only pattern beneath it requires the +4 suffix

ISO is the one that matters most. FHIR ``Patient.birthDate`` is *always*
YYYY-MM-DD, and this codebase pulls FHIR charts into the context it forwards to
Claude, so every EHR-sourced date of birth in the product reached the provider
intact. And a bare five-digit ZIP is how a person writes a ZIP; the +4 form that
was covered is the rare one.

A comment claiming coverage is worse than no comment, because it is what the next
reviewer reads when deciding not to check. So each identifier gets a test.
"""
from __future__ import annotations

import pytest

from lib.content_guard import scan


def _redacted(text: str) -> tuple[bool, str]:
    ok, cleaned, _findings = scan(text, label="test", source_ip=None, user_agent=None)
    return cleaned != text, cleaned


# ── The four that were passing through ───────────────────────────────────────

@pytest.mark.parametrize("text", [
    "patient date of birth 1962-03-14",
    "DOB: 1962-03-14",
    "birthDate 1962-03-14",
    "born 1962-03-14, presents with chest pain",
])
def test_iso_dates_of_birth_are_redacted(text):
    """FHIR Patient.birthDate is always this shape. Every chart this app pulls
    from an EHR carries one."""
    changed, cleaned = _redacted(text)
    assert changed, f"ISO DOB survived: {cleaned}"
    assert "1962-03-14" not in cleaned


@pytest.mark.parametrize("text", [
    "lives in zip 75201",
    "ZIP 75201",
    "Patient is 94 years old, lives alone, ZIP 75201",
])
def test_bare_five_digit_zips_are_redacted(text):
    changed, cleaned = _redacted(text)
    assert changed, f"5-digit ZIP survived: {cleaned}"
    assert "75201" not in cleaned


@pytest.mark.parametrize("text", ["ssn 123456789", "social security 123456789"])
def test_unformatted_ssns_are_redacted(text):
    """The dashed form was covered. Nine bare digits is how it gets typed into a
    form field that strips punctuation."""
    changed, cleaned = _redacted(text)
    assert changed, f"bare SSN survived: {cleaned}"
    assert "123456789" not in cleaned


@pytest.mark.parametrize("text", [
    "card 3782 822463 10005",     # Amex, 15 digits in 4-6-5
    "amex 378282246310005",
])
def test_amex_card_numbers_are_redacted(text):
    """Visa and Mastercard are 16 digits in groups of four and were covered.
    Amex is 15 in 4-6-5 and was not."""
    changed, cleaned = _redacted(text)
    assert changed, f"Amex survived: {cleaned}"
    assert "10005" not in cleaned


# ── The ones that already worked, which must keep working ────────────────────

@pytest.mark.parametrize("text,secret", [
    ("SSN 123-45-6789", "123-45-6789"),
    ("DOB: 03/14/1962", "03/14/1962"),
    ("lives in 75201-1234", "75201-1234"),
    ("reach me at jane.doe@example.com", "jane.doe@example.com"),
    ("call 512-555-0100", "512-555-0100"),
    ("card 4111 1111 1111 1111", "4111 1111 1111 1111"),
    ("MRN 4483920", "4483920"),
])
def test_the_identifiers_that_already_worked_still_do(text, secret):
    changed, cleaned = _redacted(text)
    assert changed and secret not in cleaned, f"regression: {cleaned}"


# ── Not over-redacting, which is how a guard gets deleted ────────────────────

def test_clinical_text_survives_intact():
    """If the guard mangles ordinary clinical language, someone turns it off.
    These are the sentences a scribe note is actually made of."""
    for text in [
        "Patient reports substernal chest pressure radiating to the left arm.",
        "Started ibuprofen 400mg PO q6h PRN for pain.",
        "Vitals: HR 118, BP 92/60, SpO2 94% on room air, temp 99.1F.",
        "Follow up in 2 weeks or sooner if symptoms worsen.",
    ]:
        changed, cleaned = _redacted(text)
        assert not changed, f"clinical text was redacted: {text!r} -> {cleaned!r}"


def test_esi_levels_and_vitals_are_not_mistaken_for_identifiers():
    changed, cleaned = _redacted("ESI 2, pain 7/10, 3 prior visits in 2025")
    assert not changed, f"clinical numbers redacted: {cleaned}"


# ── The comments have to match the patterns ──────────────────────────────────

def test_every_identifier_the_module_claims_is_actually_covered():
    """The defect here was not a missing pattern, it was a comment that said the
    pattern existed. This asserts each documented format against the code."""
    documented = {
        "MM/DD/YYYY": ("DOB: 03/14/1962", "03/14/1962"),
        "YYYY-MM-DD": ("DOB: 1962-03-14", "1962-03-14"),
        "ZIP 5-digit": ("ZIP 75201", "75201"),
        "ZIP+4": ("ZIP 75201-1234", "75201-1234"),
    }
    missed = []
    for label, (text, secret) in documented.items():
        _ok, cleaned, _f = scan(text, label="test", source_ip=None, user_agent=None)
        if secret in cleaned:
            missed.append(label)
    assert not missed, (
        f"content_guard documents these formats and does not redact them: {missed}"
    )
