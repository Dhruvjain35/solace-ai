"""SNS topic + EventBridge rules for sensitive AWS activity.

Alarms on:
  - Root account console login
  - IAM policy / user / role mutations
  - CMK scheduled-for-deletion
  - Secrets Manager secret deletion
  - Lambda function deletion

All pipe to `solace-security-alerts` SNS topic. User confirms their email
subscription via the AWS email (one-time click).

EventBridge catches these directly from the default bus (CloudTrail events
auto-appear there) — no CloudWatch Log group needed.
"""
from __future__ import annotations

import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
TOPIC_NAME = "solace-security-alerts"
CMK_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/66c32010-5752-4b1d-8efe-bc317a44cb23"

sns = boto3.client("sns", region_name=REGION)
events = boto3.client("events", region_name=REGION)

RULES = {
    "solace-alert-root-login": {
        "Description": "Alert on root account console login",
        "Pattern": {
            "source": ["aws.signin"],
            "detail-type": ["AWS Console Sign In via CloudTrail"],
            "detail": {"userIdentity": {"type": ["Root"]}},
        },
    },
    "solace-alert-iam-changes": {
        "Description": "Alert on IAM policy / user / role / access-key mutations",
        "Pattern": {
            "source": ["aws.iam"],
            "detail-type": ["AWS API Call via CloudTrail"],
            "detail": {
                "eventSource": ["iam.amazonaws.com"],
                "eventName": [
                    "CreateUser", "DeleteUser",
                    "CreatePolicy", "DeletePolicy",
                    "AttachUserPolicy", "DetachUserPolicy",
                    "AttachRolePolicy", "DetachRolePolicy",
                    "PutUserPolicy", "DeleteUserPolicy",
                    "PutRolePolicy", "DeleteRolePolicy",
                    "CreateAccessKey", "DeleteAccessKey",
                    "UpdateAssumeRolePolicy", "DeleteRole",
                    "CreateLoginProfile", "UpdateLoginProfile",
                ],
            },
        },
    },
    "solace-alert-kms-deletion": {
        "Description": "Alert when any KMS key is scheduled for deletion",
        "Pattern": {
            "source": ["aws.kms"],
            "detail": {
                "eventName": ["ScheduleKeyDeletion", "DisableKey", "DisableKeyRotation"],
            },
        },
    },
    "solace-alert-secret-deletion": {
        "Description": "Alert on Secrets Manager secret deletion or rotation failure",
        "Pattern": {
            "source": ["aws.secretsmanager"],
            "detail": {"eventName": ["DeleteSecret", "UpdateSecret", "PutSecretValue"]},
        },
    },
    "solace-alert-lambda-mutation": {
        "Description": "Alert on Lambda function delete / permission changes",
        "Pattern": {
            "source": ["aws.lambda"],
            "detail": {
                "eventName": [
                    "DeleteFunction", "RemovePermission",
                    "AddPermission", "UpdateFunctionCode",
                ],
            },
        },
    },
}


def ensure_topic(email: str | None) -> str:
    resp = sns.create_topic(Name=TOPIC_NAME, Tags=[{"Key": "project", "Value": "solace"}])
    arn = resp["TopicArn"]
    print(f"  [ok]    SNS topic: {arn}")
    # Encrypt with our CMK
    sns.set_topic_attributes(TopicArn=arn, AttributeName="KmsMasterKeyId", AttributeValue=CMK_ARN)

    # Allow EventBridge to publish
    sns.set_topic_attributes(
        TopicArn=arn,
        AttributeName="Policy",
        AttributeValue=json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "EventBridgePublish",
                    "Effect": "Allow",
                    "Principal": {"Service": "events.amazonaws.com"},
                    "Action": "sns:Publish",
                    "Resource": arn,
                }
            ],
        }),
    )

    if email:
        # Check if email already subscribed
        subs = sns.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])
        already = next((s for s in subs if s["Protocol"] == "email" and s["Endpoint"] == email), None)
        if already:
            print(f"  [ok]    email already subscribed: {email} ({already.get('SubscriptionArn','')[:40]})")
        else:
            sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=email)
            print(f"  [ok]    subscribed {email} — confirm via email click")
    return arn


def ensure_rules(topic_arn: str) -> None:
    for name, cfg in RULES.items():
        events.put_rule(
            Name=name,
            EventPattern=json.dumps(cfg["Pattern"]),
            State="ENABLED",
            Description=cfg["Description"],
        )
        events.put_targets(
            Rule=name,
            Targets=[{"Id": "sns", "Arn": topic_arn}],
        )
        print(f"  [ok]    {name}")


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else None
    if not email:
        print("usage: python setup_security_alerts.py <email_for_alerts>")
        print("  (re-run later with --no-email to skip subscription setup)")
        if "--no-email" not in sys.argv:
            sys.exit(1)

    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("SNS topic + email subscription:")
    topic_arn = ensure_topic(email if email and email != "--no-email" else None)
    print()
    print("EventBridge rules:")
    ensure_rules(topic_arn)
    print()
    print("Done. Click the confirmation link in your email to activate alerts.")


if __name__ == "__main__":
    main()
