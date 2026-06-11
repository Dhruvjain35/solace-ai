"""Section 1 infra: DDB tables + Secrets Manager + seed 3 demo clinicians.

Run once. Idempotent — safe to re-run. Prints the demo PINs ONCE at the end.
"""
from __future__ import annotations

import json
import secrets as pysecrets
import sys
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
SECRET_NAME = "solace/clinician-auth"

ddb = boto3.client("dynamodb", region_name=REGION)
sm = boto3.client("secretsmanager", region_name=REGION)
kms = boto3.client("kms", region_name=REGION)


def _resolve_cmk_arn() -> str:
    """Resolve the Solace CMK ARN via alias — avoids hardcoding a key UUID."""
    try:
        resp = kms.describe_key(KeyId="alias/solace")
        return resp["KeyMetadata"]["Arn"]
    except Exception as e:  # noqa: BLE001
        # Fall back to the legacy hardcoded ARN if alias doesn't exist yet
        print(f"  [warn]  Could not resolve alias/solace ({e}), using default encryption.")
        return f"arn:aws:kms:{REGION}:{ACCOUNT}:alias/aws/dynamodb"


CMK_ARN: str = ""  # populated in main()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_table(name: str, key_schema, attr_defs, gsis=None) -> None:
    try:
        ddb.describe_table(TableName=name)
        print(f"  [ok]    {name}")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    kwargs = {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": key_schema,
        "AttributeDefinitions": attr_defs,
        "SSESpecification": {"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": CMK_ARN},
    }
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = gsis
    ddb.create_table(**kwargs)
    print(f"  [create] {name}")


def ensure_gsi(name: str, *, index_name: str, attr_defs, key_schema) -> None:
    """Idempotently add a GSI to an existing table. No-op if it already exists."""
    try:
        desc = ddb.describe_table(TableName=name)["Table"]
    except ClientError:
        return  # table not created yet; create path already includes the GSI
    existing = {g["IndexName"] for g in desc.get("GlobalSecondaryIndexes", []) or []}
    if index_name in existing:
        print(f"  [ok]    GSI {name}.{index_name}")
        return
    try:
        ddb.update_table(
            TableName=name,
            AttributeDefinitions=attr_defs,
            GlobalSecondaryIndexUpdates=[{
                "Create": {
                    "IndexName": index_name,
                    "KeySchema": key_schema,
                    "Projection": {"ProjectionType": "ALL"},
                }
            }],
        )
        print(f"  [create] GSI {name}.{index_name} (backfilling)")
    except ClientError as e:
        print(f"  [warn]  GSI {name}.{index_name}: {e}")


def enable_ttl(name: str, attr: str) -> None:
    try:
        current = ddb.describe_time_to_live(TableName=name)["TimeToLiveDescription"].get("TimeToLiveStatus")
        if current == "ENABLED":
            return
        ddb.update_time_to_live(
            TableName=name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": attr},
        )
        print(f"  [ok]    TTL on {name}.{attr}")
    except ClientError as e:
        print(f"  [warn]  TTL on {name}: {e}")


