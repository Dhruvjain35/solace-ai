"""Deploy Solace Lambda as a container image on ARM64.

Runs after `docker build -f Dockerfile.lambda -t solace-lambda:latest --platform linux/arm64 .`
Creates/updates the ECR repo, pushes the image, recreates the Lambda in image mode,
and re-points API Gateway + EventBridge at the new function.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
REPO = "solace-api"
TAG = "latest"
FUNCTION = "solace-api"
ALIAS = None  # unused — we put LIVE function on $LATEST
ROLE_NAME = "solace-lambda-exec"
API_NAME = "solace-api-gw"
RULE_NAME = "solace-warmer"
MEDIA_BUCKET = f"solace-media-{ACCOUNT}"
CMK_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/66c32010-5752-4b1d-8efe-bc317a44cb23"

ecr = boto3.client("ecr", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
events = boto3.client("events", region_name=REGION)
iam = boto3.client("iam")


def ensure_repo() -> str:
    try:
        r = ecr.describe_repositories(repositoryNames=[REPO])["repositories"][0]
        print(f"  [ok]    repo exists")
    except ClientError as e:
        if e.response["Error"]["Code"] != "RepositoryNotFoundException":
            raise
        r = ecr.create_repository(
            repositoryName=REPO,
            imageTagMutability="MUTABLE",
            imageScanningConfiguration={"scanOnPush": True},
            encryptionConfiguration={"encryptionType": "KMS", "kmsKey": CMK_ARN},
        )["repository"]
        print(f"  [create] repo")
    return r["repositoryUri"]


def push_image(repo_uri: str) -> str:
    image = f"{repo_uri}:{TAG}"
    print(f"  [tag]    solace-lambda:latest → {image}")
    subprocess.run(["docker", "tag", "solace-lambda:latest", image], check=True)

    # ECR auth via boto → docker login
    auth = ecr.get_authorization_token()["authorizationData"][0]
    token = base64.b64decode(auth["authorizationToken"]).decode()
    user, password = token.split(":", 1)
    endpoint = auth["proxyEndpoint"]
    print(f"  [login]  {endpoint}")
    subprocess.run(
        ["docker", "login", "-u", user, "--password-stdin", endpoint],
        input=password.encode(),
        check=True,
    )

    print(f"  [push]   {image} (takes a minute for a fresh ~1.8GB image)")
    subprocess.run(["docker", "push", image], check=True)
    digest = ecr.describe_images(
        repositoryName=REPO, imageIds=[{"imageTag": TAG}]
    )["imageDetails"][0]["imageDigest"]
    immutable_uri = f"{repo_uri}@{digest}"
    print(f"  [ok]     {immutable_uri}")
    return immutable_uri


def recreate_function(image_uri: str) -> str:
    role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    # Delete the existing zip-mode function (can't change package type in place)
    try:
        current = lam.get_function(FunctionName=FUNCTION)
        pkg_type = current["Configuration"].get("PackageType", "Zip")
        if pkg_type == "Zip":
            print(f"  [delete] existing Zip-mode function")
            lam.delete_function(FunctionName=FUNCTION)
            time.sleep(5)
        else:
            # Already image mode — just update code
            print(f"  [update] existing Image-mode function → new digest")
            lam.update_function_code(FunctionName=FUNCTION, ImageUri=image_uri, Publish=True)
            lam.get_waiter("function_updated").wait(FunctionName=FUNCTION)
            return lam.get_function(FunctionName=FUNCTION)["Configuration"]["FunctionArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    env = {
        "Variables": {
            "SOLACE_MODE": "aws",
            "AWS_SECRET_NAME": "solace/api-keys",
            "DYNAMODB_TABLE_PATIENTS": "solace-patients",
            "DYNAMODB_TABLE_HOSPITALS": "solace-hospitals",
            "DYNAMODB_TABLE_PRESCRIPTIONS": "solace-prescriptions",
            "DYNAMODB_TABLE_NOTES": "solace-notes",
            "S3_BUCKET_MEDIA": MEDIA_BUCKET,
            # No SOLACE_MODELS_BUCKET — models are baked into the image
            "CLAUDE_PROVIDER": "direct",  # flip to "bedrock" after AWS BAA + model access
            "DEMO_HOSPITAL_ID": "demo",
            "DEMO_HOSPITAL_NAME": "Solace Demo Hospital",
            "ELEVENLABS_VOICE_ID": "21m00Tcm4TlvDq8ikWAM",
        }
    }
    print(f"  [create] {FUNCTION} as container image on arm64")
    lam.create_function(
        FunctionName=FUNCTION,
        PackageType="Image",
        Code={"ImageUri": image_uri},
        Role=role_arn,
        Architectures=["arm64"],
        Timeout=60,
        MemorySize=2048,
        Environment=env,
        Tags={"project": "solace"},
        Publish=True,
    )
    lam.get_waiter("function_active").wait(FunctionName=FUNCTION)
    return lam.get_function(FunctionName=FUNCTION)["Configuration"]["FunctionArn"]


def point_apigw(lambda_arn: str) -> str:
    apis = apigw.get_apis()["Items"]
    api = next(a for a in apis if a["Name"] == API_NAME)
    api_id = api["ApiId"]
    for i in apigw.get_integrations(ApiId=api_id)["Items"]:
        apigw.update_integration(
            ApiId=api_id, IntegrationId=i["IntegrationId"], IntegrationUri=lambda_arn
        )
    # Reattach invoke permission (delete_function wiped it)
    try:
        lam.add_permission(
            FunctionName=FUNCTION, StatementId="apigw-invoke",
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api_id}/*/*",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    endpoint = api.get("ApiEndpoint") or apigw.get_api(ApiId=api_id)["ApiEndpoint"]
    print(f"  [ok]     {endpoint}")
    return endpoint


def point_warmer(lambda_arn: str) -> None:
    events.put_targets(
        Rule=RULE_NAME,
        Targets=[{"Id": "solace-lambda", "Arn": lambda_arn, "Input": '{"warmup": true}'}],
    )
    try:
        lam.add_permission(
            FunctionName=FUNCTION, StatementId="eventbridge-warmer",
            Action="lambda:InvokeFunction", Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{RULE_NAME}",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    print("  [ok]     warmer re-pointed + permission reattached")


def smoke() -> bool:
    print("Smoke test:")
    resp = lam.invoke(FunctionName=FUNCTION, Payload=b'{"warmup":true}')
    if resp.get("FunctionError"):
        err = resp["Payload"].read().decode()
        print(f"  [FAIL] {err[:500]}")
        return False
    body = json.loads(json.loads(resp["Payload"].read().decode()).get("body", "{}"))
    ok = body.get("ml_ok") is True
    print(f"  ml_ok={ok}  ml_error={body.get('ml_error')}")
    return ok


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")

    print("ECR repo:")
    repo_uri = ensure_repo()
    print()

    print("Push image:")
    image_uri = push_image(repo_uri)
    print()

    print("Lambda (container mode, arm64):")
    lambda_arn = recreate_function(image_uri)
    print(f"  arn: {lambda_arn}")
    print()

    print("API Gateway → container Lambda:")
    endpoint = point_apigw(lambda_arn)
    print()

    print("EventBridge warmer → container Lambda:")
    point_warmer(lambda_arn)
    print()

    if not smoke():
        sys.exit("Container Lambda smoke test failed — check CloudWatch logs.")

    print(f"\nDone. API: {endpoint}")


if __name__ == "__main__":
    main()
