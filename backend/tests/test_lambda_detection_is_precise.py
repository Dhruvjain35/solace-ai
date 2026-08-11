"""SEC-001's deployed-process guard must fire in Lambda and nowhere else.

`assert_deployment_is_configured` refuses to boot a process that is running in
Lambda while SOLACE_MODE is 'local', because in that mode secrets are never
hydrated and clinician JWTs are signed with the dev key committed to this repo.
That guard is correct and load-bearing.

Its *detection* was not. `is_deployed()` treated the presence of
AWS_EXECUTION_ENV as proof of Lambda, and CodeBuild sets that variable too. The
result: every attempt to run the test suite inside CI died at collection with
"Refusing to start: this process is running in AWS Lambda", eight files erroring
before a single test executed.

It went unnoticed for a specific and instructive reason. Commit 9a7fb18 ("ci:
run the tests before building the image") added a pytest phase to buildspec.yml
— but the CodeBuild project was configured with an *inline* buildspec, which
overrides the file in the repository. So the test phase existed in the repo,
looked correct in review, and had never run.

The lesson is the one this codebase keeps relearning, from SEC-002 onward: a
control that is written down is not a control that is in force. This file pins
the detection in both directions, because a guard that is too broad gets removed
by whoever is trying to ship, and then it guards nothing.
"""
from __future__ import annotations

import pytest

from lib import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every case from an environment with no compute markers set."""
    for var in ("AWS_LAMBDA_FUNCTION_NAME", "AWS_LAMBDA_RUNTIME_API",
                "AWS_EXECUTION_ENV", "CODEBUILD_BUILD_ID"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# It must still fire in Lambda. This is the half that matters for security.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("AWS_LAMBDA_FUNCTION_NAME", "solace-api"),
        ("AWS_LAMBDA_RUNTIME_API", "127.0.0.1:9001"),
        ("AWS_EXECUTION_ENV", "AWS_Lambda_python3.12"),
    ],
)
def test_lambda_is_still_detected(monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    assert config.is_deployed() is True, (
        f"{var}={value!r} is Lambda and must be detected — narrowing the check "
        "must not create a way to run a deployed process in local mode"
    )


def test_a_deployed_process_in_local_mode_is_still_refused(monkeypatch):
    """The actual SEC-001 promise, end to end."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    with pytest.raises(RuntimeError, match="Refusing to start"):
        config.assert_deployment_is_configured("local")


def test_a_deployed_process_in_aws_mode_is_allowed(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "solace-api")
    config.assert_deployment_is_configured("aws")  # must not raise


# ---------------------------------------------------------------------------
# It must NOT fire anywhere else. This is the half that broke CI.
# ---------------------------------------------------------------------------

def test_codebuild_is_not_mistaken_for_lambda(monkeypatch):
    """The exact environment that took the build down.

    CodeBuild's AWS_EXECUTION_ENV value is not Lambda's. Presence is not proof;
    the value is.
    """
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_EC2")
    monkeypatch.setenv("CODEBUILD_BUILD_ID", "solace-api-deploy:abc123")
    assert config.is_deployed() is False


def test_the_suite_can_run_in_codebuild(monkeypatch):
    """Collection must not explode. This is what actually failed."""
    monkeypatch.setenv("AWS_EXECUTION_ENV", "AWS_ECS_EC2")
    config.assert_deployment_is_configured("local")  # must not raise


@pytest.mark.parametrize(
    "value",
    ["AWS_ECS_EC2", "AWS_ECS_FARGATE", "CloudShell", "", "AWS_EC2_Instance"],
)
def test_non_lambda_execution_environments_are_not_deployed(monkeypatch, value):
    monkeypatch.setenv("AWS_EXECUTION_ENV", value)
    assert config.is_deployed() is False, (
        f"AWS_EXECUTION_ENV={value!r} is not Lambda"
    )


def test_a_bare_developer_machine_is_not_deployed():
    assert config.is_deployed() is False


# ---------------------------------------------------------------------------
# The prefix match must not be defeatable by something merely similar.
# ---------------------------------------------------------------------------

def test_the_prefix_is_matched_at_the_start_not_anywhere(monkeypatch):
    """A value that merely mentions Lambda is not the Lambda runtime."""
    monkeypatch.setenv("AWS_EXECUTION_ENV", "NotReally_AWS_Lambda_python3.12")
    assert config.is_deployed() is False
