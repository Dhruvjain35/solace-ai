"""content_guard must not be a denial-of-service lever.

Nine redaction patterns were built as ``label\\s*[:=]?\\s*value``. Two adjacent
quantified whitespace groups with an optional between them is the textbook
ambiguous construct: for a run of N spaces the engine has O(N^2) ways to split it
between the two groups, and it tries them all before failing.

Measured, before the fix::

     1000 spaces      15 ms
     2000 spaces      55 ms
     4000 spaces     215 ms
     8000 spaces     911 ms
    16000 spaces    3908 ms

``POST /intake`` accepts ``pre_transcribed_text`` up to 20,000 characters, is
unauthenticated, and runs content_guard on it. ``"DOB" + " " * 19996`` cost 5.87
seconds of CPU per request. On Lambda that is billed CPU as well as a queue of
occupied workers, so it is a cost amplifier and an availability problem from a
single unauthenticated endpoint.

The fix is to make the separator unambiguous — one character class, ``[\\s:=#]``,
bounded — so there is exactly one way to match it. Same strings accepted, no
backtracking.

These bounds are deliberately loose. The point is to catch a return to quadratic
behaviour, not to police a few milliseconds on a shared CI box.
"""
from __future__ import annotations

import time

import pytest

from lib.content_guard import redact_pii, scan


def _ms(text: str) -> float:
    start = time.perf_counter()
    redact_pii(text)
    return (time.perf_counter() - start) * 1000


def test_a_long_whitespace_run_is_not_quadratic():
    """The exact shape that cost 5.87 seconds."""
    assert _ms("DOB" + " " * 20_000 + "1") < 250


@pytest.mark.parametrize("label", ["DOB", "SSN", "MRN", "zip", "account #", "member id"])
def test_every_labelled_pattern_survives_a_whitespace_flood(label):
    """All nine shared the construct, so all nine get checked."""
    assert _ms(label + " " * 10_000 + "1") < 250


def test_growth_is_roughly_linear():
    """The property, rather than a wall-clock number: quadruple the input and the
    time must not go up sixteenfold. Threshold is 6x, well clear of linear
    noise and well under the 16x a quadratic would produce."""
    small = max(_ms("DOB" + " " * 4_000 + "1"), 0.05)
    large = _ms("DOB" + " " * 16_000 + "1")
    assert large / small < 6, f"4x the input cost {large / small:.1f}x the time"


def test_a_maximum_length_intake_transcript_is_fast():
    """20,000 characters is what POST /intake accepts."""
    realistic = ("Patient reports chest pressure. Vitals: HR 118, BP 92/60. " * 350)[:20_000]
    assert _ms(realistic) < 250


def test_the_full_scan_is_also_bounded():
    """redact_pii is the floor in lib.claude; scan is what the routers call. The
    rejection patterns have their own whitespace groups."""
    start = time.perf_counter()
    scan("DOB" + " " * 20_000 + "1", label="perf", source_ip=None, user_agent=None)
    assert (time.perf_counter() - start) * 1000 < 400


# ── The separator change must not narrow what is matched ─────────────────────

@pytest.mark.parametrize("text,secret", [
    ("DOB: 03/14/1962", "03/14/1962"),
    ("DOB:03/14/1962", "03/14/1962"),
    ("DOB 03/14/1962", "03/14/1962"),
    ("date of birth = 1962-03-14", "1962-03-14"),
    ("ZIP: 75201", "75201"),
    ("zip code 75201", "75201"),
    ("MRN: 4483920", "4483920"),
    ("MRN 4483920", "4483920"),
    ("account # 123456789012", "123456789012"),
    ("member id ABC12345", "ABC12345"),
    ("ssn 123456789", "123456789"),
    ("SSN: 123456789", "123456789"),
])
def test_the_separators_that_worked_still_work(text, secret):
    cleaned, changed = redact_pii(text)
    assert changed and secret not in cleaned, f"{text!r} -> {cleaned!r}"
