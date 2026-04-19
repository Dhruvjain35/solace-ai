"""Create Solace DynamoDB tables + S3 media bucket. Idempotent."""
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
    _wait(["solace-patients", "solace-hospitals", "solace-prescriptions", "solace-notes"])

    print("Enabling TTL on solace-patients (24h auto-expire):")
    try:
        ddb.update_time_to_live(
            TableName="solace-patients",
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
        )
        print("  [ok]")
    except ClientError as e:
        if "TimeToLive is already enabled" in str(e):
            print("  [ok] already enabled")
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


def main() -> None:
    print(f"Account: {ACCOUNT_ID}  Region: {REGION}\n")
    setup_tables()
    print()
    setup_bucket()
    print(f"\nDone. Set S3_BUCKET_MEDIA={BUCKET} in .env and flip SOLACE_MODE=aws.")


if __name__ == "__main__":
    main()
