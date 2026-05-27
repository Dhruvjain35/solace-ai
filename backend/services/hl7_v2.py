"""HL7 v2.5.1 MDM^T02 (medical document) emitter, parser, and ACK handler.

Routes Solace-authored notes into the long tail of EHRs (Meditech Magic /
Expanse legacy, NextGen, eClinicalWorks, Allscripts/Veradigm, OpenEMR HL7,
OSCAR, community hospitals) via the integration engines they actually deploy:
Mirth Connect, Rhapsody, Corepoint, Cloverleaf.

Output is a fully-formed HL7 v2.5.1 MDM^T02 message ready to ship over MLLP
(Minimal Lower Layer Protocol: VT + payload + FS + CR). The MLLP framing helper
sends the message; production callers will queue the framed message to their
Mirth channel via a TCP socket.

MDM^T02 segment layout produced here:

    MSH  message header (encoding chars, app/facility routing, control id)
    EVN  event type (T02) + recorded date/time
    PID  patient identification (CX MRN, XPN name, address)
    PV1  patient visit (optional; emitted when an encounter id is supplied)
    TXA  transcription document header (document type, status, provider XCN,
         unique document number as an EI)
    OBX  observation/result, repeated. Two body modes:
           - TX  : one OBX per text line (value type TX)
           - ED  : a single OBX carrying a base64 PDF (value type ED)

TXA-17 (document completion status) is kept in lockstep with OBX-11
(observation result status) per the HL7 v2.5.1 conformance note for MDM.

Delimiter handling escapes the five HL7 separators via \\F\\ \\S\\ \\T\\ \\R\\ \\E\\
and emits non-printable characters as \\Xdd\\ hex escapes. parse() reverses both.
"""
from __future__ import annotations

import logging
import re
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

VT = b"\x0b"   # MLLP start block
FS = b"\x1c"   # MLLP end block
CR = b"\x0d"   # segment terminator / MLLP trailer

# HL7 v2.5.1 default encoding characters (MSH-1 is the field separator "|",
# MSH-2 carries component / repetition / escape / subcomponent).
FIELD_SEP = "|"
COMP_SEP = "^"
REP_SEP = "~"
ESC_CHAR = "\\"
SUBCOMP_SEP = "&"
ENCODING_CHARS = COMP_SEP + REP_SEP + ESC_CHAR + SUBCOMP_SEP  # "^~\&"

# Control IDs must fit MSH-10 (ST, 1..20). We use 20 hex chars from a uuid4.
_CONTROL_ID_LEN = 20

# Application ACK acknowledgement codes (MSA-1).
_ACK_OK = "AA"      # Application Accept
_ACK_ERROR = "AE"   # Application Error
_ACK_REJECT = "AR"  # Application Reject


def _new_control_id() -> str:
    return uuid.uuid4().hex[:_CONTROL_ID_LEN].upper()


