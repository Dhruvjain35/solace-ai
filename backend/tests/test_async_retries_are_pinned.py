"""The 3x multiplier from 42abe22 must be pinned in code, not in the console.

`test_warmup_is_bounded.py` covers the *blast radius* of that incident — the warm
path now has a time budget. This file covers the *multiplier*, which is the part
that turned a slow function into a bill:

    the multiplier   Lambda's default two async retries. 360 scheduled pings a
                     day became 1,080 invocations, each billed for a full minute
                     at 2 GB.

That fix was applied by hand in the AWS console and never written down. The
docstring of test_warmup_is_bounded.py asserts in prose that retries are "now
zero for this function" while nothing in the repository made it so — and two
separate code paths in scripts/deploy_container.py actively erased it:

  * `recreate_function` deletes the function on the Zip->Image path, which
    discards its EventInvokeConfig; `create_function` never set one.
  * `point_warmer` calls `put_targets` with the same target Id and no
    RetryPolicy on EVERY deploy, overwriting whatever was set by hand. This is
    the path that runs today, so the erasure happened on every ship.

These are static assertions against the deploy script's own AST rather than
behavioural tests, and that is the point: the lesson of 42abe22 is not that a
retry policy is hard to set, it is that a setting which lives only in an account
cannot be proven, reviewed, or restored. A test that reads the source is exactly
as strong as the claim being made — that the configuration is *in the repo*.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy_container.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    assert SCRIPT.exists(), f"deploy script moved: {SCRIPT}"
    return ast.parse(SCRIPT.read_text())


def _calls_named(tree: ast.Module, name: str) -> list[ast.Call]:
    """Every call whose function is an attribute with this name."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == name
    ]


def _kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _dict_entries(node: ast.Dict) -> dict:
    """Literal-evaluable entries of a dict node, skipping the rest.

    `Targets=[{"Arn": lambda_arn, ...}]` is not literal-evaluable as a whole
    because `lambda_arn` is a variable — but "RetryPolicy" and "Id" beside it
    are. Reading key by key gets the assertion what it needs without demanding
    the deploy script inline a runtime value.
    """
    out = {}
    for key, value in zip(node.keys, node.values):
        k = _literal(key) if key is not None else None
        if isinstance(k, str):
            out[k] = _literal(value)
    return out


# ---------------------------------------------------------------------------
# Function-level async invoke config
# ---------------------------------------------------------------------------

def test_the_deploy_pins_function_level_async_retries_to_zero(tree):
    calls = _calls_named(tree, "put_function_event_invoke_config")
    assert calls, (
        "scripts/deploy_container.py never calls put_function_event_invoke_config. "
        "Without it, a recreated function silently returns to Lambda's default of "
        "two async retries — the exact multiplier that produced the 42abe22 bill."
    )
    for call in calls:
        assert _literal(_kwarg(call, "MaximumRetryAttempts")) == 0, (
            "MaximumRetryAttempts must be 0. Any other value re-arms the multiplier."
        )
        age = _literal(_kwarg(call, "MaximumEventAgeInSeconds"))
        assert isinstance(age, int) and 0 < age <= 300, (
            f"MaximumEventAgeInSeconds must be set and short, got {age!r}. An "
            "unbounded event age lets a backlog replay long after it is useful."
        )


def test_the_pin_runs_on_every_deploy_not_only_on_a_recreate(tree):
    """It must be called from main(), not tucked inside a conditional branch.

    The Zip->Image delete path is the one that loses EventInvokeConfig, but the
    update path is the one that runs today. Pinning only on recreate would mean
    the setting is correct exactly when nobody is deploying that way.
    """
    main_fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None
    )
    assert main_fn is not None, "deploy_container.py has no main()"

    called = {
        n.func.id
        for n in ast.walk(main_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "pin_async_retries" in called, (
        "main() does not call pin_async_retries(). It must run unconditionally on "
        "every deploy, because both recreate_function branches can reach a state "
        "with no EventInvokeConfig."
    )


# ---------------------------------------------------------------------------
# Target-level retry policy
# ---------------------------------------------------------------------------

def test_every_eventbridge_target_carries_a_zero_retry_policy(tree):
    """put_targets with no RetryPolicy overwrites the account's setting.

    This is the erasure that fires on every single deploy today.
    """
    calls = _calls_named(tree, "put_targets")
    assert calls, "no put_targets call found — has the warmer wiring moved?"

    for call in calls:
        targets_node = _kwarg(call, "Targets")
        assert isinstance(targets_node, (ast.List, ast.Tuple)), (
            "Targets is not an inline list; this test reads it statically so the "
            "retry policy stays reviewable in the diff"
        )
        assert targets_node.elts, "put_targets called with no targets"
        for element in targets_node.elts:
            assert isinstance(element, ast.Dict), (
                "each EventBridge target must be an inline dict so its RetryPolicy "
                "is visible in review"
            )
            target = _dict_entries(element)
            policy = target.get("RetryPolicy")
            assert policy is not None, (
                f"EventBridge target {target.get('Id')!r} has no RetryPolicy. "
                "put_targets replaces the whole target, so omitting it erases any "
                "policy set by hand and restores the default two retries."
            )
            assert policy.get("MaximumRetryAttempts") == 0, (
                f"target {target.get('Id')!r} must set MaximumRetryAttempts to 0, "
                f"got {policy.get('MaximumRetryAttempts')!r}"
            )
            age = policy.get("MaximumEventAgeInSeconds")
            assert isinstance(age, int) and 0 < age <= 300, (
                f"target {target.get('Id')!r} needs a short MaximumEventAgeInSeconds, "
                f"got {age!r}"
            )


# ---------------------------------------------------------------------------
# The surrounding invariants that made the incident expensive
# ---------------------------------------------------------------------------

def test_the_function_timeout_is_still_bounded(tree):
    """A 60s timeout is what made each retried invocation cost a full minute.

    Not a demand that it be 60 — a demand that it be *stated*, so that the
    warmup budget in test_warmup_is_bounded.py has something to be well under.
    """
    creates = _calls_named(tree, "create_function")
    assert creates, "create_function call not found"
    for call in creates:
        timeout = _literal(_kwarg(call, "Timeout"))
        assert isinstance(timeout, int) and timeout <= 300, (
            f"Lambda Timeout must be set and bounded, got {timeout!r}"
        )


def test_no_call_sets_retries_above_zero_anywhere(tree):
    """A second call site that sets a non-zero value would defeat the first.

    Cheap now, load-bearing the moment a shadow-scorer function is added with
    its own invoke config.
    """
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        value = _literal(_kwarg(node, "MaximumRetryAttempts"))
        if value not in (None, 0):
            offenders.append(value)
        targets_node = _kwarg(node, "Targets")
        if isinstance(targets_node, (ast.List, ast.Tuple)):
            for element in targets_node.elts:
                if not isinstance(element, ast.Dict):
                    continue
                rp = _dict_entries(element).get("RetryPolicy") or {}
                if rp.get("MaximumRetryAttempts") not in (None, 0):
                    offenders.append(rp.get("MaximumRetryAttempts"))
    assert offenders == [], f"non-zero async retry attempts configured: {offenders}"
