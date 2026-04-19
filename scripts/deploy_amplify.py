"""Deploy Solace frontend to AWS Amplify Hosting. Idempotent."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import ClientError

REGION = "us-east-1"
APP_NAME = "solace-web"
BRANCH = "solace"
ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
ZIP_PATH = ROOT / "build" / "solace-frontend.zip"

amplify = boto3.client("amplify", region_name=REGION)


def build_zip() -> Path:
    assert DIST.exists(), f"dist missing — run `npm run build` in {FRONTEND}"
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    # zip dist/ contents (not the dir itself) — Amplify expects files at root
    subprocess.run(
        ["zip", "-qr9", str(ZIP_PATH), "."],
        cwd=str(DIST),
        check=True,
    )
    print(f"  [ok] zipped {ZIP_PATH} ({ZIP_PATH.stat().st_size // 1024} KB)")
    return ZIP_PATH


def ensure_app() -> str:
    apps = amplify.list_apps()["apps"]
    app = next((a for a in apps if a["name"] == APP_NAME), None)
    if app:
        app_id = app["appId"]
        print(f"  [ok] app {APP_NAME}: {app_id}")
        return app_id
    resp = amplify.create_app(
        name=APP_NAME,
        platform="WEB",
        description="Solace patient intake + clinician dashboard",
        customRules=[
            # SPA fallback: anything that doesn't match a file → index.html
            {
                "source": "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|mp3|mp4)$)([^.]+$)/>",
                "target": "/index.html",
                "status": "200",
            }
        ],
        tags={"project": "solace"},
    )
    app_id = resp["app"]["appId"]
    print(f"  [create] app {APP_NAME}: {app_id}")
    return app_id


def ensure_branch(app_id: str) -> None:
    try:
        amplify.get_branch(appId=app_id, branchName=BRANCH)
        print(f"  [ok] branch {BRANCH}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NotFoundException":
            raise
        amplify.create_branch(
            appId=app_id,
            branchName=BRANCH,
            framework="Vite",
            stage="PRODUCTION",
            enableAutoBuild=False,
        )
        print(f"  [create] branch {BRANCH}")


def deploy_zip(app_id: str, zip_path: Path) -> str:
    resp = amplify.create_deployment(appId=app_id, branchName=BRANCH)
    upload_url = resp["zipUploadUrl"]
    job_id = resp["jobId"]
    print(f"  [ok] deployment job {job_id}")

    with zip_path.open("rb") as f:
        put = httpx.put(
            upload_url,
            content=f.read(),
            headers={"Content-Type": "application/zip"},
            timeout=120,
        )
    put.raise_for_status()
    print("  [ok] uploaded")

    amplify.start_deployment(appId=app_id, branchName=BRANCH, jobId=job_id)
    print("  [ok] deployment started")
    return job_id


def wait_for_job(app_id: str, job_id: str) -> str:
    while True:
        job = amplify.get_job(appId=app_id, branchName=BRANCH, jobId=job_id)["job"]
        status = job["summary"]["status"]
        if status in ("SUCCEED", "FAILED", "CANCELLED"):
            return status
        print(f"  ... {status}")
        time.sleep(4)


def main() -> None:
    print("Building zip:")
    build_zip()
    print()
    print("Amplify app:")
    app_id = ensure_app()
    print()
    print(f"Branch {BRANCH}:")
    ensure_branch(app_id)
    print()
    print("Deployment:")
    job_id = deploy_zip(app_id, ZIP_PATH)
    print()
    print("Waiting for deploy:")
    status = wait_for_job(app_id, job_id)
    print(f"  [final] {status}")
    print()
    url = f"https://{BRANCH}.{app_id}.amplifyapp.com"
    print(f"Done. Frontend URL: {url}")


if __name__ == "__main__":
    main()
