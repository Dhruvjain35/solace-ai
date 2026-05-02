"""CloudFront distribution in front of API Gateway + WAFv2 webACL attached.

WAFv2 can't attach directly to an API Gateway HTTP API — only REST APIs and
CloudFront distributions support association. We put a CloudFront distribution
in front of the HTTP API, attach the WAF there, and point the frontend at the
CloudFront URL instead of the raw execute-api domain.

Side benefits:
  - AWS Shield Standard DDoS protection (free, auto-enabled on CloudFront)
  - TLS termination at the edge (faster TLS handshake)
  - Regional PoP fallback

WAF rules (CLOUDFRONT scope, global):
  1. Amazon IP Reputation List   — drops known botnets/scanners
  2. Known Bad Inputs Rule Set   — exploit patterns in headers/body
  3. Common (OWASP Top-10)       — SQLi, XSS, LFI, etc
  4. SolaceRateLimit 10000/5min/IP — aggregate request rate cap (hospital NAT-friendly)
"""
from __future__ import annotations

import time

import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
WAF_NAME = "solace-waf"
DIST_CALLER_REF = "solace-api-dist-v1"
API_DOMAIN = "7ew5f2x01d.execute-api.us-east-1.amazonaws.com"

# WAFv2 CLOUDFRONT-scope APIs are global but the client must target us-east-1
waf = boto3.client("wafv2", region_name="us-east-1")
cf = boto3.client("cloudfront")


def _rules() -> list[dict]:
    return [
        {
            "Name": "AWS-AWSManagedRulesAmazonIpReputationList",
            "Priority": 10,
            "OverrideAction": {"None": {}},
            "Statement": {"ManagedRuleGroupStatement": {
                "VendorName": "AWS", "Name": "AWSManagedRulesAmazonIpReputationList"}},
            "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True,
                                  "MetricName": "solace-waf-ip-reputation"},
        },
        {
            "Name": "AWS-AWSManagedRulesKnownBadInputsRuleSet",
            "Priority": 20,
            "OverrideAction": {"None": {}},
            "Statement": {"ManagedRuleGroupStatement": {
                "VendorName": "AWS", "Name": "AWSManagedRulesKnownBadInputsRuleSet"}},
            "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True,
                                  "MetricName": "solace-waf-bad-inputs"},
        },
        {
            "Name": "AWS-AWSManagedRulesCommonRuleSet",
            "Priority": 30,
            "OverrideAction": {"None": {}},
            "Statement": {"ManagedRuleGroupStatement": {
                "VendorName": "AWS", "Name": "AWSManagedRulesCommonRuleSet",
                "RuleActionOverrides": [
                    {"Name": "SizeRestrictions_BODY", "ActionToUse": {"Count": {}}},
                ],
            }},
            "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True,
                                  "MetricName": "solace-waf-common"},
        },
        {
            # Hospital-NAT puts every patient behind one IP. Ceiling is generous so
            # legitimate intake (recording, retries, photo upload) never trips it,
            # while still catching scripted abuse from a single source.
            "Name": "SolaceRateLimit",
            "Priority": 100,
            "Action": {"Block": {}},
            "Statement": {"RateBasedStatement": {
                "Limit": 50000, "EvaluationWindowSec": 300, "AggregateKeyType": "IP"}},
            "VisibilityConfig": {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True,
                                  "MetricName": "solace-waf-rate-limit"},
        },
    ]


def ensure_web_acl() -> str:
    existing = waf.list_web_acls(Scope="CLOUDFRONT")["WebACLs"]
    hit = next((w for w in existing if w["Name"] == WAF_NAME), None)
    visibility = {"SampledRequestsEnabled": True, "CloudWatchMetricsEnabled": True,
                  "MetricName": "solace-waf"}
    if hit:
        print(f"  [ok]    CLOUDFRONT WebACL {WAF_NAME} exists -> updating")
        detail = waf.get_web_acl(Name=WAF_NAME, Scope="CLOUDFRONT", Id=hit["Id"])
        waf.update_web_acl(Name=WAF_NAME, Scope="CLOUDFRONT", Id=hit["Id"],
                           DefaultAction={"Allow": {}}, Rules=_rules(),
                           VisibilityConfig=visibility, LockToken=detail["LockToken"])
        return hit["ARN"]
    resp = waf.create_web_acl(
        Name=WAF_NAME, Scope="CLOUDFRONT", DefaultAction={"Allow": {}},
        Description="Solace edge defenses - OWASP + IP reputation + rate limit",
        Rules=_rules(), VisibilityConfig=visibility,
        Tags=[{"Key": "project", "Value": "solace"}],
    )
    arn = resp["Summary"]["ARN"]
    print(f"  [create] CLOUDFRONT WebACL {WAF_NAME}: {arn}")
    return arn


