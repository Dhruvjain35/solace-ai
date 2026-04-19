"""Deploy Solace to Lambda + API Gateway + EventBridge. Idempotent."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
ROLE_NAME = "solace-lambda-exec"
FUNCTION_NAME = "solace-api"
API_NAME = "solace-api-gw"
RULE_NAME = "solace-warmer"
DEPLOY_BUCKET = f"solace-lambda-deploy-{ACCOUNT}"
ZIP_KEY = "solace-lambda.zip"
ZIP_PATH = Path(__file__).resolve().parents[1] / "build" / "solace-lambda.zip"
CMK_ARN = (
    f"arn:aws:kms:{REGION}:{ACCOUNT}:key/66c32010-5752-4b1d-8efe-bc317a44cb23"
)
MEDIA_BUCKET = f"solace-media-{ACCOUNT}"

iam = boto3.client("iam")
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
events = boto3.client("events", region_name=REGION)


# ---------- deploy bucket ----------
def ensure_deploy_bucket() -> None:
    try:
        s3.head_bucket(Bucket=DEPLOY_BUCKET)
        print(f"  [ok]    bucket {DEPLOY_BUCKET}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            if REGION == "us-east-1":
                s3.create_bucket(Bucket=DEPLOY_BUCKET)
            else:
                s3.create_bucket(
                    Bucket=DEPLOY_BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": REGION},
                )
            print(f"  [create] bucket {DEPLOY_BUCKET}")
        else:
            raise
    s3.put_public_access_block(
        Bucket=DEPLOY_BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )


def upload_zip() -> str:
    assert ZIP_PATH.exists(), f"build artifact missing: {ZIP_PATH} — run build_lambda.sh first"
    s3.upload_file(str(ZIP_PATH), DEPLOY_BUCKET, ZIP_KEY)
    print(f"  [ok]    uploaded s3://{DEPLOY_BUCKET}/{ZIP_KEY}")
    return ZIP_KEY


def upload_models() -> None:
    """Push gzipped LightGBM fold models to S3 for Lambda cold-start fetch."""
    models_dir = Path(__file__).resolve().parents[1] / "backend" / "models"
    for gz in sorted(models_dir.glob("lgbm_fold*.txt.gz")):
        key = f"models/{gz.name}"
        s3.upload_file(str(gz), DEPLOY_BUCKET, key)
        mb = gz.stat().st_size / 1e6
        print(f"  [ok]    s3://{DEPLOY_BUCKET}/{key} ({mb:.1f} MB)")


# ---------- IAM role ----------
def ensure_role() -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    try:
        resp = iam.get_role(RoleName=ROLE_NAME)
        print(f"  [ok]    role {ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        resp = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Solace Lambda execution role",
            Tags=[{"Key": "project", "Value": "solace"}],
        )
        print(f"  [create] role {ROLE_NAME}")
        time.sleep(8)  # IAM propagation

    # Managed policy: CloudWatch logs
    iam.attach_role_policy(
        RoleName=ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
    )

    # Scoped inline policy
    inline = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadSolaceSecrets",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:solace/api-keys*",
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:solace/clinician-auth*",
                ],
            },
            {
                "Sid": "UseSolaceKMS",
                "Effect": "Allow",
                "Action": ["kms:Decrypt", "kms:GenerateDataKey"],
                "Resource": CMK_ARN,
            },
            {
                "Sid": "SolaceDynamo",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:DescribeTable",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-patients",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-patients/index/*",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-hospitals",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-prescriptions",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-notes",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-clinicians",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-clinicians/index/*",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-audit-log",
                    f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/solace-audit-log/index/*",
                ],
            },
            {
                "Sid": "SolaceMediaS3",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                "Resource": f"arn:aws:s3:::{MEDIA_BUCKET}/*",
            },
            {
                "Sid": "SolaceMediaS3List",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": f"arn:aws:s3:::{MEDIA_BUCKET}",
            },
            {
                "Sid": "SolaceModelS3",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::{DEPLOY_BUCKET}/models/*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME, PolicyName="solace-app", PolicyDocument=json.dumps(inline)
    )
    print("  [ok]    inline policy attached")
    return resp["Role"]["Arn"]


# ---------- Lambda function ----------
def ensure_function(role_arn: str) -> str:
    env = {
        "Variables": {
            "SOLACE_MODE": "aws",
            "AWS_SECRET_NAME": "solace/api-keys",
            "DYNAMODB_TABLE_PATIENTS": "solace-patients",
            "DYNAMODB_TABLE_HOSPITALS": "solace-hospitals",
            "DYNAMODB_TABLE_PRESCRIPTIONS": "solace-prescriptions",
            "DYNAMODB_TABLE_NOTES": "solace-notes",
            "S3_BUCKET_MEDIA": MEDIA_BUCKET,
            "SOLACE_MODELS_BUCKET": DEPLOY_BUCKET,
            "LD_LIBRARY_PATH": "/var/task/lib:/var/task:/opt/lib:/var/runtime:/usr/lib64:/lib64",
            "DEMO_HOSPITAL_ID": "demo",
            "DEMO_HOSPITAL_NAME": "Solace Demo Hospital",
            "ELEVENLABS_VOICE_ID": "21m00Tcm4TlvDq8ikWAM",
        }
    }
    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        print(f"  [update] {FUNCTION_NAME}")
        lam.update_function_code(
            FunctionName=FUNCTION_NAME,
            S3Bucket=DEPLOY_BUCKET,
            S3Key=ZIP_KEY,
            Publish=True,
        )
        # Wait for update to complete
        lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Role=role_arn,
            Handler="main.handler",
            Runtime="python3.12",
            Timeout=60,
            MemorySize=2048,
            Environment=env,
        )
        lam.get_waiter("function_updated").wait(FunctionName=FUNCTION_NAME)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"  [create] {FUNCTION_NAME}")
        lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="main.handler",
            Code={"S3Bucket": DEPLOY_BUCKET, "S3Key": ZIP_KEY},
            Timeout=60,
            MemorySize=2048,
            Environment=env,
            Tags={"project": "solace"},
            Publish=True,
        )
        lam.get_waiter("function_active").wait(FunctionName=FUNCTION_NAME)

    arn = lam.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]
    print(f"  [ok]    arn: {arn}")
    return arn


# ---------- API Gateway HTTP API ----------
def ensure_api(lambda_arn: str) -> str:
    # Find or create the API
    apis = apigw.get_apis()["Items"]
    api = next((a for a in apis if a["Name"] == API_NAME), None)
    if api is None:
        print(f"  [create] api {API_NAME}")
        api = apigw.create_api(
            Name=API_NAME,
            ProtocolType="HTTP",
            CorsConfiguration={
                "AllowOrigins": ["*"],
                "AllowMethods": ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                "AllowHeaders": [
                    "content-type",
                    "x-clinician-pin",
                    "accept",
                    "authorization",
                ],
                "MaxAge": 300,
            },
            Tags={"project": "solace"},
        )
    else:
        print(f"  [ok]    api exists: {api['ApiId']}")
        apigw.update_api(
            ApiId=api["ApiId"],
            CorsConfiguration={
                "AllowOrigins": ["*"],
                "AllowMethods": ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                "AllowHeaders": [
                    "content-type",
                    "x-clinician-pin",
                    "accept",
                    "authorization",
                ],
                "MaxAge": 300,
            },
        )
    api_id = api["ApiId"]
    endpoint = api.get("ApiEndpoint") or apigw.get_api(ApiId=api_id)["ApiEndpoint"]

    # Integration
    integrations = apigw.get_integrations(ApiId=api_id)["Items"]
    integration = next(
        (i for i in integrations if i.get("IntegrationUri") == lambda_arn), None
    )
    if integration is None:
        integration = apigw.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationUri=lambda_arn,
            IntegrationMethod="POST",
            PayloadFormatVersion="2.0",
        )
    integration_id = integration["IntegrationId"]

    # Default route
    routes = apigw.get_routes(ApiId=api_id)["Items"]
    default = next((r for r in routes if r["RouteKey"] == "$default"), None)
    if default is None:
        apigw.create_route(
            ApiId=api_id,
            RouteKey="$default",
            Target=f"integrations/{integration_id}",
        )
    else:
        apigw.update_route(
            ApiId=api_id,
            RouteId=default["RouteId"],
            Target=f"integrations/{integration_id}",
        )

    # Auto-deploy stage
    stages = apigw.get_stages(ApiId=api_id)["Items"]
    if not any(s["StageName"] == "$default" for s in stages):
        apigw.create_stage(ApiId=api_id, StageName="$default", AutoDeploy=True)

    # Grant invoke
    statement_id = "apigw-invoke"
    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{ACCOUNT}:{api_id}/*/*",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise

    print(f"  [ok]    endpoint: {endpoint}")
    return endpoint


# ---------- EventBridge warmer ----------
def ensure_warmer(lambda_arn: str) -> None:
    events.put_rule(
        Name=RULE_NAME,
        ScheduleExpression="rate(1 minute)",
        State="ENABLED",
        Description="Keep solace-api Lambda warm for sub-second demos",
    )
    events.put_targets(
        Rule=RULE_NAME,
        Targets=[
            {
                "Id": "solace-lambda",
                "Arn": lambda_arn,
                "Input": json.dumps({"warmup": True}),
            }
        ],
    )
    statement_id = "eventbridge-warmer"
    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:{REGION}:{ACCOUNT}:rule/{RULE_NAME}",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    print(f"  [ok]    rule {RULE_NAME} → ping every 5m")


# ---------- main ----------
def smoke_test() -> bool:
    """Invoke the freshly-deployed Lambda with a synthetic warmup + health request.

    Fails loudly if any transitive import is broken (e.g., scipy submodule whack-a-mole).
    Returns True on success.
    """
    print("Smoke testing /health + warmup path:")
    # Warmup path — touches triage_ml._load() which imports sklearn + scipy + lightgbm
    warm = lam.invoke(
        FunctionName=FUNCTION_NAME,
        Payload=b'{"warmup":true}',
    )
    payload = warm["Payload"].read().decode()
    if warm.get("FunctionError"):
        print(f"  [FAIL] warmup errored: {payload[:500]}")
        return False
    # Parse body — warm handler reports ml_ok / ml_error so broken imports fail deploy
    try:
        import json as _json

        body = _json.loads(_json.loads(payload).get("body", "{}"))
        if not body.get("ml_ok"):
            print(f"  [FAIL] ML pipeline broken: {body.get('ml_error')}")
            return False
        print(f"  [ok]   warmup: ml_ok=True")
    except Exception as e:
        print(f"  [FAIL] couldn't parse warmup body: {e}  raw={payload[:200]}")
        return False

    # /health path — touches the full FastAPI app boot
    import json as _json

    import httpx

    apis = apigw.get_apis()["Items"]
    api = next((a for a in apis if a["Name"] == API_NAME), None)
    if api:
        endpoint = api.get("ApiEndpoint") or apigw.get_api(ApiId=api["ApiId"])["ApiEndpoint"]
        r = httpx.get(f"{endpoint}/health", timeout=30)
        if r.status_code != 200:
            print(f"  [FAIL] /health returned {r.status_code}: {r.text[:300]}")
            return False
        j = r.json()
        print(f"  [ok]   /health: {_json.dumps(j)}")
    return True


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")

    print("Deploy bucket:")
    ensure_deploy_bucket()
    upload_zip()
    upload_models()
    print()

    print("IAM role:")
    role_arn = ensure_role()
    print()

    print("Lambda:")
    lambda_arn = ensure_function(role_arn)
    print()

    print("API Gateway HTTP API:")
    endpoint = ensure_api(lambda_arn)
    print()

    print("EventBridge warmer:")
    ensure_warmer(lambda_arn)
    print()

    if not smoke_test():
        sys.exit("Deploy failed post-flight smoke test — investigate Lambda logs.")
    print()

    print("Done.")
    print(f"  API URL: {endpoint}")
    print(f"  Test:    curl {endpoint}/health")


if __name__ == "__main__":
    main()
