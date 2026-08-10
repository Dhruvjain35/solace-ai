"""Create Solace DynamoDB tables + S3 media bucket. Idempotent.

All DynamoDB tables are encrypted with the Solace CMK (KMS) per HIPAA §164.312.
The CMK is resolved by alias (`alias/solace`) so the setup script works across
accounts without hardcoding a key UUID.
"""
from __future__ import annotations

import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT_ID = boto3.client("sts").get_caller_identity()["Account"]
BUCKET = f"solace-media-{ACCOUNT_ID}"

ddb = boto3.client("dynamodb", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
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
        print("  [warn]  Tables will use AWS-managed default encryption (SSE-S3).")
        return ""


CMK_ARN: str = ""  # populated in main()


def _exists(name: str) -> bool:
    try:
        ddb.describe_table(TableName=name)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def _create(name: str, **kwargs) -> None:
    if _exists(name):
        print(f"  [ok]    {name} already exists")
        return
    print(f"  [create] {name}")
    # HIPAA §164.312 — encrypt all tables with the Solace CMK when available
    if CMK_ARN and "SSESpecification" not in kwargs:
        kwargs["SSESpecification"] = {
            "Enabled": True,
            "SSEType": "KMS",
            "KMSMasterKeyId": CMK_ARN,
        }
    ddb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", **kwargs)


def _wait(names: list[str]) -> None:
    waiter = ddb.get_waiter("table_exists")
    for n in names:
        waiter.wait(TableName=n)
        print(f"  [ready]  {n}")


def setup_tables() -> None:
    print("DynamoDB tables:")
    _create(
        "solace-patients",
        AttributeDefinitions=[
            {"AttributeName": "patient_id", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "patient_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "hospital_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    _create(
        "solace-hospitals",
        AttributeDefinitions=[{"AttributeName": "hospital_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "hospital_id", "KeyType": "HASH"}],
    )
    _create(
        "solace-prescriptions",
        AttributeDefinitions=[
            {"AttributeName": "patient_id", "AttributeType": "S"},
            {"AttributeName": "prescription_id", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "patient_id", "KeyType": "HASH"},
            {"AttributeName": "prescription_id", "KeyType": "RANGE"},
        ],
    )
    _create(
        "solace-notes",
        AttributeDefinitions=[
            {"AttributeName": "patient_id", "AttributeType": "S"},
            {"AttributeName": "note_id", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "patient_id", "KeyType": "HASH"},
            {"AttributeName": "note_id", "KeyType": "RANGE"},
        ],
    )
    _create(
        "solace-calls",
        AttributeDefinitions=[
            {"AttributeName": "call_id", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "started_at", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "call_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "hospital_id-started_at-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "started_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    _create(
        "solace-appointments",
        AttributeDefinitions=[
            {"AttributeName": "appointment_id", "AttributeType": "S"},
            {"AttributeName": "hospital_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "appointment_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "hospital_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "hospital_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    # The encounter ledger (CONSTITUTION COMP-002, and the spine of the shadow
    # programme). Composite key: one partition per encounter, sequence as the
    # range key so a query returns the chain already in order.
    #
    # Deliberately NO TTL on this table. Every other transient table here gets
    # one; this is the record that has to still be there in six years when
    # somebody asks what the system decided and when.
    #
    # Point-in-time recovery is on below, because the append-only guarantee
    # protects against entries being edited, not against the table being
    # dropped.
    _create(
        "solace-encounter-ledger",
        AttributeDefinitions=[
            {"AttributeName": "encounter_id", "AttributeType": "S"},
            {"AttributeName": "seq", "AttributeType": "N"},
        ],
        KeySchema=[
            {"AttributeName": "encounter_id", "KeyType": "HASH"},
            {"AttributeName": "seq", "KeyType": "RANGE"},
        ],
    )
    _wait(["solace-patients", "solace-hospitals", "solace-prescriptions", "solace-notes",
           "solace-calls", "solace-appointments", "solace-encounter-ledger"])

    print("Point-in-time recovery:")
    for tbl in ("solace-encounter-ledger",):
        try:
            ddb.update_continuous_backups(
                TableName=tbl,
                PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
            )
            print(f"  [ok]    PITR enabled on {tbl}")
        except ClientError as e:
            print(f"  [warn]  PITR on {tbl}: {e.response['Error']['Code']}")

    print("Enabling TTL:")
    for tbl, attr in [("solace-patients", "ttl"), ("solace-calls", "ttl")]:
        try:
            ddb.update_time_to_live(
                TableName=tbl,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": attr},
            )
            print(f"  [ok] {tbl}.{attr}")
        except ClientError as e:
            if "TimeToLive is already enabled" in str(e):
                print(f"  [ok] {tbl} already enabled")
            else:
                print(f"  [warn] {e}")


def setup_bucket() -> None:
    print(f"S3 media bucket: {BUCKET}")
    try:
        s3.head_bucket(Bucket=BUCKET)
        print("  [ok] already exists")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            print("  [create]")
            if REGION == "us-east-1":
                s3.create_bucket(Bucket=BUCKET)
            else:
                s3.create_bucket(
                    Bucket=BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": REGION},
                )
        else:
            raise

    cors = {
        "CORSRules": [
            {
                "AllowedHeaders": ["*"],
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedOrigins": ["*"],
                "ExposeHeaders": ["ETag", "Content-Length"],
                "MaxAgeSeconds": 3000,
            }
        ]
    }
    s3.put_bucket_cors(Bucket=BUCKET, CORSConfiguration=cors)
    print("  [ok] CORS applied")

    # Block public ACLs but allow presigned URL access (default — no policy needed).
    s3.put_public_access_block(
        Bucket=BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    print("  [ok] public access blocked (presigned URLs still work)")

    # HIPAA §164.312 — default encryption with CMK for all objects at rest
    if CMK_ARN:
        s3.put_bucket_encryption(
            Bucket=BUCKET,
            ServerSideEncryptionConfiguration={
                "Rules": [{
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms",
                        "KMSMasterKeyID": CMK_ARN,
                    },
                    "BucketKeyEnabled": True,
                }]
            },
        )
        print("  [ok] SSE-KMS with solace CMK (BucketKey enabled)")
    else:
        print("  [warn] no CMK — bucket uses default S3 encryption")


def main() -> None:
    global CMK_ARN
    print(f"Account: {ACCOUNT_ID}  Region: {REGION}\n")
    print("Resolving Solace CMK:")
    CMK_ARN = _resolve_cmk_arn()
    print()
    setup_tables()
    print()
    setup_bucket()
    print(f"\nDone. Set S3_BUCKET_MEDIA={BUCKET} in .env and flip SOLACE_MODE=aws.")


if __name__ == "__main__":
    main()
