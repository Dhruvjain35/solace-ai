"""Attach AWS WAFv2 to the API Gateway stage.

Rules (evaluated in order; first-match wins):
  1. AWS-AWSManagedRulesAmazonIpReputationList — drops known botnet / scanner IPs
  2. AWS-AWSManagedRulesKnownBadInputsRuleSet  — blocks exploit patterns in input
  3. AWS-AWSManagedRulesCommonRuleSet          — OWASP Top-10 baseline
  4. SolaceRateLimit                            — 300 req / 5-min per IP (aggregate)

Our in-app defenses (per-route throttle, identity quota, blocklist) remain
downstream. WAF is the first line; it's where we cut traffic from dirty IPs
before they even hit the Lambda.
"""
from __future__ import annotations

import json
import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
WAF_NAME = "solace-waf"
API_NAME = "solace-api-gw"
STAGE = "$default"

waf = boto3.client("wafv2", region_name=REGION)
apigw = boto3.client("apigatewayv2", region_name=REGION)


def _find_api_stage_arn() -> str:
    apis = apigw.get_apis()["Items"]
    api = next(a for a in apis if a["Name"] == API_NAME)
    # WAF-compatible stage ARN format
    return f"arn:aws:apigateway:{REGION}::/apis/{api['ApiId']}/stages/{STAGE}"


def build_rules() -> list[dict]:
    return [
        {
            "Name": "AWS-AWSManagedRulesAmazonIpReputationList",
            "Priority": 10,
            "OverrideAction": {"None": {}},
            "Statement": {
                "ManagedRuleGroupStatement": {
                    "VendorName": "AWS",
                    "Name": "AWSManagedRulesAmazonIpReputationList",
                }
            },
            "VisibilityConfig": {
                "SampledRequestsEnabled": True,
                "CloudWatchMetricsEnabled": True,
                "MetricName": "solace-waf-ip-reputation",
            },
        },
        {
            "Name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
            "Priority": 20,
            "OverrideAction": {"None": {}},
            "Statement": {
                "ManagedRuleGroupStatement": {
                    "VendorName": "AWS",
                    "Name": "AWSManagedRulesKnownBadInputsRuleSet",
                }
            },
            "VisibilityConfig": {
                "SampledRequestsEnabled": True,
                "CloudWatchMetricsEnabled": True,
                "MetricName": "solace-waf-bad-inputs",
            },
        },
        {
            "Name": "AWS-AWSManagedRulesCommonRuleSet",
            "Priority": 30,
            "OverrideAction": {"None": {}},
            "Statement": {
                "ManagedRuleGroupStatement": {
                    "VendorName": "AWS",
                    "Name": "AWSManagedRulesCommonRuleSet",
                    "RuleActionOverrides": [
                        # SizeRestrictions_BODY would block our ~8MB audio uploads; we
                        # already enforce size caps + magic-byte + decode in-process.
                        {"Name": "SizeRestrictions_BODY",
                         "ActionToUse": {"Count": {}}},
                    ],
                }
            },
            "VisibilityConfig": {
                "SampledRequestsEnabled": True,
                "CloudWatchMetricsEnabled": True,
                "MetricName": "solace-waf-common",
            },
        },
        {
            "Name": "SolaceRateLimit",
            "Priority": 100,
            "Action": {"Block": {}},
            "Statement": {
                "RateBasedStatement": {
                    "Limit": 300,
                    "EvaluationWindowSec": 300,  # 5 min
                    "AggregateKeyType": "IP",
                }
            },
            "VisibilityConfig": {
                "SampledRequestsEnabled": True,
                "CloudWatchMetricsEnabled": True,
                "MetricName": "solace-waf-rate-limit",
            },
        },
    ]


def ensure_web_acl() -> tuple[str, str]:
    # REGIONAL scope is required for API Gateway (HTTP API + REST)
    existing = waf.list_web_acls(Scope="REGIONAL")["WebACLs"]
    hit = next((w for w in existing if w["Name"] == WAF_NAME), None)
    rules = build_rules()
    visibility = {
        "SampledRequestsEnabled": True,
        "CloudWatchMetricsEnabled": True,
        "MetricName": "solace-waf",
    }
    if hit:
        print(f"  [ok]    WebACL {WAF_NAME} exists → updating rules")
        # Need the LockToken for updates
        detail = waf.get_web_acl(Name=WAF_NAME, Scope="REGIONAL", Id=hit["Id"])
        waf.update_web_acl(
            Name=WAF_NAME,
            Scope="REGIONAL",
            Id=hit["Id"],
            DefaultAction={"Allow": {}},
            Rules=rules,
            VisibilityConfig=visibility,
            LockToken=detail["LockToken"],
        )
        return hit["ARN"], hit["Id"]
    resp = waf.create_web_acl(
        Name=WAF_NAME,
        Scope="REGIONAL",
        DefaultAction={"Allow": {}},
        Description="Solace API edge defenses - OWASP + IP reputation + rate limit",
        Rules=rules,
        VisibilityConfig=visibility,
        Tags=[{"Key": "project", "Value": "solace"}],
    )
    print(f"  [create] WebACL {WAF_NAME}")
    return resp["Summary"]["ARN"], resp["Summary"]["Id"]


def associate(web_acl_arn: str) -> None:
    resource_arn = _find_api_stage_arn()
    try:
        waf.associate_web_acl(WebACLArn=web_acl_arn, ResourceArn=resource_arn)
        print(f"  [ok]    associated with {resource_arn}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if "already associated" in str(e).lower() or code == "WAFAssociatedItemException":
            print(f"  [ok]    already associated")
        else:
            raise


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("WAFv2 webACL:")
    arn, _ = ensure_web_acl()
    print(f"  {arn}\n")
    print("API Gateway association:")
    associate(arn)
    print("\nDone. Expect 1-2 minutes for rules to propagate before they apply.")


if __name__ == "__main__":
    main()
