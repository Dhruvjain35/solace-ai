"""Codify the solace-api Lambda EXECUTION-ROLE runtime IAM grants. Idempotent.

This is the source of truth for the RUNTIME role `solace-lambda-exec` (distinct from
`scripts/apply_iam_scoped.py`, which manages the DEVELOPER user `solace-dev`). It
exists because the exec-role inline policies were originally created ad-hoc, so live
tables drifted out of the policy and silently failed in prod (in-memory fallback,
lost on cold start). Re-running this keeps the runtime IAM reproducible.

Grants (all SCOPED — never Resource "*" except where the service requires it):
  - solace-ddb-all     : full DDB action set on EVERY live solace-* table + /index/*
                         (the list is the union of setup_aws.py + the feature tables:
                          overrides, labels, billing, oauth-states, magic-tokens, etc.)
  - solace-self-invoke : lambda:InvokeFunction on the solace-api ARN ONLY
                         (deferred-artifact async self-invoke — see lib/async_invoke.py)
  - solace-polly-tts   : polly:SynthesizeSpeech (Polly cannot be ARN-scoped)

NOTE: the original `solace-app` inline policy is left untouched; solace-ddb-all is a
superset that covers any table it missed. S3 media bucket access + the S3_BUCKET_MEDIA
env var are handled by setup_aws.py / deploy; this script is IAM-only.

Safety: default DRY-RUN. Pass --apply to write the inline policies.

    python scripts/setup_exec_role_iam.py            # dry-run, prints the policies
    python scripts/setup_exec_role_iam.py --apply     # apply to solace-lambda-exec
"""
from __future__ import annotations

import json
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
EXEC_ROLE = "solace-lambda-exec"
FUNCTION_NAME = "solace-api"

iam = boto3.client("iam")
ddb = boto3.client("dynamodb", region_name=REGION)

_DDB_ACTIONS = [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:DescribeTable",
]


def _all_solace_tables() -> list[str]:
    """Every live solace-* table — derived, so the policy can never drift behind
    the tables again (the root cause of the 2026-06-01 silent-failure incident)."""
    names: list[str] = []
    paginator = ddb.get_paginator("list_tables")
    for page in paginator.paginate():
        names.extend(t for t in page["TableNames"] if t.startswith("solace-"))
    return sorted(names)


def _ddb_policy(tables: list[str]) -> dict:
    resources: list[str] = []
    for t in tables:
        arn = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{t}"
        resources += [arn, arn + "/index/*"]
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "SolaceRuntimeDDB",
            "Effect": "Allow",
            "Action": _DDB_ACTIONS,
            "Resource": resources,
        }],
    }


def _self_invoke_policy() -> dict:
    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "SolaceDeferredArtifactsSelfInvoke",
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": fn_arn,
        }],
    }


def _polly_policy() -> dict:
    # Polly's SynthesizeSpeech does not support resource-level scoping; the action
    # itself is the boundary. This is standard for Polly.
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "SolacePollyTTS",
            "Effect": "Allow",
            "Action": ["polly:SynthesizeSpeech"],
            "Resource": "*",
        }],
    }


def _put(policy_name: str, doc: dict, apply: bool) -> None:
    if apply:
        iam.put_role_policy(
            RoleName=EXEC_ROLE,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(doc),
        )
        print(f"  [apply]  {policy_name}")
    else:
        n = len(doc["Statement"][0]["Resource"]) if isinstance(doc["Statement"][0]["Resource"], list) else 1
        print(f"  [dry]    {policy_name} — actions={len(doc['Statement'][0]['Action']) if isinstance(doc['Statement'][0]['Action'], list) else 1}, resources={n}")


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    print(f"Account: {ACCOUNT}  Role: {EXEC_ROLE}  ({'APPLY' if apply else 'DRY-RUN'})\n")

    try:
        iam.get_role(RoleName=EXEC_ROLE)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            print(f"ERROR: role {EXEC_ROLE} not found — is this the Solace account?")
            sys.exit(1)
        raise

    tables = _all_solace_tables()
    print(f"Live solace-* tables ({len(tables)}): {', '.join(tables)}\n")

    print("Runtime inline policies:")
    _put("solace-ddb-all", _ddb_policy(tables), apply)
    _put("solace-self-invoke", _self_invoke_policy(), apply)
    _put("solace-polly-tts", _polly_policy(), apply)

    if apply:
        print("\nDone. Runtime IAM codified — re-run after adding any new solace-* table.")
    else:
        print("\nDRY-RUN only. Re-run with --apply to write these to the role.")


if __name__ == "__main__":
    main()
