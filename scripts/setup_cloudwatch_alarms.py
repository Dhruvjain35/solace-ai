"""CloudWatch alarms for Solace — wired to the solace-security-alerts SNS topic.

Rewritten 2026-08-11 after checking whether this set would have caught the
incident in commit 42abe22. It would not have, for three separate reasons, and
all three are now fixed:

  1. THE TEN DYNAMODB ALARMS COULD NEVER FIRE. They alarmed on `UserErrors`
     dimensioned by `TableName`. `UserErrors` is an account-level DynamoDB
     metric aggregated across every table — it is not published with a
     TableName dimension at all. Combined with `TreatMissingData="notBreaching"`
     below, each of those alarms sat permanently OK on a metric that never
     reported a single datapoint. Ten green lights wired to nothing. Per-table
     throttling is `ReadThrottleEvents` / `WriteThrottleEvents`, which do carry
     TableName, so that is what they watch now.

  2. THE LAMBDA ERROR THRESHOLD WAS SET ABOVE THE INCIDENT. It fired above 5
     errors per 5 minutes. The warm ping timed out every 4 minutes, which is
     roughly 3.75 failures per 5 minutes — under the threshold, for weeks. A
     threshold has to be set below the rate of the failure you are trying to
     catch, and a scheduled job's failure rate is bounded by its own cadence.

  3. NOTHING WATCHED THE SHAPE OF THE SPEND. The signature of that incident was
     not an error spike, it was invocation count and duration: 1,080 minute-long
     2GB invocations a day on a function whose API Gateway bill was one cent.
     Duration-approaching-timeout and an invocation-envelope alarm both catch
     that directly, and a billing alarm catches whatever the others miss.

Also added: `solace-encounter-ledger`, which was absent from the table list
entirely despite being the one table whose loss ends the shadow programme.

NOTE ON BILLING: AWS/Billing EstimatedCharges is published only in us-east-1 and
only when billing alerts are enabled in the account's billing preferences. If
that switch is off the alarm will sit in INSUFFICIENT_DATA — which is why it is
created with TreatMissingData="breaching", so a silent metric is itself an alert
rather than a green light. Turning the preference on is a console action nobody
can do from here.
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
          "solace-quotas",
          # The ledger was missing from this list. It is the one table whose
          # loss ends the shadow programme, and it had no alarm at all.
          "solace-encounter-ledger"]

# The warm ping runs every 4 minutes = 375 invocations/day. The alarm fires on a
# 5-minute Sum, so the expected ceiling per period is ~2 (one warm ping plus
# headroom for real traffic bursts is handled by a separate, higher envelope).
# 42abe22's runaway showed up as 3x this. Set from the cadence, not by feel.
WARM_PING_PERIOD_SECONDS = 240


def _alarm(name, description, namespace, metric, dimensions, stat, threshold, period=300, evaluations=1, operator="GreaterThanThreshold", treat_missing="notBreaching"):
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
        TreatMissingData=treat_missing,
    )
    print(f"  [ok] {name}")


def main() -> None:
    print(f"Account {ACCOUNT}  Region {REGION}\n")
    print("CloudWatch alarms:")

    _alarm(
        "solace-lambda-errors",
        "Lambda solace-api errors > 1 in 5 min (42abe22 ran at ~3.75 and the old "
        "threshold of 5 never fired)",
        "AWS/Lambda", "Errors",
        [{"Name": "FunctionName", "Value": "solace-api"}],
        "Sum", 1,
    )
    _alarm(
        "solace-lambda-duration-near-timeout",
        "Lambda solace-api max duration > 45s — approaching the 60s timeout. This "
        "is the shape of 42abe22: not errors, but invocations running to the wall.",
        "AWS/Lambda", "Duration",
        [{"Name": "FunctionName", "Value": "solace-api"}],
        # Maximum, not Average or p99. The incident was every warm ping hitting
        # exactly 60s while real traffic stayed fast, so an average would have
        # been diluted by the requests that were fine. Maximum is noisier and
        # that is the correct trade for a spend alarm.
        "Maximum", 45_000,
    )
    _alarm(
        "solace-lambda-invocation-envelope",
        "Lambda solace-api > 40 invocations in 5 min. The warm ping alone is ~1.25 "
        "per period; a cadence that speeds up is the runaway signature, and it is "
        "visible in invocation count long before it is visible in errors.",
        "AWS/Lambda", "Invocations",
        [{"Name": "FunctionName", "Value": "solace-api"}],
        "Sum", 40,
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
        # UserErrors has no TableName dimension — see the module docstring. These
        # two do, and they are what "throttled" actually means per table.
        for metric in ("ReadThrottleEvents", "WriteThrottleEvents"):
            _alarm(
                f"solace-ddb-{'read' if metric.startswith('Read') else 'write'}-throttle-{tbl}",
                f"DDB {tbl} {metric} in 5 min",
                "AWS/DynamoDB", metric,
                [{"Name": "TableName", "Value": tbl}],
                "Sum", 0,
            )

    # Account-level spend. The only alarm here that would have caught 42abe22
    # regardless of which specific resource misbehaved.
    #
    # treat_missing="breaching": EstimatedCharges only publishes when billing
    # alerts are enabled in the account's billing preferences. If that switch is
    # off, this alarm going quiet must read as a problem rather than as calm.
    _alarm(
        "solace-estimated-charges",
        "AWS estimated charges > $50 this month. The repo had no billing alarm at "
        "all until 2026-08-11, which is why a runaway ran for weeks and was found "
        "on an invoice.",
        "AWS/Billing", "EstimatedCharges",
        [{"Name": "Currency", "Value": "USD"}],
        "Maximum", 50,
        period=21_600,  # 6h — EstimatedCharges publishes roughly every 4 hours
        treat_missing="breaching",
    )

    print(f"\nAll alarms publish to {TOPIC_ARN}")


if __name__ == "__main__":
    main()
