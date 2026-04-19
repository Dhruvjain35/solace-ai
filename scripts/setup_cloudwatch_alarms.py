"""CloudWatch alarms for Solace — wired to the solace-security-alerts SNS topic.

Alarms:
  - Lambda errors         — >5 in 5 min
  - WAF blocked requests  — >50 in 5 min (indicates an ongoing attack)
  - DDB throttling        — >0 in 5 min on any of our 4 tables
  - Lambda concurrency    — any throttle event (cap is usually 1000 default; if we hit it, there's a storm)
"""
from __future__ import annotations

import boto3

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:solace-security-alerts"

cw = boto3.client("cloudwatch", region_name=REGION)

TABLES = ["solace-patients", "solace-hospitals", "solace-prescriptions",
          "solace-notes", "solace-clinicians", "solace-audit-log",
          "solace-intake-nonces", "solace-idempotency", "solace-blocklist",
          "solace-quotas"]


def _alarm(name, description, namespace, metric, dimensions, stat, threshold, period=300, evaluations=1, operator="GreaterThanThreshold"):
    cw.put_metric_alarm(
        AlarmName=name,
        AlarmDescription=description,
        ActionsEnabled=True,
        AlarmActions=[TOPIC_ARN],
        Namespace=namespace,
        MetricName=metric,
        Dimensions=dimensions,
        Statistic=stat,
        Period=period,
        EvaluationPeriods=evaluations,
        Threshold=threshold,
        ComparisonOperator=operator,
        TreatMissingData="notBreaching",
    )
    print(f"  [ok] {name}")


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("CloudWatch alarms:")

    _alarm(
        "solace-lambda-errors",
        "Lambda solace-api errors > 5 in 5 min",
        "AWS/Lambda", "Errors",
        [{"Name": "FunctionName", "Value": "solace-api"}],
        "Sum", 5,
    )
    _alarm(
        "solace-lambda-throttles",
        "Lambda solace-api concurrency throttle events",
        "AWS/Lambda", "Throttles",
        [{"Name": "FunctionName", "Value": "solace-api"}],
        "Sum", 0,
    )
    _alarm(
        "solace-waf-blocked",
        "WAF solace-waf blocked > 50 requests in 5 min (possible attack)",
        "AWS/WAFV2", "BlockedRequests",
        [
            {"Name": "WebACL", "Value": "solace-waf"},
            {"Name": "Rule", "Value": "ALL"},
            {"Name": "Region", "Value": "CloudFront"},
        ],
        "Sum", 50,
    )
    for tbl in TABLES:
        _alarm(
            f"solace-ddb-throttle-{tbl}",
            f"DDB {tbl} throttle events in 5 min",
            "AWS/DynamoDB", "UserErrors",
            [{"Name": "TableName", "Value": tbl}],
            "Sum", 0,
        )

    print(f"\nAll alarms publish to {TOPIC_ARN}")


if __name__ == "__main__":
    main()
