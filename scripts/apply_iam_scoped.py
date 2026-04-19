"""Create the scoped IAM policy + MFA boundary and attach them to `solace-dev`.

Safety rails:
  - Default: DRY-RUN — prints what it WOULD do, makes no changes.
  - `--apply-policy`    : create + attach SolaceDeveloperAccess (keeps AdministratorAccess in place)
  - `--apply-boundary`  : attach the MFA permission boundary (DO THIS ONLY AFTER A VIRTUAL MFA DEVICE IS ENROLLED, or you'll lock yourself out)
  - `--remove-admin`    : detach AWS-managed AdministratorAccess (ONLY after verifying the scoped policy works for all your commands)

Typical flow:
  1. `python scripts/apply_iam_scoped.py --apply-policy`
  2. Test all your scripts still work (deploy, setup_aws, setup_security, etc)
  3. Enroll a virtual MFA device on solace-dev in the AWS console
  4. `python scripts/apply_iam_scoped.py --apply-boundary`
  5. After confirming all your scripts still pass MFA: `--remove-admin`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

HERE = Path(__file__).resolve().parent
POLICY_FILE = HERE / "iam_solace_developer_policy.json"
BOUNDARY_FILE = HERE / "iam_mfa_boundary.json"
USER = "solace-dev"
POLICY_NAME = "SolaceDeveloperAccess"
BOUNDARY_NAME = "SolaceMFARequired"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
ADMIN_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"

iam = boto3.client("iam")


def upsert_policy(name: str, doc_file: Path) -> str:
    """Create-or-create-new-version of a customer-managed policy."""
    body = json.loads(doc_file.read_text())
    arn = f"arn:aws:iam::{ACCOUNT}:policy/{name}"
    try:
        iam.get_policy(PolicyArn=arn)
        # Exists → create new version (keep max 5 versions)
        versions = iam.list_policy_versions(PolicyArn=arn)["Versions"]
        # Delete the oldest non-default if at cap
        if len(versions) >= 5:
            oldest = sorted([v for v in versions if not v["IsDefaultVersion"]],
                            key=lambda v: v["CreateDate"])[0]
            iam.delete_policy_version(PolicyArn=arn, VersionId=oldest["VersionId"])
        iam.create_policy_version(PolicyArn=arn, PolicyDocument=json.dumps(body), SetAsDefault=True)
        print(f"  [update] {name} -> new version")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_policy(PolicyName=name, PolicyDocument=json.dumps(body),
                          Tags=[{"Key": "project", "Value": "solace"}])
        print(f"  [create] {name}")
    return arn


def apply_policy() -> None:
    print("SolaceDeveloperAccess:")
    arn = upsert_policy(POLICY_NAME, POLICY_FILE)
    # Attach if not already
    attached = iam.list_attached_user_policies(UserName=USER)["AttachedPolicies"]
    if any(p["PolicyArn"] == arn for p in attached):
        print(f"  [ok]    already attached to {USER}")
    else:
        iam.attach_user_policy(UserName=USER, PolicyArn=arn)
        print(f"  [ok]    attached to {USER}")


def apply_boundary() -> None:
    print("SolaceMFARequired (permission boundary):")
    # Boundaries are stored as managed policies too
    arn = upsert_policy(BOUNDARY_NAME, BOUNDARY_FILE)
    iam.put_user_permissions_boundary(UserName=USER, PermissionsBoundary=arn)
    print(f"  [ok]    boundary attached to {USER}")


def remove_admin() -> None:
    print("Detach AdministratorAccess:")
    try:
        iam.detach_user_policy(UserName=USER, PolicyArn=ADMIN_ARN)
        print(f"  [ok]    detached from {USER}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            print("  [ok]    already not attached")
        else:
            raise


def dry_run() -> None:
    print("DRY RUN — no changes made.\n")
    print("Would:")
    print(f"  1. create/update managed policy {POLICY_NAME} (solace-* scoped resources)")
    print(f"  2. attach it to IAM user '{USER}' alongside AdministratorAccess")
    print(f"  3. (with --apply-boundary) attach MFA-required permission boundary")
    print(f"  4. (with --remove-admin) detach AdministratorAccess only after you verify")
    print(f"\nFlags: --apply-policy | --apply-boundary | --remove-admin")


def main() -> None:
    flags = set(sys.argv[1:])
    if not flags or flags == {"--dry-run"}:
        dry_run()
        return
    if "--apply-policy" in flags:
        apply_policy()
    if "--apply-boundary" in flags:
        apply_boundary()
    if "--remove-admin" in flags:
        remove_admin()


if __name__ == "__main__":
    main()
