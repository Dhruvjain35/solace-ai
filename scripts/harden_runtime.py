"""Runtime-hardening pass: strong PIN, log retention, API GW throttle, CORS scoping.

Pass --rotate to generate a new PIN. Otherwise PIN is untouched (safe re-runs).
"""
from __future__ import annotations

import json
import secrets
import string
import sys

import boto3

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
SECRET_NAME = "solace/api-keys"
FUNCTION_NAME = "solace-api"
API_NAME = "solace-api-gw"
LOG_GROUP = f"/aws/lambda/{FUNCTION_NAME}"
AMPLIFY_APP_ID = "d2gsbjipp9quan"
AMPLIFY_ORIGIN = f"https://solace.{AMPLIFY_APP_ID}.amplifyapp.com"

sm = boto3.client("secretsmanager", region_name=REGION)
logs = boto3.client("logs", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
ddb = boto3.resource("dynamodb", region_name=REGION)


def rotate_pin() -> str:
    """Generate 16-char alphanumeric PIN, put it in Secrets Manager AND the hospital record."""
    alphabet = string.ascii_letters + string.digits
    pin = "".join(secrets.choice(alphabet) for _ in range(16))

    current = json.loads(sm.get_secret_value(SecretId=SECRET_NAME)["SecretString"])
    current["DEMO_CLINICIAN_PIN"] = pin
    sm.update_secret(SecretId=SECRET_NAME, SecretString=json.dumps(current))
    print("  [ok] Secrets Manager updated with new PIN")

    ddb.Table("solace-hospitals").update_item(
        Key={"hospital_id": "demo"},
        UpdateExpression="SET clinician_pin = :p",
        ExpressionAttributeValues={":p": pin},
    )
    print("  [ok] demo hospital record updated with new PIN")
    return pin


def set_log_retention(days: int) -> None:
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
        print(f"  [create] log group {LOG_GROUP}")
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=days)
    print(f"  [ok] retention = {days}d on {LOG_GROUP}")


def get_api_id() -> str:
    apis = apigw.get_apis()["Items"]
    api = next(a for a in apis if a["Name"] == API_NAME)
    return api["ApiId"]


def scope_cors(api_id: str) -> None:
    # Open CORS to any origin — security is enforced at WAF (rate-limit + OWASP
    # common rule set) + per-identity quota + JWT auth. Locking CORS to a single
    # host breaks multi-env testing (Amplify + Vercel + local dev tunnels) with
    # no real security upside for a public API.
    apigw.update_api(
        ApiId=api_id,
        CorsConfiguration={
            "AllowOrigins": ["*"],
            "AllowMethods": ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            "AllowHeaders": [
                "content-type",
                "x-clinician-pin",
                "accept",
                "authorization",
            ],
            "ExposeHeaders": [],
            "MaxAge": 300,
            "AllowCredentials": False,
        },
    )
    print(f"  [ok] CORS locked to {AMPLIFY_ORIGIN}")


def set_throttle(api_id: str) -> None:
    """API Gateway default-stage throttle. Sized for ~50 concurrent patients per
    hospital — peak burst is the whole waiting room finishing intake at once.
    Per-route throttles in setup_abuse_prevention.py are stricter for the few
    routes that actually need bounding; the stage default is the floor below
    which nothing should rate-limit."""
    apigw.update_stage(
        ApiId=api_id,
        StageName="$default",
        DefaultRouteSettings={
            "ThrottlingBurstLimit": 800,
            "ThrottlingRateLimit": 400.0,
        },
    )
    print(f"  [ok] throttle: 400 req/s steady, 800 burst on $default stage")


def main() -> None:
    rotate = "--rotate" in sys.argv
    if rotate:
        print("Rotating clinician PIN:")
        pin = rotate_pin()
    else:
        print("Skipping PIN rotation (pass --rotate to generate a new one)")
        pin = None
    print()
    print(f"CloudWatch log retention:")
    set_log_retention(14)
    print()
    api_id = get_api_id()
    print(f"API Gateway ({api_id}) CORS + throttling:")
    scope_cors(api_id)
    set_throttle(api_id)
    print()
    if pin:
        print("=" * 50)
        print(f"NEW CLINICIAN PIN: {pin}")
        print("=" * 50)
        print("Save this — plaintext lives here once.")


if __name__ == "__main__":
    main()
