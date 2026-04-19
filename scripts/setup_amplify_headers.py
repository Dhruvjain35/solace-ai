"""Apply security response headers to the Solace Amplify app.

Headers (applied to every response from Amplify Hosting):
  - Strict-Transport-Security — force HTTPS for 2 years + preload list
  - Content-Security-Policy    — restrict to our own origins + S3 presigned + data: imgs
  - X-Frame-Options            — clickjacking defense
  - X-Content-Type-Options     — MIME sniff defense
  - Referrer-Policy            — no cross-origin referrers (PHI leak prevention)
  - Permissions-Policy         — limit to what the patient intake flow actually needs
"""
from __future__ import annotations

import boto3

REGION = "us-east-1"
APP_ID = "d2gsbjipp9quan"

CLOUDFRONT_API = "https://djfjrel7b1ebi.cloudfront.net"
APIGW_DIRECT = "https://7ew5f2x01d.execute-api.us-east-1.amazonaws.com"
MEDIA_S3 = "https://solace-media-704229156617.s3.amazonaws.com"

# YAML payload for Amplify customHeaders (Amplify Hosting uses YAML, not JSON)
HEADERS_YAML = f"""customHeaders:
  - pattern: '**'
    headers:
      - key: 'Strict-Transport-Security'
        value: 'max-age=63072000; includeSubDomains; preload'
      - key: 'X-Frame-Options'
        value: 'DENY'
      - key: 'X-Content-Type-Options'
        value: 'nosniff'
      - key: 'Referrer-Policy'
        value: 'no-referrer'
      - key: 'Permissions-Policy'
        value: 'camera=(self), microphone=(self), geolocation=(), accelerometer=(), gyroscope=()'
      - key: 'Content-Security-Policy'
        value: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: {MEDIA_S3}; media-src 'self' {MEDIA_S3}; connect-src 'self' {CLOUDFRONT_API} {APIGW_DIRECT}; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
      - key: 'Cross-Origin-Opener-Policy'
        value: 'same-origin'
      - key: 'Cross-Origin-Resource-Policy'
        value: 'same-origin'
"""


def main() -> None:
    amplify = boto3.client("amplify", region_name=REGION)
    resp = amplify.update_app(appId=APP_ID, customHeaders=HEADERS_YAML)
    print(f"  [ok] custom headers applied to {resp['app']['name']} ({APP_ID})")
    print("  Next deploy picks these up; hard-refresh the browser to see them.")


if __name__ == "__main__":
    main()
