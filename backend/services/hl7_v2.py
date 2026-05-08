"""HL7 v2 MDM^T02 (medical document) emitter.

Routes Solace-authored notes into the long tail of EHRs (Meditech Magic /
Expanse legacy, NextGen, eClinicalWorks, Allscripts/Veradigm, OpenEMR HL7,
OSCAR, community hospitals) via the integration engines they actually deploy:
Mirth Connect, Rhapsody, Corepoint, Cloverleaf.

Output is a fully-formed HL7 v2.5.1 MDM^T02 message ready to ship over MLLP
(Minimal Lower Layer Protocol — STX + payload + ETX + CR). The MLLP framing
helper sends the message; production callers will queue the framed message to
their Mirth channel via a TCP socket.

We also support a `to_pipe_string()` helper for any caller that wants the bare
HL7 string for logging or queuing into a different transport.
"""
from __future__ import annotations

import logging
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

VT = b"\x0b"   # MLLP start
FS = b"\x1c"   # MLLP end
CR = b"\x0d"


def _ts(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S")


def _esc(s: str) -> str:
    """HL7 v2 escape sequences. Order matters."""
    if s is None:
        return ""
    s = str(s)
    return (
        s.replace("\\", "\\E\\")
         .replace("|", "\\F\\")
         .replace("^", "\\S\\")
         .replace("&", "\\T\\")
         .replace("~", "\\R\\")
    )


@dataclass
class Patient:
    mrn: str
    family_name: str
    given_name: str
    dob: str  # YYYYMMDD
    sex: str  # M | F | O | U
    address: str = ""


@dataclass
class Provider:
    npi: str
    family_name: str
    given_name: str
    role_code: str = "RP"  # responsible party


@dataclass
class MdmMessage:
    sending_app: str = "SOLACE"
    sending_facility: str = "SOLACE_HUB"
    receiving_app: str = "EHR"
    receiving_facility: str = "HOSPITAL"
    message_control_id: str = field(default_factory=lambda: uuid.uuid4().hex[:18])
    note_text: str = ""
    note_type_code: str = "PROG"        # Progress note default
    note_type_display: str = "Progress note"
    document_status: str = "DO"         # Documented (final)
    encounter_id: str = ""
    patient: Patient | None = None
    provider: Provider | None = None
    visit_class: str = "O"              # O outpatient, I inpatient, E ED


def render(msg: MdmMessage) -> str:
    """Build the HL7 pipe-delimited message string. Final separator is CR."""
    if msg.patient is None:
        raise ValueError("MdmMessage requires a patient")
    if msg.provider is None:
        raise ValueError("MdmMessage requires a provider")
    p = msg.patient
    pr = msg.provider
    now = _ts()

    msh = (
        f"MSH|^~\\&|{_esc(msg.sending_app)}|{_esc(msg.sending_facility)}|"
        f"{_esc(msg.receiving_app)}|{_esc(msg.receiving_facility)}|{now}||"
        f"MDM^T02|{_esc(msg.message_control_id)}|P|2.5.1"
    )
    evn = f"EVN|T02|{now}"
    pid = (
        "PID|1||"
        f"{_esc(p.mrn)}^^^{_esc(msg.receiving_facility)}^MR||"
        f"{_esc(p.family_name)}^{_esc(p.given_name)}||"
        f"{_esc(p.dob)}|{_esc(p.sex)}|||"
        f"{_esc(p.address)}"
    )
    pv1 = (
        f"PV1|1|{_esc(msg.visit_class)}|||||"
        f"{_esc(pr.npi)}^{_esc(pr.family_name)}^{_esc(pr.given_name)}|||||||||||"
        f"|||||||||||||||||||||||||||||||"
        f"{_esc(msg.encounter_id)}"
    )
    txa = (
        f"TXA|1|{_esc(msg.note_type_code)}^{_esc(msg.note_type_display)}|TX|{now}|"
        f"{_esc(pr.npi)}^{_esc(pr.family_name)}^{_esc(pr.given_name)}|"
        f"{now}||||||||||{_esc(msg.document_status)}"
    )
    obx_lines = []
    for i, line in enumerate((msg.note_text or "").split("\n"), start=1):
        obx_lines.append(f"OBX|{i}|TX|{i:04d}^Note line||{_esc(line)}")
    return "\r".join([msh, evn, pid, pv1, txa, *obx_lines])


def to_mllp_frame(message: str) -> bytes:
    return VT + message.encode("utf-8") + FS + CR


def send_mllp(host: str, port: int, message: str, *, timeout: float = 10.0) -> dict[str, Any]:
    """Open a TCP connection to the Mirth/Rhapsody/Corepoint listener and write the framed message.

    Returns a dict with `ack_type` (AA / AE / AR) parsed from the inbound MSA segment.
    Use a feature flag to gate; production callers also wrap this in a retry queue.
    """
    framed = to_mllp_frame(message)
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.sendall(framed)
            sock.settimeout(timeout)
            chunks = []
            while True:
                buf = sock.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
                if FS in buf:
                    break
            raw = b"".join(chunks)
        body = raw.strip(VT + FS + CR).decode("utf-8", errors="replace")
        # MSA|AA|<control id>|...
        ack_type = "AE"
        for line in body.split("\r"):
            if line.startswith("MSA|"):
                parts = line.split("|")
                if len(parts) >= 2:
                    ack_type = parts[1]
                break
        return {"sent": True, "ack_type": ack_type, "raw_ack": body[:500]}
    except Exception as e:
        log.warning("MLLP send failed: %s", e)
        return {"sent": False, "error": str(e)}


def build_and_send_demo(*, host: str, port: int, mrn: str, note_text: str) -> dict[str, Any]:
    msg = MdmMessage(
        note_text=note_text,
        encounter_id=uuid.uuid4().hex[:10],
        patient=Patient(mrn=mrn, family_name="DOE", given_name="JANE", dob="19850321", sex="F"),
        provider=Provider(npi="1234567890", family_name="SMITH", given_name="ALEX"),
    )
    s = render(msg)
    result = send_mllp(host, port, s)
    return {"message": s, "result": result}