def _ts(dt: datetime | None = None) -> str:
    """HL7 DTM timestamp, second precision, UTC."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S")


# --------------------------------------------------------------------------
# Delimiter escaping
# --------------------------------------------------------------------------

# Map of literal delimiter -> HL7 escape sequence. Order matters: the escape
# character itself must be substituted first so we do not double-escape the
# backslashes introduced by the other replacements.
_ESCAPE_PAIRS = [
    (ESC_CHAR, "\\E\\"),
    (FIELD_SEP, "\\F\\"),
    (COMP_SEP, "\\S\\"),
    (SUBCOMP_SEP, "\\T\\"),
    (REP_SEP, "\\R\\"),
]


def _esc(s: Any) -> str:
    """Escape a single HL7 field value.

    Substitutes the five delimiter characters with their \\F\\-style escape
    sequences and emits any other non-printable / control character (CR, LF,
    tabs, etc.) as a \\Xdd\\ hex escape so segment framing cannot be broken by
    embedded data.
    """
    if s is None:
        return ""
    s = str(s)
    for literal, escape in _ESCAPE_PAIRS:
        s = s.replace(literal, escape)
    out: list[str] = []
    for ch in s:
        code = ord(ch)
        # Block C0 controls and DEL; everything else passes through.
        if code < 0x20 or code == 0x7F:
            out.append("\\X%02X\\" % code)
        else:
            out.append(ch)
    return "".join(out)


_HEX_ESCAPE_RE = re.compile(r"\\X([0-9A-Fa-f]+)\\")


def _unescape(s: str) -> str:
    """Reverse _esc(): turn \\F\\ / \\Xdd\\ style escapes back into literals."""
    if not s:
        return ""

    # First decode \Xdd\ hex escapes (each pair of hex digits = one char).
    def _hex(m: re.Match[str]) -> str:
        digits = m.group(1)
        chars = []
        for i in range(0, len(digits), 2):
            chars.append(chr(int(digits[i:i + 2], 16)))
        return "".join(chars)

    s = _HEX_ESCAPE_RE.sub(_hex, s)

    # Then decode the delimiter escapes. \E\ must come last so it does not
    # consume the backslashes belonging to the other sequences.
    s = (
        s.replace("\\F\\", FIELD_SEP)
         .replace("\\S\\", COMP_SEP)
         .replace("\\T\\", SUBCOMP_SEP)
         .replace("\\R\\", REP_SEP)
         .replace("\\E\\", ESC_CHAR)
    )
    return s


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------

@dataclass
class Patient:
    mrn: str
    family_name: str
    given_name: str
    dob: str  # YYYYMMDD
    sex: str  # M | F | O | U
    middle_name: str = ""
    address: str = ""              # free-text street, mapped to XAD-1
    assigning_authority: str = ""  # CX-4; defaults to receiving facility


@dataclass
class Provider:
    npi: str
    family_name: str
    given_name: str
    middle_name: str = ""
    id_type: str = "NPI"              # XCN-13 identifier type code
    assigning_authority: str = "CMS"  # XCN-9


@dataclass
class MdmMessage:
    sending_app: str = "SOLACE"
    sending_facility: str = "SOLACE_HUB"
    receiving_app: str = "EHR"
    receiving_facility: str = "HOSPITAL"
    message_control_id: str = field(default_factory=_new_control_id)
    processing_id: str = "P"            # P production, T test, D debug

    # Document body. Exactly one of note_text / pdf_base64 drives the OBX block.
    note_text: str = ""
    pdf_base64: str = ""                # if set, emits a single OBX|ED segment

    note_type_code: str = "PROG"        # TXA-2 document type
    note_type_display: str = "Progress note"
    document_status: str = "DO"         # TXA-17: DO documented(final), IP, etc.

    # EI document number (TXA-12). Auto-assigned when blank.
    document_number: str = ""

    encounter_id: str = ""              # drives PV1 emission when present
    visit_class: str = "O"              # PV1-2: O outpatient, I inpatient, E ED
    patient: Patient | None = None
    provider: Provider | None = None

    event_dt: str = field(default_factory=_ts)  # EVN-2 / TXA activity time

    def __post_init__(self) -> None:
        if not self.document_number:
            self.document_number = "SOLACE-" + uuid.uuid4().hex[:12].upper()


# OBX-11 result status that pairs with each TXA-17 document status.
# HL7 conformance: a final document carries final ("F") observations; an
# in-progress document carries preliminary ("P") observations.
_TXA17_TO_OBX11 = {
    "DO": "F",  # Documented -> Final
    "AU": "F",  # Authenticated -> Final
    "LA": "F",  # Legally authenticated -> Final
    "IP": "P",  # In progress -> Preliminary
    "PA": "P",  # Pre-authenticated -> Preliminary
    "CA": "C",  # Cancelled -> Corrected/cancelled status flagged on OBX
}


def _obx11_for(document_status: str) -> str:
    return _TXA17_TO_OBX11.get((document_status or "").upper(), "F")


def _xcn(provider: Provider) -> str:
    """Render a Provider as an HL7 XCN (extended composite ID + name)."""
    return COMP_SEP.join([
        _esc(provider.npi),            # XCN-1 ID number
        _esc(provider.family_name),    # XCN-2 family name
        _esc(provider.given_name),     # XCN-3 given name
        _esc(provider.middle_name),    # XCN-4 second/further given names
        "", "", "", "",                # XCN-5..8
        _esc(provider.assigning_authority),  # XCN-9 assigning authority
        "", "", "", "",                # XCN-10..12
        _esc(provider.id_type),        # XCN-13 identifier type code
    ]).rstrip(COMP_SEP)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render(msg: MdmMessage) -> str:
    """Build the HL7 v2.5.1 MDM^T02 pipe-delimited string (CR-terminated)."""
    if msg.patient is None:
        raise ValueError("MdmMessage requires a patient")
    if msg.provider is None:
        raise ValueError("MdmMessage requires a provider")
    if msg.pdf_base64 and msg.note_text:
        raise ValueError("provide either note_text or pdf_base64, not both")
    if not msg.pdf_base64 and not msg.note_text:
        raise ValueError("MdmMessage requires note_text or pdf_base64")

    p = msg.patient
    pr = msg.provider
    now = _ts()
    event_dt = msg.event_dt or now
    auth = p.assigning_authority or msg.receiving_facility

    # MSH-1 is the field separator; MSH-2 is the encoding chars. These two are
    # positional and must NOT be escaped.
    msh = (
        "MSH" + FIELD_SEP + ENCODING_CHARS + FIELD_SEP
        + _esc(msg.sending_app) + FIELD_SEP
        + _esc(msg.sending_facility) + FIELD_SEP
        + _esc(msg.receiving_app) + FIELD_SEP
        + _esc(msg.receiving_facility) + FIELD_SEP
        + now + FIELD_SEP                       # MSH-7 date/time of message
        + FIELD_SEP                             # MSH-8 security
        + "MDM" + COMP_SEP + "T02" + COMP_SEP + "MDM_T02" + FIELD_SEP  # MSH-9
        + _esc(msg.message_control_id) + FIELD_SEP   # MSH-10 control id
        + _esc(msg.processing_id) + FIELD_SEP        # MSH-11 processing id
        + "2.5.1"                                    # MSH-12 version id
    )

    evn = FIELD_SEP.join(["EVN", "T02", event_dt])

    pid = (
        "PID" + FIELD_SEP
        + "1" + FIELD_SEP                       # PID-1 set id
        + FIELD_SEP                             # PID-2 (deprecated)
        # PID-3 patient identifier list as a CX: id^^^authority^typecode
        + COMP_SEP.join([_esc(p.mrn), "", "", _esc(auth), "MR"]) + FIELD_SEP
        + FIELD_SEP                             # PID-4
        # PID-5 patient name as XPN: family^given^middle
        + COMP_SEP.join([
            _esc(p.family_name), _esc(p.given_name), _esc(p.middle_name),
        ]).rstrip(COMP_SEP) + FIELD_SEP
        + FIELD_SEP                             # PID-6 mother's maiden name
        + _esc(p.dob) + FIELD_SEP               # PID-7 date/time of birth
        + _esc(p.sex) + FIELD_SEP               # PID-8 administrative sex
        + FIELD_SEP                             # PID-9
        + FIELD_SEP                             # PID-10 race
        # PID-11 address as XAD: street is the first component
        + _esc(p.address)
    )

    segments = [msh, evn, pid]

    # PV1 is optional in MDM^T02; emit only when an encounter id is supplied.
    if msg.encounter_id:
        pv1 = (
            "PV1" + FIELD_SEP
            + "1" + FIELD_SEP                   # PV1-1 set id
            + _esc(msg.visit_class) + FIELD_SEP  # PV1-2 patient class
            + FIELD_SEP * 4                     # PV1-3..6
            + _xcn(pr) + FIELD_SEP              # PV1-7 attending doctor (XCN)
            + FIELD_SEP * 11                    # PV1-8..18
            + COMP_SEP.join([_esc(msg.encounter_id), "", "", _esc(auth)])
            # PV1-19 visit number (CX)
        )
        segments.append(pv1)

    obx11 = _obx11_for(msg.document_status)
    body_value_type = "ED" if msg.pdf_base64 else "TX"

    txa = (
        "TXA" + FIELD_SEP
        + "1" + FIELD_SEP                       # TXA-1 set id
        # TXA-2 document type as CE: code^display
        + COMP_SEP.join([_esc(msg.note_type_code), _esc(msg.note_type_display)])
        + FIELD_SEP
        + body_value_type + FIELD_SEP           # TXA-3 document content present
        + event_dt + FIELD_SEP                  # TXA-4 activity date/time
        + _xcn(pr) + FIELD_SEP                  # TXA-5 primary activity provider
        + FIELD_SEP                             # TXA-6 origination date/time
        + FIELD_SEP                             # TXA-7 transcription date/time
        + FIELD_SEP                             # TXA-8 edit date/time
        + _xcn(pr) + FIELD_SEP                  # TXA-9 originator (XCN)
        + FIELD_SEP                             # TXA-10 assigned document
        + _xcn(pr) + FIELD_SEP                  # TXA-11 transcriptionist (XCN)
        # TXA-12 unique document number as an EI: entity id^namespace
        + COMP_SEP.join([_esc(msg.document_number), _esc(msg.sending_app)])
        + FIELD_SEP
        + FIELD_SEP                             # TXA-13 parent document number
        + FIELD_SEP                             # TXA-14 placer order number
        + FIELD_SEP                             # TXA-15 filler order number
        + FIELD_SEP                             # TXA-16 unique document file name
        + _esc(msg.document_status)             # TXA-17 document completion status
    )
    segments.append(txa)

    # OBX block. Two body modes.
    if msg.pdf_base64:
        # Single OBX|ED. ED data type: source^type^subtype^encoding^data.
        ed = COMP_SEP.join([
            "",                    # ED-1 source application
            "application",         # ED-2 type of data
            "pdf",                 # ED-3 data subtype
            "Base64",              # ED-4 encoding
            _esc(msg.pdf_base64),  # ED-5 data
        ])
        obx = (
            "OBX" + FIELD_SEP
            + "1" + FIELD_SEP                   # OBX-1 set id
            + "ED" + FIELD_SEP                  # OBX-2 value type
            + COMP_SEP.join([
                _esc(msg.note_type_code), _esc(msg.note_type_display), "L",
            ]) + FIELD_SEP                      # OBX-3 observation identifier
            + FIELD_SEP                         # OBX-4 observation sub-id
            + ed + FIELD_SEP                    # OBX-5 observation value (ED)
            + FIELD_SEP * 5                     # OBX-6..10
            + obx11                             # OBX-11 result status
        )
        segments.append(obx)
    else:
        # Repeated OBX|TX, one segment per logical line of the note.
        lines = (msg.note_text or "").replace("\r\n", "\n").replace("\r", "\n")
        for i, line in enumerate(lines.split("\n"), start=1):
            obx = (
                "OBX" + FIELD_SEP
                + str(i) + FIELD_SEP            # OBX-1 set id
                + "TX" + FIELD_SEP              # OBX-2 value type
                + COMP_SEP.join([
                    _esc(msg.note_type_code), _esc(msg.note_type_display), "L",
                ]) + FIELD_SEP                  # OBX-3 observation identifier
                + FIELD_SEP                     # OBX-4 observation sub-id
                + _esc(line) + FIELD_SEP        # OBX-5 observation value (TX)
                + FIELD_SEP * 5                 # OBX-6..10
                + obx11                         # OBX-11 result status
            )
            segments.append(obx)

    return "\r".join(segments)


def to_pipe_string(msg: MdmMessage) -> str:
    """Bare HL7 string for logging or queuing into a non-MLLP transport."""
    return render(msg)


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def parse(message: str) -> dict[str, Any]:
    """Parse an HL7 v2 pipe-delimited message into a structured dict.

    Returns a dict keyed by segment name. Repeating segments (OBX) are stored
    under a list. Field values are returned with HL7 escapes decoded, except
    for MSH-1/MSH-2 which are positional and kept raw.
    """
    if not message:
        raise ValueError("empty HL7 message")

    # Strip MLLP framing if present and normalise terminators to CR.
    text = message.strip("\x0b\x1c").replace("\r\n", "\r").replace("\n", "\r")
    raw_segments = [s for s in text.split("\r") if s]
    if not raw_segments or not raw_segments[0].startswith("MSH"):
        raise ValueError("HL7 message must begin with an MSH segment")

    msh0 = raw_segments[0]
    field_sep = msh0[3]  # MSH-1 is the char right after "MSH"

    result: dict[str, Any] = {"_segments": []}
    for raw in raw_segments:
        fields = raw.split(field_sep)
        name = fields[0]

        if name == "MSH":
            # Re-insert the field separator as MSH-1 so downstream indexing
            # matches the HL7 spec (MSH-1 == "|", MSH-2 == "^~\&").
            decoded = [field_sep, fields[1]] + [
                _unescape(f) for f in fields[2:]
            ]
        else:
            decoded = [name] + [_unescape(f) for f in fields[1:]]

        seg = {"name": name, "fields": decoded}
        result["_segments"].append(seg)
        if name == "OBX":
            result.setdefault("OBX", []).append(decoded)
        else:
            result.setdefault(name, decoded)

    return result


def _seg_field(fields: list[str], index: int) -> str:
    """1-based HL7 field accessor (field index 1 == fields[1])."""
    return fields[index] if 0 <= index < len(fields) else ""


def extract_document_text(message: str) -> str:
    """Return the document body from an MDM message.

    For an OBX|TX message the text lines are joined with newlines. For an
    OBX|ED message the base64 payload (ED-5) of the single OBX is returned.
    """
    parsed = parse(message)
    obx_segments = parsed.get("OBX", [])
    if not obx_segments:
        return ""

    first = obx_segments[0]
    value_type = _seg_field(first, 2)

    if value_type == "ED":
        ed_value = _seg_field(first, 5)
        # ED-5 is the data component of source^type^subtype^encoding^data.
        comps = ed_value.split(COMP_SEP)
        return comps[4] if len(comps) >= 5 else ed_value

    # TX mode: OBX-5 of each segment is one line.
    lines = [_seg_field(seg, 5) for seg in obx_segments]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Acknowledgement (ACK^T02 / generic ACK) handling
# --------------------------------------------------------------------------

def parse_ack(ack_message: str) -> dict[str, Any]:
    """Parse an HL7 ACK and return its acknowledgement outcome.

    Returns a dict with:
        ack_code        MSA-1 (AA / AE / AR)
        accepted        True only when ack_code == "AA"
        control_id      MSA-2 message control id being acknowledged
        text_message    MSA-3 free-text status
        error           ERR segment text if present, else ""
    """
    out: dict[str, Any] = {
        "ack_code": "",
        "accepted": False,
        "control_id": "",
        "text_message": "",
        "error": "",
    }
    try:
        parsed = parse(ack_message)
    except ValueError as e:
        out["error"] = str(e)
        return out

    msa = parsed.get("MSA")
    if msa:
        out["ack_code"] = _seg_field(msa, 1)
        out["control_id"] = _seg_field(msa, 2)
        out["text_message"] = _seg_field(msa, 3)
        out["accepted"] = out["ack_code"] == _ACK_OK

    err = parsed.get("ERR")
    if err:
        # ERR-1 (legacy) or ERR-3/ERR-8 (v2.5+). Capture whatever is populated.
        out["error"] = " ".join(f for f in err[1:] if f).strip()

    return out


def build_ack(
    original: str,
    *,
    ack_code: str = _ACK_OK,
    text_message: str = "",
    error_text: str = "",
) -> str:
    """Build an HL7 ACK responding to a received message.

    Used when Solace acts as the receiver (e.g. inbound MDM from an EHR) or in
    self_check round-trips. MSA-2 echoes the original MSH-10 control id.
    """
    parsed = parse(original)
    msh = parsed.get("MSH")
    if not msh:
        raise ValueError("cannot ACK a message without an MSH segment")

    # MSH indexing note: parse() places MSH-1 (the field separator) at list
    # index 0, so HL7 spec field MSH-N lives at decoded[N-1].
    # Swap sender/receiver so the ACK routes back to the originator.
    sending_app = _seg_field(msh, 4)         # MSH-5 original receiving app
    sending_facility = _seg_field(msh, 5)    # MSH-6 original receiving facility
    receiving_app = _seg_field(msh, 2)       # MSH-3 original sending app
    receiving_facility = _seg_field(msh, 3)  # MSH-4 original sending facility
    orig_control_id = _seg_field(msh, 9)     # MSH-10 message control id
    processing_id = _seg_field(msh, 10) or "P"  # MSH-11 processing id
    now = _ts()

    ack_msh = (
        "MSH" + FIELD_SEP + ENCODING_CHARS + FIELD_SEP
        + _esc(sending_app) + FIELD_SEP
        + _esc(sending_facility) + FIELD_SEP
        + _esc(receiving_app) + FIELD_SEP
        + _esc(receiving_facility) + FIELD_SEP
        + now + FIELD_SEP
        + FIELD_SEP
        + "ACK" + COMP_SEP + "T02" + COMP_SEP + "ACK" + FIELD_SEP
        + _new_control_id() + FIELD_SEP
        + _esc(processing_id) + FIELD_SEP
        + "2.5.1"
    )
    msa = FIELD_SEP.join([
        "MSA", _esc(ack_code), _esc(orig_control_id), _esc(text_message),
    ])
    segments = [ack_msh, msa]
    if error_text and ack_code != _ACK_OK:
        # ERR-3 (HL7 error code) left blank; ERR-8 carries user message.
        err = FIELD_SEP.join(["ERR", "", "", "", "", "", "", _esc(error_text)])
        segments.append(err)
    return "\r".join(segments)


# --------------------------------------------------------------------------
# MLLP transport
# --------------------------------------------------------------------------

def to_mllp_frame(message: str) -> bytes:
    """Wrap an HL7 string in MLLP framing: VT + payload + FS + CR."""
    return VT + message.encode("utf-8") + FS + CR


def send_mllp(host: str, port: int, message: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Open a TCP connection to a Mirth/Rhapsody/Corepoint listener and write
    the MLLP-framed message, then parse the inbound ACK.

    Returns a dict with the parse_ack() outcome plus transport status. Gate
    behind a feature flag; production callers wrap this in a retry queue.
    """
    framed = to_mllp_frame(message)
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.sendall(framed)
            sock.settimeout(timeout)
            chunks: list[bytes] = []
            while True:
                buf = sock.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
                if FS in buf:
                    break
            raw = b"".join(chunks)
        body = raw.strip(VT + FS + CR).decode("utf-8", errors="replace")
        ack = parse_ack(body)
        return {
            "sent": True,
            "ack_code": ack["ack_code"],
            "accepted": ack["accepted"],
            "error": ack["error"],
            "raw_ack": body[:500],
        }
    except Exception as e:  # noqa: BLE001 - transport errors surfaced to caller
        log.warning("MLLP send failed: %s", e)
        return {"sent": False, "accepted": False, "error": str(e)}


