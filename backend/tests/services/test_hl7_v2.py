"""Unit tests for ``services.hl7_v2`` — HL7 v2.5.1 MDM^T02 emitter.

Only pure rendering / escaping / framing is exercised. The network paths
(``send_mllp``, ``build_and_send_demo``) are not invoked.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

# Imported directly rather than via pytest.importorskip. A guard turns
# "this module is broken" into "these tests were skipped" and lets a red
# build report green, which is how a genuine import failure went unnoticed.
import services.hl7_v2 as hl7


def _patient():
    return hl7.Patient(
        mrn="MRN123", family_name="DOE", given_name="JANE",
        dob="19850321", sex="F", address="1 Main St",
    )


def _provider():
    return hl7.Provider(npi="1234567890", family_name="SMITH", given_name="ALEX")


# ---- _ts -------------------------------------------------------------------
class TestTimestamp:
    def test_format_is_14_digits(self):
        ts = hl7._ts(datetime(2026, 5, 16, 9, 30, 15, tzinfo=timezone.utc))
        assert ts == "20260516093015"
        assert len(ts) == 14 and ts.isdigit()

    def test_default_uses_now(self):
        ts = hl7._ts()
        assert len(ts) == 14 and ts.isdigit()


# ---- _esc ------------------------------------------------------------------
class TestEscape:
    def test_none_becomes_empty(self):
        assert hl7._esc(None) == ""

    def test_plain_text_unchanged(self):
        assert hl7._esc("hello world") == "hello world"

    def test_pipe_escaped(self):
        assert hl7._esc("a|b") == "a\\F\\b"

    def test_caret_escaped(self):
        assert hl7._esc("a^b") == "a\\S\\b"

    def test_ampersand_escaped(self):
        assert hl7._esc("a&b") == "a\\T\\b"

    def test_tilde_escaped(self):
        assert hl7._esc("a~b") == "a\\R\\b"

    def test_backslash_escaped_first(self):
        # backslash must be escaped before the others so \E\ tokens are clean
        assert hl7._esc("a\\b") == "a\\E\\b"

    def test_non_string_coerced(self):
        assert hl7._esc(42) == "42"


# ---- render ----------------------------------------------------------------
class TestRender:
    def test_requires_patient(self):
        msg = hl7.MdmMessage(provider=_provider())
        with pytest.raises(ValueError):
            hl7.render(msg)

    def test_requires_provider(self):
        msg = hl7.MdmMessage(patient=_patient())
        with pytest.raises(ValueError):
            hl7.render(msg)

    def test_segments_present_and_cr_delimited(self):
        # encounter_id is supplied so the optional PV1 segment is emitted,
        # exercising the full MDM^T02 segment layout.
        msg = hl7.MdmMessage(
            patient=_patient(), provider=_provider(), note_text="line one\nline two",
            encounter_id="ENC-1",
        )
        out = hl7.render(msg)
        segs = out.split("\r")
        assert segs[0].startswith("MSH|")
        assert segs[1].startswith("EVN|")
        assert segs[2].startswith("PID|")
        assert segs[3].startswith("PV1|")
        assert segs[4].startswith("TXA|")
        assert segs[5].startswith("OBX|1|")
        assert segs[6].startswith("OBX|2|")

    def test_msh_encoding_characters(self):
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="x")
        out = hl7.render(msg)
        assert out.startswith("MSH|^~\\&|")

    def test_msh_message_type_and_version(self):
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="x")
        msh = hl7.render(msg).split("\r")[0]
        assert "MDM^T02" in msh
        assert msh.endswith("2.5.1")

    def test_patient_demographics_in_pid(self):
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="x")
        pid = [s for s in hl7.render(msg).split("\r") if s.startswith("PID|")][0]
        assert "MRN123" in pid
        assert "DOE^JANE" in pid
        assert "19850321" in pid

    def test_one_obx_per_note_line(self):
        msg = hl7.MdmMessage(
            patient=_patient(), provider=_provider(), note_text="a\nb\nc",
        )
        obx = [s for s in hl7.render(msg).split("\r") if s.startswith("OBX|")]
        assert len(obx) == 3

    def test_empty_note_rejected(self):
        # An MdmMessage with neither note_text nor pdf_base64 is invalid input:
        # render() must refuse it rather than emit a content-free document.
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="")
        with pytest.raises(ValueError):
            hl7.render(msg)

    def test_single_line_note_yields_single_obx(self):
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="only line")
        obx = [s for s in hl7.render(msg).split("\r") if s.startswith("OBX|")]
        assert len(obx) == 1

    def test_special_chars_in_note_escaped(self):
        msg = hl7.MdmMessage(
            patient=_patient(), provider=_provider(), note_text="BP 120|80",
        )
        out = hl7.render(msg)
        assert "120\\F\\80" in out

    def test_control_id_propagates(self):
        msg = hl7.MdmMessage(
            patient=_patient(), provider=_provider(),
            message_control_id="CTRL999", note_text="x",
        )
        assert "CTRL999" in hl7.render(msg)


# ---- to_mllp_frame ---------------------------------------------------------
class TestMllpFrame:
    def test_framing_bytes(self):
        framed = hl7.to_mllp_frame("HELLO")
        assert framed[:1] == hl7.VT
        assert framed[-2:-1] == hl7.FS
        assert framed[-1:] == hl7.CR
        assert b"HELLO" in framed

    def test_roundtrip_payload_recoverable(self):
        msg = hl7.MdmMessage(patient=_patient(), provider=_provider(), note_text="round trip")
        rendered = hl7.render(msg)
        framed = hl7.to_mllp_frame(rendered)
        recovered = framed.strip(hl7.VT + hl7.FS + hl7.CR).decode("utf-8")
        assert recovered == rendered
