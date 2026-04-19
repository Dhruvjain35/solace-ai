"""Rotate clinician PINs — run manually or from an EventBridge schedule.

Behavior:
  - Generate new 12-char PINs for every clinician in `solace-clinicians`.
  - bcrypt-hash into DDB (replaces old `pin_hash`).
  - Update `DEMO_CLINICIANS` plaintext map in `solace/clinician-auth` Secrets Manager
    entry so Dr. Chen / Patel / Kim still know their new PINs (demo convenience).
  - Publish the new PINs to the SNS topic `solace-security-alerts` so the human
    who confirmed the subscription gets them by email.
  - Existing JWTs remain valid until expiry (30 min default) — no forced logout.

Run manually: `python scripts/rotate_pins.py --apply`
Schedule: use `scripts/schedule_pin_rotation.py` to create an EventBridge rule.
"""
from __future__ import annotations

import json
import secrets
import string
import sys
from datetime import datetime, timezone

import boto3

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:solace-security-alerts"
SECRET_NAME = "solace/clinician-auth"

ddb = boto3.resource("dynamodb", region_name=REGION)
sm = boto3.client("secretsmanager", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)


def _new_pin() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _bcrypt(plain: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=10)).decode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rotate(apply: bool = False) -> dict[str, str]:
    clinicians_table = ddb.Table("solace-clinicians")
    rows = clinicians_table.scan().get("Items", [])

    new_pins: dict[str, str] = {}
    for c in rows:
        new_pins[c["name"]] = _new_pin()

    if not apply:
        print("DRY RUN — pass --apply to commit")
        for name, pin in new_pins.items():
            print(f"  would rotate {name} → {pin}")
        return new_pins

    for c in rows:
        name = c["name"]
        plain = new_pins[name]
        clinicians_table.update_item(
            Key={"clinician_id": c["clinician_id"]},
            UpdateExpression="SET pin_hash = :h, rotated_at = :t",
            ExpressionAttributeValues={":h": _bcrypt(plain), ":t": _now()},
        )
        print(f"  [ok]  DDB pin_hash rotated for {name}")

    # Update Secrets Manager plaintext map
    current = json.loads(sm.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
    current["DEMO_CLINICIANS"] = new_pins
    current["LAST_ROTATED_AT"] = _now()
    sm.update_secret(SecretId=SECRET_NAME, SecretString=json.dumps(current))
    print("  [ok]  Secrets Manager updated")

    # Publish via SNS so the human(s) on the topic get the new PINs
    body_lines = [f"Solace clinician PINs rotated at {_now()}", ""]
    for name, pin in new_pins.items():
        body_lines.append(f"  {name}: {pin}")
    body_lines.append("")
    body_lines.append("Old PINs no longer work. Existing 30-min JWT sessions remain valid.")
    sns.publish(
        TopicArn=TOPIC_ARN,
        Subject="Solace: clinician PINs rotated",
        Message="\n".join(body_lines),
    )
    print(f"  [ok]  SNS published to {TOPIC_ARN}")
    return new_pins


def main() -> None:
    apply = "--apply" in sys.argv
    rotate(apply=apply)


if __name__ == "__main__":
    main()
