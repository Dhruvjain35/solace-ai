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
  4. SolaceRateLimit 50000/5min/IP — aggregate request rate cap (hospital NAT-friendly).
     Generous because a whole hospital waiting room shares one NAT egress IP;
     per-identity quota + blocklist do the real abuse-bounding.
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
# ACM certs consumed by CloudFront MUST live in us-east-1, regardless of the
# distribution's edge footprint.
acm = boto3.client("acm", region_name="us-east-1")

# Optional custom domain served by CloudFront. When set (and an ISSUED ACM cert
# exists for it in us-east-1), the distribution is pinned to that cert + the
# TLSv1.2_2021 security policy. Leave as None to keep the *.cloudfront.net
# default certificate (which only supports the weaker TLSv1 floor).
CUSTOM_DOMAIN: str | None = None


def _find_acm_cert(domain: str) -> str | None:
    """Return the ARN of an ISSUED ACM cert covering ``domain`` (us-east-1)."""
    paginator = acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["ISSUED"]):
        for cert in page.get("CertificateSummaryList", []):
            names = {cert.get("DomainName")}
            detail = acm.describe_certificate(CertificateArn=cert["CertificateArn"])
            names.update(detail["Certificate"].get("SubjectAlternativeNames", []))
            if domain in {n for n in names if n}:
                return cert["CertificateArn"]
    return None


def _viewer_certificate() -> tuple[dict, dict]:
    """Build the ViewerCertificate + Aliases blocks for the distribution.

    With a custom domain + ISSUED ACM cert we can enforce the modern
    TLSv1.2_2021 security policy (COMP-004). Without one, CloudFront only
    permits MinimumProtocolVersion=TLSv1 on its shared default certificate.
    """
    if CUSTOM_DOMAIN:
        cert_arn = _find_acm_cert(CUSTOM_DOMAIN)
        if cert_arn:
            print(f"  [acm]   using ACM cert for {CUSTOM_DOMAIN} -> TLSv1.2_2021")
            viewer_cert = {
                "ACMCertificateArn": cert_arn,
                "SSLSupportMethod": "sni-only",
                "MinimumProtocolVersion": "TLSv1.2_2021",
                "CertificateSource": "acm",
            }
            aliases = {"Quantity": 1, "Items": [CUSTOM_DOMAIN]}
            return viewer_cert, aliases
        print(f"  [warn]  no ISSUED ACM cert for {CUSTOM_DOMAIN} in us-east-1 — "
              "falling back to the CloudFront default certificate")
    # Default *.cloudfront.net certificate: TLSv1 is the only value AWS accepts
    # here; a custom ACM cert is required to raise the floor to TLS 1.2.
    viewer_cert = {
        "CloudFrontDefaultCertificate": True,
        "MinimumProtocolVersion": "TLSv1",
        "CertificateSource": "cloudfront",
    }
    return viewer_cert, {"Quantity": 0}


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

    viewer_cert, aliases = _viewer_certificate()

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
        "ViewerCertificate": viewer_cert,
        "DefaultRootObject": "",
        "IsIPV6Enabled": True,
        "HttpVersion": "http2",
        "Logging": {"Enabled": False, "IncludeCookies": False, "Bucket": "", "Prefix": ""},
        "Aliases": aliases,
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
