# Solace landing page

Static marketing site for solace.health. Deploys independently of the app.

## Deploy options

### Option 1 — AWS Amplify (recommended, matches the app deploy model)

Amplify can host raw static sites. Push this folder to a separate Amplify app:

```
cd landing
zip -r landing.zip index.html
aws amplify create-app --name solace-landing --region us-east-1
# then in the console: deploy this zip OR connect the GitHub repo with build root "landing"
```

Amplify gives you `https://main.d<id>.amplifyapp.com` and a custom domain hookup.

### Option 2 — S3 + CloudFront (cheapest)

```
aws s3 mb s3://solace-landing-prod --region us-east-1
aws s3 sync . s3://solace-landing-prod --exclude "README.md" --acl public-read
aws s3 website s3://solace-landing-prod/ --index-document index.html
```

Then put a CloudFront distribution in front for HTTPS.

### Option 3 — Local preview

```
cd landing
python3 -m http.server 8081
open http://localhost:8081
```

## What's inside

- `index.html` — the entire landing page. Tailwind via Play CDN, Inter + JetBrains Mono via Google Fonts.
- All buttons CTA to the live app at `https://solace.d2gsbjipp9quan.amplifyapp.com/demo`.

When the production domain is wired (e.g. `app.solace.health`), find/replace the Amplify URL.
