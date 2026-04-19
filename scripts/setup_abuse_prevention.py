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
CMK_ARN = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/66c32010-5752-4b1d-8efe-bc317a44cb23"
API_NAME = "solace-api-gw"

ddb = boto3.client("dynamodb", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)

NONCE_TABLE = "solace-intake-nonces"
ROUTE_THROTTLES = {
    # Per-identity quota + blocklist do the cost-bounding; the API-GW layer just
    # has to stay out of the way of legitimate demos. 0.5rps was 429ing real users.
    "POST /api/{hospital_id}/intake":            {"rps": 5.0, "burst": 15},
    "POST /api/{hospital_id}/transcribe":        {"rps": 5.0, "burst": 15},
    "POST /api/{hospital_id}/scan-insurance":    {"rps": 5.0, "burst": 15},
    "POST /api/{hospital_id}/start-intake":      {"rps": 5.0, "burst": 25},
    "GET /api/{hospital_id}/public-patients/{patient_id}": {"rps": 10.0, "burst": 40},
}

EXTRA_TABLES = [
    ("solace-quotas", "bucket_key", None),
    ("solace-intake-nonces", "nonce", "ttl"),
    ("solace-idempotency", "key", "ttl"),
    ("solace-blocklist", "identity", "ttl"),
]


def ensure_nonce_table() -> None:
    print("DynamoDB table:")
    try:
        ddb.describe_table(TableName=NONCE_TABLE)
        print(f"  [ok]    {NONCE_TABLE}")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    ddb.create_table(
        TableName=NONCE_TABLE,
        BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "nonce", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "nonce", "AttributeType": "S"}],
        SSESpecification={"Enabled": True, "SSEType": "KMS", "KMSMasterKeyId": CMK_ARN},
    )
    print(f"  [create] {NONCE_TABLE}")
    ddb.get_waiter("table_exists").wait(TableName=NONCE_TABLE)
    ddb.update_time_to_live(
        TableName=NONCE_TABLE,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )
    print("  [ok]    TTL enabled")


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
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    ensure_nonce_table()
    apply_throttles()
    print("\nDone.")


if __name__ == "__main__":
    main()
