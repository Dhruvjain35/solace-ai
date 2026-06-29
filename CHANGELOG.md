# Changelog

A truthful, dated record of Solace's development. We have **not** squashed or rewritten
history to disguise the project's age — this reflects the real `git log`.

> For UOE Summer of Code 2026 judges: Solace is an ongoing project (started April 2026),
> not a from-scratch hackathon build. See the "Provenance & what's new" section of the
> [README](README.md) for the honest accounting of what was carried over vs. improved for
> the event. **Edit the "Event window" entry below to match exactly what you worked on
> during the contest period, with dates — keep it accurate.**

## Event window — UOE Summer of Code 2026 (June 2026)

- **2026-06-22** — Recorded the [demo walkthrough](https://www.youtube.com/watch?v=vFjxtGklkCo); re-seeded
  and verified the live production triage board; finalized the Devpost submission.
- **2026-06-21** — Submission hardening: scrubbed stale references, added MIT `LICENSE`,
  reconciled licensing headers, corrected the ML architecture description (4-model stacked
  ensemble), documented the demo-vs-production AI path and synthetic-data caveats, fixed a
  landing-page horizontal-overflow bug, restructured the README for the live demo, and added
  this changelog + a Devpost writeup (`docs/DEVPOST.md`).

## June 2026
- Replaced the landing mockup with the full marketing site + Pricing page; SPA deep-link
  rewrites; Vercel auto-deploy from `landing/`; root + landing README handoff docs.

## May 2026 (bulk of the build)
- Served the **trained 4-model ensemble** in production + fixed `/health` detection.
- Deterministic triage **safety floor** — never down-triage life threats.
- EHR Copilot agent: chart Q&A, catch-me-up, fixable-issue scan, autopopulate.
- SMS via AWS SNS fallback when Twilio creds are absent.
- CI: bake trained ML artifacts into the Lambda image.
- Triage regex fixes (psych-crisis / suicidality detection).

## April 2026 (project inception)
- Initial Solace build: AI-assisted ER triage, patient intake, QR flow, camera/insurance
  capture, AWS deployment pipeline (container Lambda, WAF + CloudFront).

---
*This file is maintained by hand; `git log` remains the authoritative record.*
