"""Section 2 infra: intake-nonce DDB table + per-route API Gateway throttling.

Per-route throttle keys:
  POST /api/{hospital_id}/intake             — 30 req/min (0.5 rps) burst 5
  POST /api/{hospital_id}/transcribe         — 30 req/min (0.5 rps) burst 5
  POST /api/{hospital_id}/scan-insurance     — 30 req/min (0.5 rps) burst 5
  POST /api/{hospital_id}/start-intake       — 60 req/min (1 rps)   burst 10
  GET  /api/{hospital_id}/public-patients/{patient_id} — 120 req/min (2 rps) burst 20
"""
from __future__ import annotations

import json
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
API_NAME = "solace-api-gw"

ddb = boto3.client("dynamodb", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)
kms = boto3.client("kms", region_name=REGION)


def _resolve_cmk_arn() -> str:
    """Resolve the Solace CMK ARN via alias — avoids hardcoding a key UUID."""
    try:
        resp = kms.describe_key(KeyId="alias/solace")
        return resp["KeyMetadata"]["Arn"]
    except Exception as e:  # noqa: BLE001
        print(f"  [warn]  Could not resolve alias/solace ({e}), using default encryption.")
        return ""


CMK_ARN: str = ""  # populated in main()

NONCE_TABLE = "solace-intake-nonces"
ROUTE_THROTTLES = {
    # Sized for ~50 concurrent patients per hospital. The per-identity quota +
    # blocklist do the abuse-bounding; this layer just needs to stay out of the
    # way during a peak (whole waiting room hitting submit at once). The earlier
    # 5 rps was tripping during multi-patient demos.
    "POST /api/{hospital_id}/intake":            {"rps": 100.0, "burst": 300},
    "POST /api/{hospital_id}/transcribe":        {"rps": 100.0, "burst": 300},
    "POST /api/{hospital_id}/scan-insurance":    {"rps": 50.0,  "burst": 150},
    "POST /api/{hospital_id}/start-intake":      {"rps": 100.0, "burst": 300},
    "GET /api/{hospital_id}/public-patients/{patient_id}": {"rps": 200.0, "burst": 500},
}

EXTRA_TABLES = [
    ("solace-quotas", "bucket_key", None),
    ("solace-intake-nonces", "nonce", "ttl"),
    ("solace-idempotency", "key", "ttl"),
    ("solace-blocklist", "identity", "ttl"),
]


def _sse_spec() -> dict:
    """SSE specification using the Solace CMK if available."""
    if CMK_ARN:
        return {"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": CMK_ARN}
    return {}


def _ensure_table(table_name: str, hash_key: str, ttl_attr: str | None) -> None:
    """Create a single-key DDB table with CMK encryption if it doesn't exist."""
    try:
        ddb.describe_table(TableName=table_name)
        print(f"  [ok]    {table_name}")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    kwargs: dict = {
        "TableName": table_name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": hash_key, "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": hash_key, "AttributeType": "S"}],
    }
    sse = _sse_spec()
    if sse:
        kwargs["SSESpecification"] = sse
    ddb.create_table(**kwargs)
    print(f"  [create] {table_name}")
    ddb.get_waiter("table_exists").wait(TableName=table_name)
    if ttl_attr:
        try:
            ddb.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": ttl_attr},
            )
            print(f"  [ok]    TTL on {table_name}.{ttl_attr}")
        except ClientError as e:
            if "TimeToLive is already enabled" not in str(e):
                print(f"  [warn]  TTL on {table_name}: {e}")


def ensure_abuse_tables() -> None:
    """Create all abuse-prevention DynamoDB tables with CMK encryption."""
    print("DynamoDB abuse-prevention tables:")
    for table_name, hash_key, ttl_attr in EXTRA_TABLES:
        _ensure_table(table_name, hash_key, ttl_attr)


def _find_api() -> str:
    apis = apigw.get_apis()["Items"]
    return next(a for a in apis if a["Name"] == API_NAME)["ApiId"]


def _find_or_create_route(api_id: str, route_key: str) -> str | None:
    routes = apigw.get_routes(ApiId=api_id)["Items"]
    existing = next((r for r in routes if r["RouteKey"] == route_key), None)
    if existing:
        return existing["RouteId"]
    # Look up the default integration so we can attach this route to the same Lambda
    integrations = apigw.get_integrations(ApiId=api_id)["Items"]
    if not integrations:
        print(f"  [warn] no integrations on api; can't create route {route_key}")
        return None
    integration_id = integrations[0]["IntegrationId"]
    resp = apigw.create_route(
        ApiId=api_id,
        RouteKey=route_key,
        Target=f"integrations/{integration_id}",
    )
    print(f"  [create] route {route_key}")
    return resp["RouteId"]


def apply_throttles() -> None:
    print("\nAPI Gateway per-route throttling:")
    api_id = _find_api()
    stage_settings = {}
    for route_key, limits in ROUTE_THROTTLES.items():
        _find_or_create_route(api_id, route_key)
        stage_settings[route_key] = {
            "ThrottlingRateLimit": limits["rps"],
            "ThrottlingBurstLimit": limits["burst"],
            "DetailedMetricsEnabled": False,
        }
    # Stage-level update — bulk upsert all per-route settings at once
    apigw.update_stage(
        ApiId=api_id,
        StageName="$default",
        RouteSettings=stage_settings,
    )
    for route_key, limits in ROUTE_THROTTLES.items():
        print(f"  [ok] {route_key}  → {limits['rps']} rps, burst {limits['burst']}")


def main() -> None:
    global CMK_ARN
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("Resolving Solace CMK:")
    CMK_ARN = _resolve_cmk_arn()
    if CMK_ARN:
        print(f"  [cmk]   {CMK_ARN}")
    print()
    ensure_abuse_tables()
    apply_throttles()
    print("\nDone.")


if __name__ == "__main__":
    main()