# --------------------------------------------------------------------------
# Self-check round trip
# --------------------------------------------------------------------------

def self_check() -> dict[str, Any]:
    """Render -> parse -> ACK round-trip smoke test for both body modes.

    Returns a dict of pass/fail booleans. Raises AssertionError on the first
    hard failure so callers can fail fast.
    """
    import base64

    results: dict[str, Any] = {}

    patient = Patient(
        mrn="MRN|0042",            # embedded delimiter exercises escaping
        family_name="O'Brien",
        given_name="Mary^Jane",    # embedded component separator
        dob="19850321",
        sex="F",
        address="500 Main St",
    )
    provider = Provider(
        npi="1234567890",
        family_name="Smith",
        given_name="Alex",
        middle_name="R",
    )

    # --- TX mode ---------------------------------------------------------
    tx_note = "Chief complaint: chest pain.\nVitals stable.\nPlan: ECG & troponin."
    tx_msg = MdmMessage(
        note_text=tx_note,
        encounter_id="ENC-77",
        patient=patient,
        provider=provider,
    )
    tx_rendered = render(tx_msg)
    assert "\n" not in tx_rendered and "\r" in tx_rendered, "must be CR-terminated"
    assert tx_rendered.startswith("MSH|^~\\&|"), "MSH header malformed"

    tx_parsed = parse(tx_rendered)
    assert tx_parsed["MSH"][9] == tx_msg.message_control_id, "control id round-trip"
    assert tx_parsed["MSH"][1] == ENCODING_CHARS, "encoding chars round-trip"
    assert tx_parsed["PID"][5].split(COMP_SEP)[0] == "O'Brien", "name unescape"
    # MRN with an embedded "|" must survive escaping + parsing intact.
    assert tx_parsed["PID"][3].split(COMP_SEP)[0] == "MRN|0042", "MRN escape round-trip"
    assert "PV1" in tx_parsed, "PV1 emitted when encounter id present"

    tx_extracted = extract_document_text(tx_rendered)
    assert tx_extracted == tx_note, f"TX body mismatch: {tx_extracted!r}"

    # TXA-17 <-> OBX-11 pairing for a final (DO) document.
    txa17 = tx_parsed["TXA"][17]
    obx11 = tx_parsed["OBX"][0][11]
    assert txa17 == "DO" and obx11 == "F", f"TXA17/OBX11 pairing: {txa17}/{obx11}"
    results["tx_mode"] = True

    # --- ED / PDF mode ---------------------------------------------------
    pdf_bytes = b"%PDF-1.4 fake solace pdf body"
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    ed_msg = MdmMessage(
        pdf_base64=pdf_b64,
        document_status="IP",      # in progress -> OBX-11 == P
        patient=patient,
        provider=provider,
    )
    ed_rendered = render(ed_msg)
    ed_parsed = parse(ed_rendered)
    assert "PV1" not in ed_parsed, "PV1 omitted when no encounter id"
    assert len(ed_parsed["OBX"]) == 1, "ED mode emits exactly one OBX"
    assert ed_parsed["OBX"][0][2] == "ED", "ED OBX value type"

    ed_extracted = extract_document_text(ed_rendered)
    assert ed_extracted == pdf_b64, "ED body base64 mismatch"
    assert base64.b64decode(ed_extracted) == pdf_bytes, "PDF bytes round-trip"

    ed_txa17 = ed_parsed["TXA"][17]
    ed_obx11 = ed_parsed["OBX"][0][11]
    assert ed_txa17 == "IP" and ed_obx11 == "P", "in-progress TXA17/OBX11 pairing"
    results["ed_mode"] = True

    # --- ACK round-trip --------------------------------------------------
    ack_ok = build_ack(tx_rendered, ack_code=_ACK_OK, text_message="filed")
    parsed_ok = parse_ack(ack_ok)
    assert parsed_ok["accepted"] is True, "AA ACK should be accepted"
    assert parsed_ok["control_id"] == tx_msg.message_control_id, "ACK echoes control id"

    ack_err = build_ack(tx_rendered, ack_code=_ACK_ERROR, error_text="bad PID")
    parsed_err = parse_ack(ack_err)
    assert parsed_err["accepted"] is False, "AE ACK should not be accepted"
    assert "bad PID" in parsed_err["error"], "ACK error text round-trip"
    results["ack_mode"] = True

    # --- control id length ----------------------------------------------
    assert len(tx_msg.message_control_id) == _CONTROL_ID_LEN, "control id length"
    results["control_id_length"] = True

    results["ok"] = all(v is True for k, v in results.items() if k != "ok")
    return results


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    logging.basicConfig(level=logging.INFO)
    outcome = self_check()
    print("self_check:", outcome)

    demo = MdmMessage(
        note_text="Patient seen for follow-up.\nNo acute distress.",
        encounter_id="ENC-DEMO-1",
        patient=Patient(
            mrn="A100245", family_name="Doe", given_name="Jane",
            dob="19850321", sex="F", address="1 Health Way",
        ),
        provider=Provider(npi="1234567890", family_name="Smith", given_name="Alex"),
    )
    print("--- sample MDM^T02 ---")
    print(render(demo).replace("\r", "\n"))
