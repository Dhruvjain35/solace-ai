"""Pin Lambda to zero cold-starts for the demo.

- Publishes a new version of solace-api
- Creates/updates alias `live` → that version
- Sets provisioned concurrency = 1 on the alias
- Points API Gateway + EventBridge warmer at the alias
"""
from __future__ import annotations

import time
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
FUNCTION = "solace-api"
ALIAS = "live"
API_NAME = "solace-api-gw"
RULE_NAME = "solace-warmer"

lam = boto3.client("lambda", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
events = boto3.client("events", region_name=REGION)


def publish_and_alias() -> str:
    lam.get_waiter("function_updated").wait(FunctionName=FUNCTION)
    v = lam.publish_version(FunctionName=FUNCTION)["Version"]
    print(f"  [ok]   published version {v}")

    try:
        lam.update_alias(FunctionName=FUNCTION, Name=ALIAS, FunctionVersion=v)
        print(f"  [ok]   alias {ALIAS} → v{v}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        lam.create_alias(FunctionName=FUNCTION, Name=ALIAS, FunctionVersion=v)
        print(f"  [new]  alias {ALIAS} → v{v}")
    return v


def set_provisioned(pc: int = 1) -> None:
    try:
        lam.put_provisioned_concurrency_config(
            FunctionName=FUNCTION,
            Qualifier=ALIAS,
            ProvisionedConcurrentExecutions=pc,
        )
        print(f"  [ok]   requested provisioned concurrency = {pc} on alias {ALIAS}")
    except ClientError as e:
        print(f"  [warn] {e}")
        return

    # Poll until Ready (usually 1-3 min, up to 10)
    deadline = time.time() + 600
    while time.time() < deadline:
        resp = lam.get_provisioned_concurrency_config(FunctionName=FUNCTION, Qualifier=ALIAS)
        status = resp["Status"]
        print(f"    ...{status}  available={resp.get('AvailableProvisionedConcurrentExecutions', 0)}/{pc}")
        if status == "READY":
            print("  [ok]   provisioned concurrency READY — zero cold starts")
            return
        if status == "FAILED":
            print(f"  [fail] {resp.get('StatusReason')}")
            return
        time.sleep(15)
    print("  [warn] timed out waiting for READY; check AWS console")


def _aliased_arn() -> str:
    return f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}:{ALIAS}"


def point_apigw_at_alias() -> None:
    apis = apigw.get_apis()["Items"]
    api = next(a for a in apis if a["Name"] == API_NAME)
    api_id = api["ApiId"]
    target_arn = _aliased_arn()

    integrations = apigw.get_integrations(ApiId=api_id)["Items"]
    for i in integrations:
        uri = i.get("IntegrationUri", "")
        if FUNCTION not in uri:
            continue
        if uri == target_arn:
            print(f"  [ok]   integration already on alias")
            continue
        apigw.update_integration(
            ApiId=api_id,
            IntegrationId=i["IntegrationId"],
            IntegrationUri=target_arn,
        )
        print(f"  [ok]   integration → {target_arn}")

    # Grant invoke on the alias from API GW
    statement_id = "apigw-invoke-live"
    try:
        lam.add_permission(
            FunctionName=FUNCTION,
            Qualifier=ALIAS,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api_id}/*/*",
        )
        print(f"  [ok]   invoke permission granted to API GW on alias")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise


def point_warmer_at_alias() -> None:
    events.put_targets(
        Rule=RULE_NAME,
        Targets=[
            {
                "Id": "solace-lambda",
                "Arn": _aliased_arn(),
                "Input": '{"warmup": true}',
            }
        ],
    )
    statement_id = "eventbridge-warmer-live"
    try:
        lam.add_permission(
            FunctionName=FUNCTION,
            Qualifier=ALIAS,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{RULE_NAME}",
        )
        print(f"  [ok]   invoke permission granted to EventBridge on alias")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise


def main() -> None:
    print("Lambda alias + provisioned concurrency:")
    publish_and_alias()
    set_provisioned(1)
    print()
    print("API Gateway:")
    point_apigw_at_alias()
    print()
    print("EventBridge warmer:")
    point_warmer_at_alias()
    print()
    print(f"Done. Alias ARN: {_aliased_arn()}")


if __name__ == "__main__":
    main()