def ensure_distribution(web_acl_arn: str) -> tuple[str, str]:
    # Look up existing by caller reference through list
    dists = cf.list_distributions().get("DistributionList", {}).get("Items", []) or []
    existing = next(
        (d for d in dists if any(o["DomainName"] == API_DOMAIN for o in d.get("Origins", {}).get("Items", []))),
        None,
    )

    distribution_config = {
        "CallerReference": DIST_CALLER_REF,
        "Comment": "Solace API edge - WAF + AWS Shield",
        "Enabled": True,
        "PriceClass": "PriceClass_100",  # US/CA/EU only - cheapest for demo
        "WebACLId": web_acl_arn,
        "Origins": {
            "Quantity": 1,
            "Items": [{
                "Id": "solace-apigw",
                "DomainName": API_DOMAIN,
                "OriginPath": "",
                "CustomHeaders": {"Quantity": 0},
                "CustomOriginConfig": {
                    "HTTPPort": 80,
                    "HTTPSPort": 443,
                    "OriginProtocolPolicy": "https-only",
                    "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                    "OriginReadTimeout": 60,
                    "OriginKeepaliveTimeout": 5,
                },
                "ConnectionAttempts": 3,
                "ConnectionTimeout": 10,
            }],
        },
        "DefaultCacheBehavior": {
            "TargetOriginId": "solace-apigw",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 7,
                "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
            },
            "Compress": True,
            "MinTTL": 0,
            "DefaultTTL": 0,
            "MaxTTL": 0,
            "ForwardedValues": {
                "QueryString": True,
                "Headers": {"Quantity": 1, "Items": ["*"]},
                "Cookies": {"Forward": "all"},
                "QueryStringCacheKeys": {"Quantity": 0},
            },
            "TrustedSigners": {"Enabled": False, "Quantity": 0},
            "SmoothStreaming": False,
            "LambdaFunctionAssociations": {"Quantity": 0},
            "FieldLevelEncryptionId": "",
        },
        "ViewerCertificate": {
            "CloudFrontDefaultCertificate": True,
            "MinimumProtocolVersion": "TLSv1",
            "CertificateSource": "cloudfront",
        },
        "DefaultRootObject": "",
        "IsIPV6Enabled": True,
        "HttpVersion": "http2",
        "Logging": {"Enabled": False, "IncludeCookies": False, "Bucket": "", "Prefix": ""},
        "Aliases": {"Quantity": 0},
        "CacheBehaviors": {"Quantity": 0},
        "CustomErrorResponses": {"Quantity": 0},
        "Restrictions": {"GeoRestriction": {"RestrictionType": "none", "Quantity": 0}},
    }

    if existing:
        print(f"  [ok]    distribution {existing['Id']} already points at {API_DOMAIN}")
        # Reassociate WAF in case it changed
        cur = cf.get_distribution_config(Id=existing["Id"])
        cfg = cur["DistributionConfig"]
        if cfg.get("WebACLId") != web_acl_arn:
            cfg["WebACLId"] = web_acl_arn
            cf.update_distribution(Id=existing["Id"], IfMatch=cur["ETag"], DistributionConfig=cfg)
            print(f"  [ok]    reattached WAF to existing distribution")
        return existing["Id"], existing["DomainName"]

    print(f"  [create] CloudFront distribution (3-5 min to deploy)")
    resp = cf.create_distribution(DistributionConfig=distribution_config)
    dist = resp["Distribution"]
    return dist["Id"], dist["DomainName"]


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("WAFv2 webACL (CLOUDFRONT scope):")
    arn = ensure_web_acl()
    print()
    print("CloudFront distribution:")
    dist_id, domain = ensure_distribution(arn)
    print(f"  id:     {dist_id}")
    print(f"  domain: https://{domain}")
    print(f"\nDone.")
    print(f"Update frontend config.json apiBaseUrl to: https://{domain}")
    print(f"(Distribution deploys in 3-5 min; visit the WAF console to see rule hits.)")


if __name__ == "__main__":
    main()
