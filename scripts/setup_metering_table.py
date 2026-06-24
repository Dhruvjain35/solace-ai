"""Create the Solace usage-metering / billing-events table. Idempotent.

`solace-billing-events` is the durable backing store for backend/lib/metering.py —
it records ONE NON-PHI billable event per triage encounter so aggregate usage and
an estimated-value figure survive Lambda cold starts and aren't fragmented across
warm containers.

Schema:
  - Partition key: hospital_id (S)   — scopes reads to one workspace
  - Sort key:      ts_id (S)         — "{epoch_ms}#{uuid}", so list-by-hospital is a
                                       .query() (newest-first), never a .scan() (PERF-004)
  - TTL attribute: ttl               — ~18-month hot retention in DDB (billing/usage
                                       history is referenced across quarterly reviews)

Events are NON-PHI: hospital_id, encounter_type, model_source, billable, an optional
CPT hint, an opaque event id, and a timestamp — never patient names/notes/UUID keys.

Encrypted with the Solace CMK (alias/solace) per COMP-003 / HIPAA §164.312, resolved by
alias so this works across accounts without hardcoding a key UUID. PAY_PER_REQUEST.

DO NOT run against AWS as part of CI — invoke manually when provisioning a workspace:
    python scripts/setup_metering_table.py
"""
from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
TABLE_NAME = "solace-billing-events"
TTL_ATTRIBUTE = "ttl"

ddb = boto3.client("dynamodb", region_name=REGION)
kms = boto3.client("kms", region_name=REGION)


def _resolve_cmk_arn() -> str:
    """Resolve the Solace CMK ARN via alias — avoids hardcoding a key UUID."""
    try:
        resp = kms.describe_key(KeyId="alias/solace")
        arn = resp["KeyMetadata"]["Arn"]
        print(f"  [cmk]   {arn}")
        return arn
    except ClientError as e:
        print(f"  [warn]  Could not resolve alias/solace: {e}")
        print("  [warn]  Table will use AWS-managed default encryption (SSE-S3).")
        return ""


def _exists(name: str) -> bool:
    try:
        ddb.describe_table(TableName=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def setup_table(cmk_arn: str) -> None:
    print("DynamoDB table:")
    if _exists(TABLE_NAME):
        print(f"  [ok]    {TABLE_NAME} already exists")
    else:
        print(f"  [create] {TABLE_NAME}")
        kwargs: dict = {
            "AttributeDefinitions": [
                {"AttributeName": "hospital_id", "AttributeType": "S"},
                {"AttributeName": "ts_id", "AttributeType": "S"},
            ],
            "KeySchema": [
                {"AttributeName": "hospital_id", "KeyType": "HASH"},
                {"AttributeName": "ts_id", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        }
        # COMP-003 / HIPAA §164.312 — encrypt with the Solace CMK when available.
        if cmk_arn:
            kwargs["SSESpecification"] = {
                "Enabled": True,
                "SSEType": "KMS",
                "KMSMasterKeyId": cmk_arn,
            }
        ddb.create_table(TableName=TABLE_NAME, **kwargs)
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        print(f"  [ready]  {TABLE_NAME}")

    print("Enabling TTL:")
    try:
        ddb.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
        )
        print(f"  [ok] {TABLE_NAME}.{TTL_ATTRIBUTE}")
    except ClientError as e:
        if "TimeToLive is already enabled" in str(e):
            print(f"  [ok] {TABLE_NAME} TTL already enabled")
        else:
            print(f"  [warn] {e}")


def main() -> None:
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    print(f"Account: {account_id}  Region: {REGION}\n")
    print("Resolving Solace CMK:")
    cmk_arn = _resolve_cmk_arn()
    print()
    setup_table(cmk_arn)
    print(
        "\nDone. solace-billing-events is the durable store for lib.metering "
        "(per-encounter usage metering + ROI/billing panel)."
    )


if __name__ == "__main__":
    main()
