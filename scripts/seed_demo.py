"""Seed the local storage with demo patients using REAL Claude + ElevenLabs calls.

Usage:
    cd ~/solace/backend && source .venv/bin/activate
    python ../scripts/seed_demo.py

Creates 5 patients — one per ESI level — so the clinician dashboard has something to show.
One patient has pain_flagged=true. Run AFTER uvicorn is up OR run against an in-process
import (this script uses the in-process storage, so run with the same Python interpreter
as uvicorn and they'll share memory — i.e. run inside `uvicorn --reload` won't work for
seeding. For local demos, call the /intake endpoint instead via curl or the test harness.)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Let this script run from repo root: `python scripts/seed_demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

DEMO_TRANSCRIPTS: list[tuple[str, dict]] = [
    (
        "Marcus",
        {
            "transcript": (
                "I'm having really bad chest pain. It started about two hours ago and radiates into my left jaw. "
                "I'm a 38 year old man and I don't have any history of heart problems. I'm having shortness of breath and sweating. "
                "Pain is maybe 7 out of 10."
            ),
            "medical_info": {
                "age": 38, "sex": "male", "pregnant": None,
                "allergies": ["None"], "medications": ["None"],
                "conditions": ["Hypertension"],
            },
        },
    ),
    (
        "Elena",
        {
            "transcript": (
                "I have a severe bleeding laceration on my hand from chopping vegetables an hour ago. "
                "There's a lot of bleeding even with pressure. I feel a bit dizzy. I'm 42 and I don't take blood thinners. "
                "Pain is 6 out of 10."
            ),
            "medical_info": {
                "age": 42, "sex": "female", "pregnant": False,
                "allergies": ["None"], "medications": ["None"], "conditions": ["None"],
            },
        },
    ),
    (
        "Priya",
        {
            "transcript": (
                "I have a severe headache with vomiting for two days. Light makes it worse. "
                "I'm 34. I have a history of migraines but this one is different, more intense. Pain is 8 out of 10."
            ),
            "medical_info": {
                "age": 34, "sex": "female", "pregnant": False,
                "allergies": ["Penicillin"], "medications": ["None"], "conditions": ["None"],
            },
        },
    ),
    (
        "James",
        {
            "transcript": (
                "I have a sprain on my ankle from basketball yesterday. It's swollen and bruised. "
                "I can walk on it. Pain is maybe 4 out of 10. I'm 29 and otherwise healthy."
            ),
            "medical_info": {
                "age": 29, "sex": "male", "pregnant": None,
                "allergies": ["None"], "medications": ["None"], "conditions": ["None"],
            },
        },
    ),
    (
        "Sofia",
        {
            "transcript": (
                "I need a medication refill. I'm 26 and otherwise feeling fine — no pain."
            ),
            "medical_info": {
                "age": 26, "sex": "female", "pregnant": False,
                "allergies": ["None"], "medications": ["Birth control"], "conditions": ["None"],
            },
        },
    ),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--hospital-id", default="demo")
    parser.add_argument("--flag-pain-on", type=int, default=2, help="Index (0-based) of patient to pain-flag")
    args = parser.parse_args()

    import json as _json

    created: list[dict] = []
    with httpx.Client(timeout=120) as client:
        for name, payload in DEMO_TRANSCRIPTS:
            transcript = payload["transcript"]
            print(f"[seed] {name}: {transcript[:60]}...")
            form = {
                "patient_name": name,
                "pre_transcribed_text": transcript,
                "medical_info": _json.dumps(payload["medical_info"]),
            }
            resp = client.post(f"{args.url}/api/{args.hospital_id}/intake", data=form)
            if resp.status_code != 200:
                print(f"  FAIL {resp.status_code}: {resp.text[:200]}")
                continue
            data = resp.json()
            print(f"  → ESI {data['esi_level']} ({data['esi_label']})")
            created.append(data)

        if args.flag_pain_on is not None and 0 <= args.flag_pain_on < len(created):
            target = created[args.flag_pain_on]
            resp = client.post(
                f"{args.url}/api/{args.hospital_id}/pain-flag",
                json={"patient_id": target["patient_id"]},
            )
            print(f"[seed] flagged pain on {DEMO_TRANSCRIPTS[args.flag_pain_on][0]}: {resp.status_code}")

    print(f"[seed] created {len(created)} patients. Open http://localhost:5173/{args.hospital_id}/clinician")


if __name__ == "__main__":
    main()
