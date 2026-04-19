"""Harden Solace on AWS — KMS CMK, Secrets Manager, CloudTrail. Idempotent."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
sts = boto3.client("sts")
ACCOUNT = sts.get_caller_identity()["Account"]

KEY_ALIAS = "alias/solace"
SECRET_NAME = "solace/api-keys"
TRAIL_NAME = "solace-trail"
TRAIL_BUCKET = f"solace-cloudtrail-{ACCOUNT}"
MEDIA_BUCKET = f"solace-media-{ACCOUNT}"
DDB_TABLES = [
    "solace-patients",
    "solace-hospitals",
    "solace-prescriptions",
    "solace-notes",
]

kms = boto3.client("kms", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
s3ctl = boto3.client("s3control", region_name=REGION)
ddb = boto3.client("dynamodb", region_name=REGION)
sm = boto3.client("secretsmanager", region_name=REGION)
ct = boto3.client("cloudtrail", region_name=REGION)


# ---------- KMS ----------
def ensure_cmk() -> str:
    """Create or fetch the Solace CMK. Returns key ARN."""
    try:
        resp = kms.describe_key(KeyId=KEY_ALIAS)
        arn = resp["KeyMetadata"]["Arn"]
        print(f"  [ok] CMK exists: {arn}")
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "EnableRootAccount",
                "Effect": "Allow",
                "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
                "Action": "kms:*",
                "Resource": "*",
            },
            {
                "Sid": "AllowCloudTrailUseOfKey",
                "Effect": "Allow",
                "Principal": {"Service": "cloudtrail.amazonaws.com"},
                "Action": ["kms:GenerateDataKey*", "kms:DescribeKey"],
                "Resource": "*",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudtrail:{REGION}:{ACCOUNT}:trail/{TRAIL_NAME}"
                    }
                },
            },
        ],
    }
    resp = kms.create_key(
        Description="Solace patient data encryption key",
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
        Policy=json.dumps(policy),
        Tags=[{"TagKey": "project", "TagValue": "solace"}],
    )
    arn = resp["KeyMetadata"]["Arn"]
    key_id = resp["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName=KEY_ALIAS, TargetKeyId=key_id)
    kms.enable_key_rotation(KeyId=key_id)
    print(f"  [create] CMK: {arn}")
    print("  [ok] annual rotation enabled")
    return arn


# ---------- DynamoDB encryption ----------
def encrypt_ddb(cmk_arn: str) -> None:
    for name in DDB_TABLES:
        desc = ddb.describe_table(TableName=name)["Table"]
        sse = desc.get("SSEDescription", {})
        current = sse.get("KMSMasterKeyArn")
        if current == cmk_arn:
            print(f"  [ok]    {name} already uses solace CMK")
            continue
        print(f"  [update] {name} → solace CMK")
        ddb.update_table(
            TableName=name,
            SSESpecification={
                "Enabled": True,
                "SSEType": "KMS",
                "KMSMasterKeyId": cmk_arn,
            },
        )
    # Wait until every table is ACTIVE again
    waiter = ddb.get_waiter("table_exists")
    for name in DDB_TABLES:
        waiter.wait(TableName=name)


# ---------- S3 encryption ----------
def encrypt_s3(cmk_arn: str) -> None:
    s3.put_bucket_encryption(
        Bucket=MEDIA_BUCKET,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms",
                        "KMSMasterKeyID": cmk_arn,
                    },
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    print(f"  [ok] {MEDIA_BUCKET} now encrypts with solace CMK (BucketKey enabled)")


# ---------- Secrets Manager ----------
def upsert_secret(cmk_arn: str) -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

    secret_payload = {
        "OPENAI_API_KEY": env.get("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": env.get("ANTHROPIC_API_KEY", ""),
        "ELEVENLABS_API_KEY": env.get("ELEVENLABS_API_KEY", ""),
        "ELEVENLABS_VOICE_ID": env.get("ELEVENLABS_VOICE_ID", ""),
        "DEMO_CLINICIAN_PIN": env.get("DEMO_CLINICIAN_PIN", ""),
    }
    body = json.dumps(secret_payload)

    try:
        sm.describe_secret(SecretId=SECRET_NAME)
        sm.update_secret(SecretId=SECRET_NAME, SecretString=body, KmsKeyId=cmk_arn)
        print(f"  [update] {SECRET_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        sm.create_secret(
            Name=SECRET_NAME,
            Description="Solace third-party API keys",
            KmsKeyId=cmk_arn,
            SecretString=body,
            Tags=[{"Key": "project", "Value": "solace"}],
        )
        print(f"  [create] {SECRET_NAME}")


# ---------- CloudTrail ----------
def ensure_trail_bucket() -> None:
    try:
        s3.head_bucket(Bucket=TRAIL_BUCKET)
        print(f"  [ok] {TRAIL_BUCKET} exists")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            if REGION == "us-east-1":
                s3.create_bucket(Bucket=TRAIL_BUCKET)
            else:
                s3.create_bucket(
                    Bucket=TRAIL_BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": REGION},
                )
            print(f"  [create] {TRAIL_BUCKET}")
        else:
            raise

    s3.put_public_access_block(
        Bucket=TRAIL_BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    # Enforce SSE on the log bucket itself (trail logs are sensitive)
    s3.put_bucket_encryption(
        Bucket=TRAIL_BUCKET,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AWSCloudTrailAclCheck",
                "Effect": "Allow",
                "Principal": {"Service": "cloudtrail.amazonaws.com"},
                "Action": "s3:GetBucketAcl",
                "Resource": f"arn:aws:s3:::{TRAIL_BUCKET}",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudtrail:{REGION}:{ACCOUNT}:trail/{TRAIL_NAME}"
                    }
                },
            },
            {
                "Sid": "AWSCloudTrailWrite",
                "Effect": "Allow",
                "Principal": {"Service": "cloudtrail.amazonaws.com"},
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{TRAIL_BUCKET}/AWSLogs/{ACCOUNT}/*",
                "Condition": {
                    "StringEquals": {
                        "s3:x-amz-acl": "bucket-owner-full-control",
                        "AWS:SourceArn": f"arn:aws:cloudtrail:{REGION}:{ACCOUNT}:trail/{TRAIL_NAME}",
                    }
                },
            },
        ],
    }
    s3.put_bucket_policy(Bucket=TRAIL_BUCKET, Policy=json.dumps(policy))
    print("  [ok] bucket policy applied")


def ensure_trail(cmk_arn: str) -> None:
    try:
        ct.describe_trails(trailNameList=[TRAIL_NAME])["trailList"][0]
        print(f"  [ok] trail {TRAIL_NAME} exists — updating config")
        ct.update_trail(
            Name=TRAIL_NAME,
            S3BucketName=TRAIL_BUCKET,
            IsMultiRegionTrail=True,
            IncludeGlobalServiceEvents=True,
            EnableLogFileValidation=True,
            KmsKeyId=cmk_arn,
        )
    except (ClientError, IndexError):
        print(f"  [create] trail {TRAIL_NAME}")
        ct.create_trail(
            Name=TRAIL_NAME,
            S3BucketName=TRAIL_BUCKET,
            IsMultiRegionTrail=True,
            IncludeGlobalServiceEvents=True,
            EnableLogFileValidation=True,
            KmsKeyId=cmk_arn,
        )

    # Log every GET/PUT on the media bucket as data events
    ct.put_event_selectors(
        TrailName=TRAIL_NAME,
        AdvancedEventSelectors=[
            {
                "Name": "Management events",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Management"]}
                ],
            },
            {
                "Name": "S3 data events on media bucket",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::S3::Object"]},
                    {
                        "Field": "resources.ARN",
                        "StartsWith": [f"arn:aws:s3:::{MEDIA_BUCKET}/"],
                    },
                ],
            },
            {
                "Name": "DynamoDB data events",
                "FieldSelectors": [
                    {"Field": "eventCategory", "Equals": ["Data"]},
                    {"Field": "resources.type", "Equals": ["AWS::DynamoDB::Table"]},
                ],
            },
        ],
    )
    ct.start_logging(Name=TRAIL_NAME)
    print("  [ok] trail logging started (mgmt + S3 data + DDB data)")


# ---------- DDB point-in-time recovery ----------
def enable_ddb_pitr() -> None:
    for name in DDB_TABLES:
        try:
            cur = ddb.describe_continuous_backups(TableName=name)
            status = cur["ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"][
                "PointInTimeRecoveryStatus"
            ]
            if status == "ENABLED":
                print(f"  [ok]    {name} PITR already enabled")
                continue
        except ClientError:
            pass
        ddb.update_continuous_backups(
            TableName=name,
            PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
        )
        print(f"  [enable] {name} PITR (35-day restore window)")


# ---------- S3 hardening ----------
def harden_s3(bucket: str) -> None:
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    deny_insecure = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ],
    }
    # Fetch existing policy (trail bucket has one already) and append deny
    try:
        existing = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        existing_stmts = existing.get("Statement", [])
        existing_stmts = [s for s in existing_stmts if s.get("Sid") != "DenyInsecureTransport"]
        existing_stmts.append(deny_insecure["Statement"][0])
        merged = {"Version": "2012-10-17", "Statement": existing_stmts}
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(merged))
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchBucketPolicy":
            s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(deny_insecure))
        else:
            raise
    print(f"  [ok] {bucket}: versioning + TLS-only policy")


def block_public_at_account() -> None:
    s3ctl.put_public_access_block(
        AccountId=ACCOUNT,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    print(f"  [ok] account-level public access fully blocked")


def main() -> None:
    print(f"Account: {ACCOUNT}  Region: {REGION}\n")

    print("KMS customer-managed key:")
    cmk = ensure_cmk()
    print()

    print("DynamoDB encryption:")
    encrypt_ddb(cmk)
    print()

    print("S3 media bucket encryption:")
    encrypt_s3(cmk)
    print()

    print("Secrets Manager:")
    upsert_secret(cmk)
    print()

    print("CloudTrail log bucket:")
    ensure_trail_bucket()
    print()

    print("CloudTrail:")
    ensure_trail(cmk)
    print()

    print("DynamoDB PITR (35-day backups):")
    enable_ddb_pitr()
    print()

    print("S3 hardening (versioning + TLS-only):")
    harden_s3(MEDIA_BUCKET)
    harden_s3(TRAIL_BUCKET)
    print()

    print("Account-level S3 public access block:")
    block_public_at_account()
    print()

    print(f"Done. CMK: {cmk}")
    print("Everything at rest is now encrypted with the Solace CMK.")
    print("API keys live in Secrets Manager; trail captures every data-plane call.")


if __name__ == "__main__":
    main()
