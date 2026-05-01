"""Create the two DynamoDB tables the voice agent needs.

  * solace-calls         — per-call session state (transcript, intent, escalation)
                           PAY_PER_REQUEST, CMK-encrypted, 90-day TTL
  * solace-appointments  — voice-booked appointments
                           PAY_PER_REQUEST, CMK-encrypted, 30-day TTL

Idempotent: re-runs are safe.
"""
from __future__ import annotations

import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ddb = boto3.client("dynamodb", region_name=REGION)
kms = boto3.client("kms", region_name=REGION)


def _cmk_arn() -> str | None:
    """Look up the Solace CMK created by setup_security.py. Falls back to the AWS-managed
    DDB key if not found (still encrypted, just not customer-managed)."""
    try:
        for alias in kms.list_aliases()["Aliases"]:
            if alias["AliasName"] == "alias/solace-cmk":
                return alias["TargetKeyId"]
    except Exception:
        pass
    return None


def _wait_active(name: str) -> None:
    while True:
        s = ddb.describe_table(TableName=name)["Table"]["TableStatus"]
        if s == "ACTIVE":
            return
        time.sleep(1)


def ensure_calls_table(cmk: str | None) -> None:
    name = "solace-calls"
    try:
        ddb.describe_table(TableName=name)
        print(f"  [ok]    {name} exists")
        # Make sure TTL is on and the GSI is present.
        try:
            ddb.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
            )
        except ClientError as e:
            if "TimeToLive is already enabled" not in str(e):
                raise
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    print(f"  [create] {name}")
    args: dict = {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": "call_id",     "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "started_at",  "AttributeType": "S"},
        ],
        "KeySchema": [{"AttributeName": "call_id", "KeyType": "HASH"}],
        "GlobalSecondaryIndexes": [{
            "IndexName": "hospital_id-started_at-index",
            "KeySchema": [
                {"AttributeName": "hospital_id", "KeyType": "HASH"},
                {"AttributeName": "started_at",  "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }],
        "Tags": [{"Key": "project", "Value": "solace"}],
    }
    if cmk:
        args["SSESpecification"] = {"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": cmk}
    ddb.create_table(**args)
    _wait_active(name)
    ddb.update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )
    ddb.update_continuous_backups(
        TableName=name,
        PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
    )


def ensure_appointments_table(cmk: str | None) -> None:
    name = "solace-appointments"
    try:
        ddb.describe_table(TableName=name)
        print(f"  [ok]    {name} exists")
        try:
            ddb.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
            )
        except ClientError as e:
            if "TimeToLive is already enabled" not in str(e):
                raise
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    print(f"  [create] {name}")
    args: dict = {
        "TableName": name,
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": "appointment_id",    "AttributeType": "S"},
            {"AttributeName": "hospital_id",       "AttributeType": "S"},
            {"AttributeName": "created_at",        "AttributeType": "S"},
            {"AttributeName": "confirmation_code", "AttributeType": "S"},
        ],
        "KeySchema": [{"AttributeName": "appointment_id", "KeyType": "HASH"}],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": "hospital_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at",  "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "confirmation_code-index",
                "KeySchema": [{"AttributeName": "confirmation_code", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        "Tags": [{"Key": "project", "Value": "solace"}],
    }
    if cmk:
        args["SSESpecification"] = {"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": cmk}
    ddb.create_table(**args)
    _wait_active(name)
    ddb.update_time_to_live(
        TableName=name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )


def main() -> None:
    cmk = _cmk_arn()
    if cmk:
        print(f"Using CMK alias/solace-cmk → {cmk}")
    else:
        print("CMK not found — falling back to AWS-managed DDB encryption.")
    print("DynamoDB tables (voice agent):")
    ensure_calls_table(cmk)
    ensure_appointments_table(cmk)
    print("\nDone.")


if __name__ == "__main__":
    main()
