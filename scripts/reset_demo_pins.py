"""Reset all demo clinician PINs to '123456' so judges / users can sign in
without copying a 12-character random string. Idempotent — safe to re-run.

Updates two places to keep them in sync:
  - DDB `solace-clinicians`: pin_hash for each row (bcrypt of new PIN)
  - Secrets Manager `solace/clinician-auth`: DEMO_CLINICIANS map
"""
from __future__ import annotations

import json

import bcrypt
import boto3

REGION = "us-east-1"
DEMO_PIN = "123456"


def main() -> None:
    sm = boto3.client("secretsmanager", region_name=REGION)
    ddb = boto3.resource("dynamodb", region_name=REGION).Table("solace-clinicians")

    secret = json.loads(sm.get_secret_value(SecretId="solace/clinician-auth")["SecretString"])
    demo = secret.get("DEMO_CLINICIANS", {})
    if not demo:
        print("no DEMO_CLINICIANS map in secret — nothing to reset")
        return

    new_hash = bcrypt.hashpw(DEMO_PIN.encode(), bcrypt.gensalt(rounds=10)).decode()
    print(f"resetting {len(demo)} clinicians to PIN '{DEMO_PIN}'")

    # 1. Find each clinician row by name and update their pin_hash.
    for name in demo.keys():
        try:
            resp = ddb.query(
                IndexName="hospital_name-index",
                KeyConditionExpression="hospital_id = :h AND name_lower = :n",
                ExpressionAttributeValues={":h": "demo", ":n": name.lower()},
                Limit=1,
            )
            items = resp.get("Items", [])
            if not items:
                print(f"  [warn] clinician '{name}' not found in DDB; skipping")
                continue
            ddb.update_item(
                Key={"clinician_id": items[0]["clinician_id"]},
                UpdateExpression="SET pin_hash = :h",
                ExpressionAttributeValues={":h": new_hash},
            )
            print(f"  [ok]   {name} → PIN {DEMO_PIN}")
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {name}: {e}")

    # 2. Update the secret so reads stay coherent.
    secret["DEMO_CLINICIANS"] = {name: DEMO_PIN for name in demo.keys()}
    sm.update_secret(SecretId="solace/clinician-auth", SecretString=json.dumps(secret))
    print("  [ok]   secret updated")

    print("\nDone. Sign in with any of:", ", ".join(demo.keys()), f"  PIN: {DEMO_PIN}")


if __name__ == "__main__":
    main()
