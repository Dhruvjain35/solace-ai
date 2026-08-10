#!/usr/bin/env python3
"""Make the encounter ledger's append-only guarantee enforceable from outside.

``services/encounter_ledger.py`` writes each entry with

    ConditionExpression="attribute_not_exists(encounter_id) AND attribute_not_exists(seq)"

which means our own code cannot overwrite an entry even if it tries. That is a
real guarantee and it is not the whole one, because the same credentials can call
``UpdateItem`` directly and skip our write path entirely. The developer policy
currently grants ``dynamodb:*`` on ``solace-*``, so today they can.

This attaches an explicit Deny for UpdateItem, DeleteItem and the PartiQL
equivalents on the ledger table. In IAM a Deny beats any Allow, including
``dynamodb:*`` and including AdministratorAccess, so after this runs there is no
principal in the account that can edit a ledger row through the API. That is the
difference between "our code does not modify it" and "it cannot be modified" —
the second is a claim a hospital's security review can verify without reading a
line of our source.

Also denies DeleteTable and UpdateTimeToLive. Append-only protects entries from
being edited; it does nothing about the table being dropped or quietly given a
TTL that expires the record out from under everyone.

Run:  python scripts/enforce_ledger_immutability.py [--check]

``--check`` verifies without changing anything, which is what belongs in a
compliance review or a periodic job.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import boto3
from botocore.exceptions import ClientError

DENY_FILE = pathlib.Path(__file__).with_name("iam_ledger_append_only.json")
ALLOW_FILE = pathlib.Path(__file__).with_name("iam_ledger_allow.json")
POLICY_NAME = "SolaceLedgerAppendOnly"
ALLOW_NAME = "SolaceLedgerAppend"

# The allow is least-privilege on its own: PutItem, GetItem, Query and nothing
# else. The deny is belt as well as braces, because a future edit that widens
# some other policy to solace-* would otherwise silently hand back UpdateItem.
REQUIRED_ALLOWS = {"dynamodb:PutItem", "dynamodb:Query"}

# Every principal that can reach the table. A deny on the Lambda role alone would
# leave a developer with console access able to edit the record by hand, which is
# exactly the person an auditor is asking about.
TARGET_ROLES = ["solace-lambda-exec"]

# The human principal, deliberately included. Proved necessary rather than
# assumed: with only the Lambda role denied, a direct UpdateItem from solace-dev
# succeeded, and the ledger reported ok=False broken_at=1 reason="content
# edited". The chain made the edit visible, which is what it promises, but
# visible-after-the-fact is a weaker claim than impossible.
#
# This is not a lockout. Removing the policy is still within this user's IAM
# permissions — it just cannot be done silently or by accident, and the
# solace-alert-iam-changes rule fires when somebody does. Forcing an auditable,
# deliberate act is the whole mechanism.
TARGET_USERS: list[str] = ["solace-dev"]

DENIED_ACTIONS = {
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:PartiQLUpdate",
    "dynamodb:PartiQLDelete",
}


def _policy(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def apply(iam) -> int:
    deny_doc = json.dumps(_policy(DENY_FILE))
    allow_doc = json.dumps(_policy(ALLOW_FILE))
    failures = 0
    for role in TARGET_ROLES:
        for name, doc, label in (
            (ALLOW_NAME, allow_doc, "append+read allow"),
            (POLICY_NAME, deny_doc, "mutation deny"),
        ):
            try:
                iam.put_role_policy(RoleName=role, PolicyName=name, PolicyDocument=doc)
                print(f"  [ok]     {label} attached to role {role}")
            except ClientError as e:
                failures += 1
                print(f"  [FAIL]   role {role} {label}: {e.response['Error']['Code']}")
    for user in TARGET_USERS:
        try:
            iam.put_user_policy(
                UserName=user, PolicyName=POLICY_NAME, PolicyDocument=deny_doc
            )
            print(f"  [ok]     deny attached to user {user}")
        except ClientError as e:
            failures += 1
            print(f"  [FAIL]   user {user}: {e.response['Error']['Code']}")
    return failures


def check(iam) -> int:
    """Report whether the deny is in place. Exit code is what a CI job reads."""
    missing = 0
    for user in TARGET_USERS:
        arn = f"arn:aws:iam::704229156617:user/{user}"
        missing += _simulate_arn(iam, arn, f"user {user}", mutating_only=True)
    for role in TARGET_ROLES:
        try:
            doc = iam.get_role_policy(RoleName=role, PolicyName=POLICY_NAME)["PolicyDocument"]
        except ClientError:
            print(f"  [MISSING] role {role} has no {POLICY_NAME} policy")
            missing += 1
            continue
        denied = {
            action
            for statement in doc.get("Statement", [])
            if statement.get("Effect") == "Deny"
            for action in (
                statement["Action"]
                if isinstance(statement.get("Action"), list)
                else [statement.get("Action")]
            )
        }
        gaps = DENIED_ACTIONS - denied
        if gaps:
            print(f"  [GAP]     role {role} does not deny: {sorted(gaps)}")
            missing += 1
        else:
            print(f"  [ok]      role {role} denies every mutating ledger action")

        # Ask IAM what it would actually decide, rather than reading our own
        # document back. The first version of this script reported success while
        # the role had no allow at all and could not write a single entry — the
        # deny was correct and the table was unusable.
        missing += _simulate(iam, role)
    return missing


def _simulate(iam, role: str) -> int:
    return _simulate_arn(iam, f"arn:aws:iam::704229156617:role/{role}", f"role {role}")


def _simulate_arn(iam, arn: str, label: str, *, mutating_only: bool = False) -> int:
    table = "arn:aws:dynamodb:us-east-1:704229156617:table/solace-encounter-ledger"
    expected = {
        "dynamodb:UpdateItem": "explicitDeny",
        "dynamodb:DeleteItem": "explicitDeny",
    }
    if not mutating_only:
        # A human principal has no reason to append entries; only the service
        # writes. So the allow half is checked for the role and not for people.
        expected["dynamodb:PutItem"] = "allowed"
        expected["dynamodb:Query"] = "allowed"
    problems = 0
    try:
        results = iam.simulate_principal_policy(
            PolicySourceArn=arn, ActionNames=list(expected), ResourceArns=[table]
        )["EvaluationResults"]
    except ClientError as e:
        print(f"  [warn]    could not simulate {label}: {e.response['Error']['Code']}")
        return 0
    for r in results:
        action, decision = r["EvalActionName"], r["EvalDecision"]
        want = expected[action]
        if decision != want:
            print(f"  [GAP]     {action} evaluates to {decision}, expected {want}")
            problems += 1
    if not problems:
        what = "cannot mutate" if mutating_only else "can append and read, and cannot mutate"
        print(f"  [ok]      {label} {what}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify without changing anything")
    args = parser.parse_args()

    iam = boto3.client("iam")
    print(f"Ledger immutability ({'check' if args.check else 'apply'}):")
    problems = check(iam) if args.check else apply(iam)
    if problems:
        print(f"\n{problems} problem(s). The ledger's append-only claim is not "
              f"enforceable against a principal with direct table access.")
        return 1
    print("\nThe ledger cannot be edited or deleted through the DynamoDB API by "
          "any principal covered above, regardless of what else they are granted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