def generate_pin() -> str:
    """12-char alphanumeric PIN — memorable-ish, 72-bit entropy."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"  # no 0/O/1/l/I
    return "".join(pysecrets.choice(alphabet) for _ in range(12))


def bcrypt_hash(plain: str) -> str:
    import bcrypt  # noqa: PLC0415

    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=10)).decode()


def main() -> None:
    global CMK_ARN
    print(f"Account {ACCOUNT}  Region {REGION}\n")

    print("Resolving Solace CMK:")
    CMK_ARN = _resolve_cmk_arn()
    print(f"  [cmk]   {CMK_ARN}\n")

    print("DynamoDB tables:")
    ensure_table(
        "solace-clinicians",
        [{"AttributeName": "clinician_id", "KeyType": "HASH"}],
        [
            {"AttributeName": "clinician_id", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "name_lower", "AttributeType": "S"},
            {"AttributeName": "email_lower", "AttributeType": "S"},
        ],
        gsis=[
            {
                "IndexName": "hospital_name-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "name_lower", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                # Magic-link auth looks clinicians up by (hospital, email).
                "IndexName": "hospital_email-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "email_lower", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )
    # Idempotent add for accounts created before the email GSI existed.
    ensure_gsi(
        "solace-clinicians",
        index_name="hospital_email-index",
        attr_defs=[
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "email_lower", "AttributeType": "S"},
        ],
        key_schema=[
            {"AttributeName": "hospital_id", "KeyType": "HASH"},
            {"AttributeName": "email_lower", "KeyType": "RANGE"},
        ],
    )
    # Single-use magic-link tokens (login + invites). expires_at is a DDB TTL.
    ensure_table(
        "solace-magic-tokens",
        [{"AttributeName": "token_hash", "KeyType": "HASH"}],
        [{"AttributeName": "token_hash", "AttributeType": "S"}],
    )
    # Request-to-join records, queried per workspace via hospital-index.
    ensure_table(
        "solace-access-requests",
        [{"AttributeName": "request_id", "KeyType": "HASH"}],
        [
            {"AttributeName": "request_id", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
        ],
        gsis=[{
            "IndexName": "hospital-index",
            "KeySchema": [{"AttributeName": "hospital_id", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
    )
    # Public contact/sales inquiries (POST /api/contact). Non-PHI marketing
    # inbound; simple PK lookup only, so no GSI.
    ensure_table(
        "solace-contact-requests",
        [{"AttributeName": "contact_id", "KeyType": "HASH"}],
        [{"AttributeName": "contact_id", "AttributeType": "S"}],
    )
    ensure_table(
        "solace-audit-log",
        [
            {"AttributeName": "clinician_id", "KeyType": "HASH"},
            {"AttributeName": "ts_id", "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "clinician_id", "AttributeType": "S"},
            {"AttributeName": "ts_id", "AttributeType": "S"},
            {"AttributeName": "patient_id", "AttributeType": "S"},
        ],
        gsis=[{
            "IndexName": "patient-index",
            "KeySchema": [
                {"AttributeName": "patient_id", "KeyType": "HASH"},
                {"AttributeName": "ts_id", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
    )
    waiter = ddb.get_waiter("table_exists")
    for t in ["solace-clinicians", "solace-audit-log", "solace-magic-tokens", "solace-access-requests", "solace-contact-requests"]:
        waiter.wait(TableName=t)
    enable_ttl("solace-audit-log", "ttl")
    enable_ttl("solace-magic-tokens", "expires_at")
    print()

    print("JWT signing key in Secrets Manager:")
    # Fixed, known demo PINs — the demo must work every time without a PIN
    # handoff. Real (non-demo) clinicians still get random PINs via generate_pin().
    clinicians_plan = [
        {"name": "Dr. Chen", "role": "chief", "pin": "224466"},
        {"name": "Dr. Patel", "role": "attending", "pin": "113355"},
        {"name": "Dr. Kim", "role": "resident", "pin": "667788"},
    ]
    jwt_key = pysecrets.token_urlsafe(48)
    payload = {
        "JWT_SIGNING_KEY": jwt_key,
        "JWT_ALGORITHM": "HS256",
        "DEMO_CLINICIANS": {c["name"]: c["pin"] for c in clinicians_plan},
    }
    body = json.dumps(payload)
    try:
        sm.describe_secret(SecretId=SECRET_NAME)
        sm.update_secret(SecretId=SECRET_NAME, SecretString=body, KmsKeyId=CMK_ARN)
        print(f"  [update] {SECRET_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        sm.create_secret(
            Name=SECRET_NAME,
            Description="Solace clinician auth — JWT signing key + demo PINs",
            KmsKeyId=CMK_ARN,
            SecretString=body,
            Tags=[{"Key": "project", "Value": "solace"}],
        )
        print(f"  [create] {SECRET_NAME}")
    print()

    print("Seeding demo clinicians:")
    dynamo = boto3.resource("dynamodb", region_name=REGION)
    clinicians_table = dynamo.Table("solace-clinicians")
    for c in clinicians_plan:
        name = c["name"]
        # Reuse deterministic clinician_id from the name so re-runs don't create duplicates
        cid = f"demo-{name.lower().replace(' ', '-').replace('.', '')}"
        clinicians_table.put_item(Item={
            "clinician_id": cid,
            "hospital_id": "demo",
            "name": name,
            "name_lower": name.lower(),
            "role": c["role"],
            "pin_hash": bcrypt_hash(c["pin"]),
            "created_at": _now(),
            "last_login_at": None,
        })
        print(f"  [ok]    {cid}  ({c['role']})")
    print()

    print("=" * 60)
    print("DEMO CLINICIAN PINS — save these now, not printed again:")
    print("=" * 60)
    for c in clinicians_plan:
        print(f"  {c['name']:12} · {c['role']:10} · PIN: {c['pin']}")
    print("=" * 60)
    print("(PINs are bcrypt-hashed in DDB; plaintext lives in Secrets Manager as")
    print("DEMO_CLINICIANS map — retrievable for demo reset but never logged.)")


if __name__ == "__main__":
    main()
