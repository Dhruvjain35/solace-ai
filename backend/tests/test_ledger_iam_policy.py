"""The ledger's IAM posture, asserted against the checked-in documents.

The append-only guarantee has two halves and only one of them is Python.

``encounter_ledger._persist`` writes with ``attribute_not_exists``, so our code
cannot overwrite an entry. That stops our code. It does nothing about anybody
holding credentials who calls UpdateItem directly, and the developer policy grants
``dynamodb:*`` on ``solace-*``, so until ``scripts/enforce_ledger_immutability.py``
ran, they could — verified rather than assumed:

    $ aws dynamodb update-item --table-name solace-encounter-ledger ...
    (succeeded)
    >>> ledger.verify("enc-live-proof")
    VerifyResult(ok=False, checked=1, broken_at=1, reason='content edited')

The chain made the edit visible, which is exactly what it promises. Visible after
the fact is still weaker than impossible, so an explicit Deny now covers both the
Lambda role and the human principal:

    An error occurred (AccessDeniedException) ... is not authorized to perform:
    dynamodb:UpdateItem ... with an explicit deny in an identity-based policy

These tests guard the documents, not AWS. They run with no credentials and catch
the change that would quietly undo this: somebody widening the allow, or trimming
the deny, in a PR that looks like cleanup.
"""
from __future__ import annotations

import json
import pathlib

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
DENY = json.loads((SCRIPTS / "iam_ledger_append_only.json").read_text())
ALLOW = json.loads((SCRIPTS / "iam_ledger_allow.json").read_text())

LEDGER_ARN = "arn:aws:dynamodb:us-east-1:704229156617:table/solace-encounter-ledger"


def _statements(policy, effect):
    return [s for s in policy["Statement"] if s["Effect"] == effect]


def _actions(policy, effect) -> set[str]:
    out = set()
    for s in _statements(policy, effect):
        a = s["Action"]
        out.update(a if isinstance(a, list) else [a])
    return out


# ── The deny ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("action", [
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",   # can carry DeleteRequest
    "dynamodb:PartiQLUpdate",
    "dynamodb:PartiQLDelete",
])
def test_every_way_to_change_a_row_is_denied(action):
    """PartiQL is the one that gets forgotten. It is a separate action namespace,
    so denying UpdateItem alone leaves `UPDATE solace-encounter-ledger SET ...`
    working."""
    assert action in _actions(DENY, "Deny")


@pytest.mark.parametrize("action", [
    "dynamodb:DeleteTable",
    "dynamodb:UpdateTimeToLive",
])
def test_the_table_cannot_be_dropped_or_given_a_ttl(action):
    """Append-only protects entries from being edited. It says nothing about the
    table being deleted, or quietly given a TTL that expires the record out from
    under everyone, which would look like ordinary housekeeping in a console."""
    assert action in _actions(DENY, "Deny")


def test_the_deny_has_no_allow_statements():
    """A deny document that grows an Allow is how a deny stops being a deny."""
    assert not _statements(DENY, "Allow")


def test_the_deny_targets_the_ledger_and_only_the_ledger():
    """A wildcard here would deny writes to every solace table and take the
    product down, which is the failure mode of over-correcting on this."""
    for s in _statements(DENY, "Deny"):
        for arn in (s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]):
            assert arn.startswith(LEDGER_ARN), f"deny reaches beyond the ledger: {arn}"


# ── The allow ────────────────────────────────────────────────────────────────

def test_the_service_can_append_and_read():
    """The other failure mode. The first version of this attached a correct deny
    and no allow at all, so the role could not write a single entry — the policy
    simulator said implicitDeny on PutItem while the script printed success."""
    assert {"dynamodb:PutItem", "dynamodb:Query"} <= _actions(ALLOW, "Allow")


def test_the_allow_grants_nothing_that_mutates():
    """Belt and braces are both wanted, but the allow should be right on its own:
    if the deny were ever detached, least privilege should still hold."""
    mutating = {"dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
               "dynamodb:DeleteTable", "dynamodb:PartiQLUpdate", "dynamodb:PartiQLDelete"}
    assert not (_actions(ALLOW, "Allow") & mutating)


def test_the_allow_uses_no_wildcards():
    for s in _statements(ALLOW, "Allow"):
        for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]]):
            assert "*" not in a, f"wildcard action in the ledger allow: {a}"
        for arn in (s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]):
            assert arn == LEDGER_ARN, f"allow reaches beyond the ledger: {arn}"


# ── The two halves have to agree ─────────────────────────────────────────────

def test_nothing_is_both_allowed_and_denied():
    """Not broken — a Deny wins — but it means the two documents disagree about
    intent, and the next person has to work out which one is the mistake."""
    overlap = _actions(ALLOW, "Allow") & _actions(DENY, "Deny")
    assert not overlap, f"the allow grants what the deny forbids: {sorted(overlap)}"


def test_the_ledger_table_is_not_covered_by_a_ttl_anywhere():
    """setup_aws.py enables TTL on transient tables by name. The ledger must
    never join that list: a six-year record with a TTL is a six-week record."""
    setup = (SCRIPTS / "setup_aws.py").read_text()
    ttl_block = setup[setup.index("Enabling TTL:"):] if "Enabling TTL:" in setup else ""
    assert "solace-encounter-ledger" not in ttl_block, \
        "the ledger was added to the TTL list; entries would silently expire"
