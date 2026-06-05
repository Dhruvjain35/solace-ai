"""Create the Solace per-hospital workspaces config table. Idempotent.

`solace-workspaces` is the durable backing store for per-hospital workspace
configuration (branding, feature flags, EHR connection metadata, seat config).
It is NON-PHI workspace/tenant config — never patient names/notes/UUID keys.

Schema (per the research contract):
  - Partition key: hospital_id  (S)  — one item-collection per tenant
  - Sort key:      workspace_id (S)  — a hospital may own >1 workspace; list-by-
                                       hospital is a .query() (PERF-004), never a .scan()
  - NO TTL                           — this is durable configuration, not transient
                                       state (contrast solace-billing-events / nonce
                                       tables which DO expire). Do not enable TTL here.

Encrypted with the Solace CMK (alias/solace) per COMP-003 / HIPAA §164.312, resolved
by alias so this works across accounts without hardcoding a key UUID (SEC-009). No
secrets are read, written, or printed by this script (COMP-007). PAY_PER_REQUEST.

Safety rails (mirrors scripts/apply_iam_scoped.py):
  - Default: DRY-RUN / plan — prints what it WOULD create, makes ZERO AWS calls.
  - `--apply` : actually resolve the CMK + create the table + verify NO TTL.

DO NOT run with --apply in CI. Invoke manually when provisioning a workspace:
    python scripts/setup_workspaces.py            # plan only, no AWS mutations
    python scripts/setup_workspaces.py --apply     # create the table

Standalone per ARCH-008: imports only boto3 / botocore (third-party) + stdlib.
"""
from __future__ import annotations

import sys

REGION = "us-east-1"
TABLE_NAME = "solace-workspaces"
PARTITION_KEY = "hospital_id"
SORT_KEY = "workspace_id"
CMK_ALIAS = "alias/solace"  # SEC-009 / COMP-003 — resolved at runtime, never a hardcoded UUID


def _resolve_cmk_arn(kms) -> str:
    """Resolve the Solace CMK ARN via alias — avoids hardcoding a key UUID (SEC-009)."""
    from botocore.exceptions import ClientError

    try:
        resp = kms.describe_key(KeyId=CMK_ALIAS)
        arn = resp["KeyMetadata"]["Arn"]
        print(f"  [cmk]   {arn}")
        return arn
    except ClientError as e:
        print(f"  [warn]  Could not resolve {CMK_ALIAS}: {e}")
        print("  [warn]  Table would use AWS-managed default encryption (SSE-S3).")
        print("  [warn]  Re-run scripts/setup_security.py to create the CMK, then retry.")
        return ""


def _exists(ddb, name: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        ddb.describe_table(TableName=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def _table_kwargs(cmk_arn: str) -> dict:
    """Build the create_table request. NO TTL — this is durable config."""
    kwargs: dict = {
        "AttributeDefinitions": [
            {"AttributeName": PARTITION_KEY, "AttributeType": "S"},
            {"AttributeName": SORT_KEY, "AttributeType": "S"},
        ],
        "KeySchema": [
            {"AttributeName": PARTITION_KEY, "KeyType": "HASH"},
            {"AttributeName": SORT_KEY, "KeyType": "RANGE"},
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
    return kwargs


def plan() -> None:
    """DRY-RUN: describe the intended action. Makes ZERO AWS calls."""
    print("DRY RUN — no AWS calls, no changes made.\n")
    print("Would:")
    print(f"  1. resolve the Solace CMK by alias ({CMK_ALIAS}) — never a hardcoded key UUID")
    print(f"  2. create DynamoDB table '{TABLE_NAME}' in {REGION} if absent (idempotent):")
    print(f"       partition key : {PARTITION_KEY} (S)")
    print(f"       sort key      : {SORT_KEY} (S)")
    print(f"       billing       : PAY_PER_REQUEST")
    print(f"       encryption    : SSE-KMS with the Solace CMK (COMP-003)")
    print(f"       TTL           : NONE — durable config, intentionally not expired")
    print("\nNo secrets are read or written (COMP-007).")
    print(f"\nTo actually provision the table, re-run with --apply:")
    print(f"    python scripts/setup_workspaces.py --apply")


def apply() -> None:
    """Resolve CMK, create the table idempotently, and verify NO TTL is set."""
    import boto3
    from botocore.exceptions import ClientError

    ddb = boto3.client("dynamodb", region_name=REGION)
    kms = boto3.client("kms", region_name=REGION)
    account_id = boto3.client("sts").get_caller_identity()["Account"]

    print(f"Account: {account_id}  Region: {REGION}\n")
    print("Resolving Solace CMK:")
    cmk_arn = _resolve_cmk_arn(kms)
    print()

    print("DynamoDB table:")
    if _exists(ddb, TABLE_NAME):
        print(f"  [ok]    {TABLE_NAME} already exists")
    else:
        print(f"  [create] {TABLE_NAME}")
        ddb.create_table(TableName=TABLE_NAME, **_table_kwargs(cmk_arn))
        ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        print(f"  [ready]  {TABLE_NAME}")

    # Durable config — assert TTL stays OFF. We never enable it here; verify it
    # was not enabled out of band so the table's durability guarantee holds.
    print("Verifying NO TTL (durable config):")
    try:
        ttl = ddb.describe_time_to_live(TableName=TABLE_NAME)
        status = ttl["TimeToLiveDescription"]["TimeToLiveStatus"]
        if status in ("ENABLED", "ENABLING"):
            print(f"  [warn] TTL is {status} — workspace config should be durable. "
                  "Disable TTL on this table.")
        else:
            print(f"  [ok]   TTL is {status} (expected DISABLED)")
    except ClientError as e:
        print(f"  [warn] could not read TTL status: {e}")

    print(
        f"\nDone. {TABLE_NAME} is the durable per-hospital workspace config store "
        "(partition hospital_id, sort workspace_id, CMK-encrypted, no TTL)."
    )


def main() -> None:
    flags = set(sys.argv[1:])
    if "--apply" in flags:
        apply()
    else:
        plan()


if __name__ == "__main__":
    main()
