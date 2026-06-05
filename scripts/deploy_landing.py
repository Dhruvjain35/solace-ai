"""Deploy landing/index.html as a separate Amplify Hosting app.

The landing page lives at its own URL (e.g. solace-landing.<id>.amplifyapp.com)
so the marketing site stays decoupled from the application. The CTAs in
index.html point back to the application's Amplify URL.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import ClientError

REGION = "us-east-1"
APP_NAME = "solace-landing"
BRANCH = "main"
ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
ZIP_PATH = ROOT / "build" / "solace-landing.zip"

amplify = boto3.client("amplify", region_name=REGION)


def build_zip() -> Path:
    assert (LANDING / "index.html").exists(), f"missing {LANDING}/index.html"
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    subprocess.run(["zip", "-qr9", str(ZIP_PATH), "index.html"], cwd=str(LANDING), check=True)
    print(f"  [ok] zipped {ZIP_PATH} ({ZIP_PATH.stat().st_size // 1024} KB)")
    return ZIP_PATH


def find_or_create_app() -> str:
    paginator = amplify.get_paginator("list_apps")
    for page in paginator.paginate():
        for app in page["apps"]:
            if app["name"] == APP_NAME:
                print(f"  [ok] app {APP_NAME}: {app['appId']}")
                return app["appId"]
    resp = amplify.create_app(
        name=APP_NAME,
        platform="WEB",
        description="Solace marketing landing page (separately hosted)",
    )
    app_id = resp["app"]["appId"]
    print(f"  [create] app {APP_NAME}: {app_id}")
    return app_id


def find_or_create_branch(app_id: str) -> None:
    try:
        amplify.get_branch(appId=app_id, branchName=BRANCH)
        print(f"  [ok] branch {BRANCH}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise
        amplify.create_branch(appId=app_id, branchName=BRANCH, stage="PRODUCTION")
        print(f"  [create] branch {BRANCH}")


def deploy(app_id: str, zip_path: Path) -> str:
    deployment = amplify.create_deployment(appId=app_id, branchName=BRANCH)
    print(f"  [ok] deployment job {deployment['jobId']}")
    upload_url = deployment["zipUploadUrl"]
    with open(zip_path, "rb") as f:
        r = httpx.put(upload_url, content=f.read(), timeout=120)
        r.raise_for_status()
    print("  [ok] uploaded")
    amplify.start_deployment(appId=app_id, branchName=BRANCH, jobId=deployment["jobId"])
    print("  [ok] deployment started")
    job_id = deployment["jobId"]

    print("Waiting for deploy:")
    for _ in range(60):
        job = amplify.get_job(appId=app_id, branchName=BRANCH, jobId=job_id)
        status = job["job"]["summary"]["status"]
        print(f"  ... {status}")
        if status in ("SUCCEED", "FAILED", "CANCELLED"):
            print(f"  [final] {status}")
            break
        time.sleep(4)
    return f"https://{BRANCH}.{app_id}.amplifyapp.com"


def plan() -> None:
    """DRY-RUN: print the landing deploy plan. Makes NO AWS mutations."""
    print("DRY RUN — no AWS mutations, no live Amplify deploy.\n")
    print("Would (in order):")
    print(f"  1. zip {LANDING}/index.html → {ZIP_PATH}")
    print(f"  2. ensure Amplify app '{APP_NAME}' + branch '{BRANCH}' (PRODUCTION stage)")
    print(f"  3. create_deployment + upload zip + start_deployment to the live branch")
    print("\nThis publishes the marketing landing page live. Re-run with --apply:")
    print("    python scripts/deploy_landing.py --apply")


def main() -> None:
    if "--apply" not in set(sys.argv[1:]):
        plan()
        return

    print("Building zip:")
    z = build_zip()
    print("\nAmplify app:")
    app_id = find_or_create_app()
    print("\nBranch:")
    find_or_create_branch(app_id)
    print("\nDeployment:")
    url = deploy(app_id, z)
    print(f"\nDone. Landing URL: {url}")


if __name__ == "__main__":
    main()
