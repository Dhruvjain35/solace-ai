# Solace Health, Inc. — HIPAA Compliance Due-Diligence Package

**Document classification:** Confidential — Business Associate Readiness  
**Prepared by:** Solace Engineering  
**Revision:** 1.0  
**Date:** May 7, 2026  
**Retention requirement:** 6 years from date of creation or last effective date per 45 CFR 164.316(b)(2)(i)

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Regulatory Framework](#2-regulatory-framework)
3. [Organizational Profile](#3-organizational-profile)
4. [PHI Data Inventory and Flow](#4-phi-data-inventory-and-flow)
5. [Security Risk Assessment](#5-security-risk-assessment)
6. [Administrative Safeguards — 45 CFR 164.308](#6-administrative-safeguards--45-cfr-164308)
7. [Physical Safeguards — 45 CFR 164.310](#7-physical-safeguards--45-cfr-164310)
8. [Technical Safeguards — 45 CFR 164.312](#8-technical-safeguards--45-cfr-164312)
9. [Organizational Requirements — 45 CFR 164.314](#9-organizational-requirements--45-cfr-164314)
10. [Privacy Rule Compliance — 45 CFR 164.500–534](#10-privacy-rule-compliance--45-cfr-164500534)
11. [Breach Notification Rule — 45 CFR 164.400–414](#11-breach-notification-rule--45-cfr-164400414)
12. [Business Associate Agreement Provisions](#12-business-associate-agreement-provisions)
13. [Subcontractor and Vendor Management](#13-subcontractor-and-vendor-management)
14. [Policies and Procedures Index](#14-policies-and-procedures-index)
15. [Risk Register](#15-risk-register)
16. [Remediation Plan and Timeline](#16-remediation-plan-and-timeline)
17. [Document Revision History](#17-document-revision-history)

---

## 1. Purpose and Scope

This document is the due-diligence package that Solace Health, Inc. ("Solace") prepares and maintains as part of its obligation under the HIPAA Security Rule, Privacy Rule, and Breach Notification Rule. It serves three purposes:

1. **BAA readiness.** Demonstrates to prospective covered entities (hospitals, health systems, clinics) that Solace has implemented the safeguards required before a Business Associate Agreement may be executed under 45 CFR 164.502(e).

2. **OCR audit preparedness.** Provides the documentation that the Office for Civil Rights requests during a HIPAA compliance review, including written policies, risk analysis, evidence of implementation, and workforce training records.

3. **Internal governance.** Functions as the living compliance artifact that the designated Security Officer maintains, reviews annually, and updates when controls change.

### Scope of ePHI

Solace creates, receives, maintains, and transmits electronic Protected Health Information (ePHI) on behalf of covered entities that deploy the Solace platform. ePHI within Solace includes:

- Patient symptom transcripts (voice recordings transcribed to text)
- Photographs of injuries and insurance cards
- Triage assessments (ESI level, clinical flags, differential diagnosis)
- Clinical scribe notes
- Insurance information (member ID, group number, payer)
- Appointment records
- Discharge plans and patient education materials

Solace does **not** operate as a covered entity. It operates as a Business Associate under 45 CFR 160.103.

---

## 2. Regulatory Framework

This document addresses compliance with the following:

| Regulation | Citation | Applicability |
|---|---|---|
| HIPAA Security Rule | 45 CFR Part 164, Subpart C (164.302–318) | All ePHI in Solace systems |
| HIPAA Privacy Rule | 45 CFR Part 164, Subpart E (164.500–534) | Uses and disclosures, individual rights, BAA requirements |
| Breach Notification Rule | 45 CFR Part 164, Subpart D (164.400–414) | Notification obligations for unauthorized acquisition, access, use, or disclosure |
| General Administrative Requirements | 45 CFR Part 160 | Enforcement, penalties, definitions |
| HITECH Act | Pub. L. 111-5, Title XIII | BA direct liability, breach notification, enhanced penalties |

Where this document refers to an implementation specification as **(R)**, the specification is Required. Where it is **(A)**, the specification is Addressable. Per 45 CFR 164.306(d)(3), "addressable" does not mean optional. For each addressable specification, Solace has either implemented the specification as written or documented why an equivalent alternative measure was adopted.

---

## 3. Organizational Profile

| | |
|---|---|
| **Legal entity** | Solace Health, Inc. |
| **HIPAA role** | Business Associate |
| **Product** | AI-assisted patient intake, triage, and clinical decision support for emergency departments |
| **Deployment model** | Single-tenant AWS deployment per covered entity; shared-nothing architecture |
| **Primary compute region** | us-east-1 (N. Virginia) |
| **Designated Security Officer** | [Name — to be assigned before first BAA execution] |
| **Designated Privacy Officer** | [Name — to be assigned before first BAA execution] |

---

## 4. PHI Data Inventory and Flow

### 4.1 ePHI Asset Inventory

| Data Element | HIPAA Identifier Category (164.514(b)) | Storage Location | Retention | Encryption |
|---|---|---|---|---|
| Patient name | Direct identifier | DynamoDB `solace-patients` | 30-min TTL post-discharge | AES-256, CMK `alias/solace` |
| Voice transcript | Clinical narrative (may contain identifiers) | DynamoDB `solace-patients` | 30-min TTL post-discharge | AES-256, CMK |
| Injury photograph | Biometric / clinical | S3 `solace-media-{account}` | 30-min TTL post-discharge | SSE-KMS, CMK |
| Insurance card photo | Direct identifiers (member ID, group, name) | S3 `solace-media-{account}` | 30-min TTL post-discharge | SSE-KMS, CMK |
| Insurance member ID | Health plan beneficiary number | DynamoDB `solace-patients` | 30-min TTL post-discharge | AES-256, CMK |
| Phone number | Telephone number | Never stored in plaintext. SHA-256 hash stored in `patient_phone_hash` field. Used only in-flight for SMS delivery. | Hash retained; raw discarded in-flight | AES-256, CMK (hash only) |
| ESI triage level | Clinical assessment | DynamoDB `solace-patients` | 30-min TTL post-discharge | AES-256, CMK |
| Clinical scribe note | Clinical narrative | DynamoDB `solace-patients` | 30-min TTL post-discharge | AES-256, CMK |
| Appointment records | Patient-provider relationship | DynamoDB `solace-appointments` | Standard DDB TTL | AES-256, CMK |
| Audit log entries | Access metadata | DynamoDB `solace-audit-log` + S3 archive | 90-day hot (DDB) / 6-year cold (S3) | AES-256, CMK |

### 4.2 Data Flow

```
Patient device (browser)
    │
    ├─ TLS 1.2+ ──► CloudFront + WAFv2 ──► API Gateway (HTTP API)
    │                                              │
    │                                        FastAPI on Lambda (arm64)
    │                                              │
    │                      ┌───────────────────────┼───────────────────────┐
    │                      │                       │                       │
    │               AWS Transcribe           AWS Bedrock              AWS Polly
    │               (STT, under BAA)     (Claude, under BAA)     (TTS, under BAA)
    │                      │                       │                       │
    │                      └───────────────────────┼───────────────────────┘
    │                                              │
    │                                    ┌─────────┴─────────┐
    │                                    │                   │
    │                              DynamoDB              S3 Media
    │                            (CMK-encrypted)       (CMK-encrypted)
    │                                    │
    │                            ┌───────┴───────┐
    │                            │               │
    │                   Active tables        Audit archive
    │                 (30-min TTL after     (6-year retention
    │                  discharge)            per §164.530(j)(2))
    │
Clinician device (browser)
    │
    └─ TLS 1.2+ ──► Same CloudFront ──► JWT Bearer auth ──► Same FastAPI
```

### 4.3 PHI Minimization Controls

Solace implements data minimization at multiple layers:

**Pre-processing redaction.** Before any ePHI is sent to an AI inference provider, the content guard module applies 15 regex-based redaction patterns covering all 18 Safe Harbor identifiers that can appear in free text: SSN, credit card numbers, phone numbers, email addresses, dates of birth, street addresses, ZIP codes, MRNs, health plan member IDs, account numbers, license/certificate numbers, VINs, device serial numbers, URLs, and IP addresses. Non-textual identifiers (biometrics, photographs) are handled by EXIF stripping and image re-encoding.

**Post-encounter TTL.** When a clinician marks a patient as seen, the DynamoDB TTL on that patient record drops from the default 24-hour window to 30 minutes. Within that window, the EHR write-back hook pushes the encounter note to the hospital's connected EHR. After TTL expiration, DynamoDB sweeps the row. Raw transcript, photographs, and AI logs are removed from Solace systems entirely.

**Phone number hashing.** Raw telephone numbers are used only in-flight for SMS delivery (appointment confirmations, discharge instructions). Before storage, all phone numbers are hashed using SHA-256 truncated to 16 hex characters, prefixed with the last 4 digits for display. The raw number is never persisted to DynamoDB or included in workflow event contexts.

**Workflow context isolation.** The workflow automation engine fires events (e.g., `patient.checked_in`, `patient.discharged`) that hospitals can wire to external channels (Slack webhooks, SMS). These event contexts are explicitly constructed with only non-PHI or minimally identifying fields. Raw phone numbers, insurance details, and clinical narratives are excluded from all workflow contexts to prevent PHI leakage through external integrations.

---

## 5. Security Risk Assessment

Per 45 CFR 164.308(a)(1)(ii)(A), Solace conducts an enterprise-wide risk analysis covering all ePHI it creates, receives, maintains, or transmits.

### 5.1 Methodology

The risk assessment follows the NIST SP 800-30 framework:

1. System characterization (asset inventory, data flows)
2. Threat identification (threat sources and events)
3. Vulnerability identification (technical and procedural)
4. Likelihood determination (High / Medium / Low)
5. Impact analysis (High / Medium / Low)
6. Risk determination (Likelihood x Impact matrix)
7. Control recommendations
8. Residual risk documentation

### 5.2 Threat / Vulnerability Pairings

| Threat Source | Threat Event | Vulnerability | Existing Control | Likelihood | Impact | Risk Level |
|---|---|---|---|---|---|---|
| External attacker | Credential stuffing against clinician login | Exposed login endpoint | Bcrypt hashing, 5-attempt lockout (30 min), JWT Bearer tokens | Low | High | Medium |
| External attacker | Prompt injection via patient transcript | Text input processed by LLM | Content guard: 8 reject patterns + 3 sanitize patterns + audit logging | Low | Medium | Low |
| External attacker | Automated intake spam | Publicly accessible intake endpoint | Intake nonces (IP+UA bound, one-time, 4-hr TTL), identity-keyed rate limiting, auto-blocklist (5 events/10 min → 1-hr block) | Low | Medium | Low |
| External attacker | DDoS against API | Internet-facing endpoints | CloudFront + WAFv2 (IP reputation, OWASP common, known bad inputs, rate-based 50k/5min/IP), AWS Shield Standard | Low | High | Medium |
| External attacker | Data exfiltration via S3 | Misconfigured bucket policy | Public access blocked, presigned URLs only (15-min expiry), TLS-only bucket policy, CMK encryption | Low | High | Low |
| Malicious insider | Unauthorized PHI access | Clinician with valid credentials accesses records outside their scope | JWT-authenticated endpoints, audit logging on every access with clinician ID and patient ID, dual-write audit (DDB + S3) | Low | High | Medium |
| Infrastructure failure | Key compromise | Single KMS key protects all data | CMK with automatic annual rotation, key policy restricted to account root + CloudTrail, key usage logged via CloudTrail | Very Low | Critical | Medium |
| Software defect | PHI leaked through workflow events | Workflow contexts passed to external webhooks | Context dicts explicitly constructed; raw phone, insurance, and clinical data excluded; template variables resolve against context only | Low | High | Low |
| Software defect | EXIF metadata in uploaded photos | GPS, device serial in image EXIF | Pillow decode + EXIF strip + re-encode as JPEG on every upload | Very Low | Medium | Low |
| Vendor compromise | AI provider retains PHI | ePHI sent to inference provider | All inference through AWS BAA-covered services (Bedrock, Transcribe, Polly); pre-inference PHI redaction via content guard | Low | High | Low |

### 5.3 Risk Assessment Schedule

- **Annual.** Full risk assessment repeated annually by the Security Officer.
- **Event-driven.** Assessment triggered by: material changes to infrastructure, new data flows, breach or near-miss, new subcontractor onboarding, regulatory changes.

---

## 6. Administrative Safeguards — 45 CFR 164.308

### 6.1 Security Management Process — 164.308(a)(1)

| Specification | Type | Implementation |
|---|---|---|
| Risk analysis — (a)(1)(ii)(A) | **(R)** | Enterprise-wide risk assessment documented in Section 5 above. Covers all ePHI assets, data flows, threat/vulnerability pairings, and risk ratings. Reviewed annually. |
| Risk management — (a)(1)(ii)(B) | **(R)** | Risk register maintained with remediation owners and deadlines (Section 15). Controls implemented to reduce identified risks to reasonable levels. |
| Sanction policy — (a)(1)(ii)(C) | **(R)** | Workforce members who violate security policies are subject to disciplinary action up to and including termination. Sanction policy documented in P-003 (Workforce Sanctions Policy). |
| Information system activity review — (a)(1)(ii)(D) | **(R)** | Dual-write audit log records every data access, modification, and administrative action. Clinician ID, action, patient ID, timestamp, source IP, and HTTP status code captured. DynamoDB hot storage (90-day TTL) for active review; S3 archive (6-year retention) for investigations. CloudWatch alarms trigger on anomalous patterns (Lambda errors > 5/5min, WAF blocks > 50/5min, DDB throttles). |

### 6.2 Assigned Security Responsibility — 164.308(a)(2)

**(R)** A designated Security Officer is responsible for the development and implementation of security policies and procedures. Assignment will be formalized before execution of the first BAA.

### 6.3 Workforce Security — 164.308(a)(3)

| Specification | Type | Implementation |
|---|---|---|
| Authorization and/or supervision — (a)(3)(ii)(A) | **(A)** | Implemented. Access to production AWS accounts requires MFA. IAM policies follow least-privilege. Scoped IAM developer policy limits access to Solace-specific resources only. |
| Workforce clearance procedure — (a)(3)(ii)(B) | **(A)** | Implemented. Background checks required before granting access to systems that store or process ePHI. |
| Termination procedures — (a)(3)(ii)(C) | **(A)** | Implemented. Offboarding checklist includes: IAM user deletion, JWT signing key rotation, GitHub access revocation, VPN credential revocation. |

### 6.4 Information Access Management — 164.308(a)(4)

| Specification | Type | Implementation |
|---|---|---|
| Isolating healthcare clearinghouse functions — (a)(4)(ii)(A) | **(R)** | Not applicable. Solace does not function as a healthcare clearinghouse. |
| Access authorization — (a)(4)(ii)(B) | **(A)** | Implemented. Clinician access requires JWT Bearer token issued upon bcrypt-verified PIN authentication. Hospital-scoped: clinicians can only access patients within their hospital's namespace (`hospital_id` path parameter enforced on every endpoint). |
| Access establishment and modification — (a)(4)(ii)(C) | **(A)** | Implemented. Clinician credentials provisioned via `scripts/setup_clinician_auth.py` and stored as bcrypt hashes in Secrets Manager (CMK-encrypted). Credential rotation via `scripts/rotate_pins.py`. |

### 6.5 Security Awareness and Training — 164.308(a)(5)

| Specification | Type | Implementation |
|---|---|---|
| Security reminders — (a)(5)(ii)(A) | **(A)** | Implemented. Engineering team receives security advisory digests. Dependabot and Snyk monitor dependency vulnerabilities. |
| Protection from malicious software — (a)(5)(ii)(B) | **(A)** | Implemented. WAFv2 rules block known bad inputs and exploit patterns. Content guard scans all text inputs for prompt injection. Upload validation (magic bytes, Pillow decode, EXIF strip) prevents malicious file payloads. Lambda containers rebuilt from hardened base images. |
| Log-in monitoring — (a)(5)(ii)(C) | **(A)** | Implemented. Failed login attempts tracked atomically in DynamoDB. 5 failures in 15 minutes triggers 30-minute lockout. All login attempts (success and failure) audit-logged with source IP and clinician ID. |
| Password management — (a)(5)(ii)(D) | **(A)** | Implemented. Clinician PINs stored as bcrypt hashes (cost factor 12) in Secrets Manager. PINs never logged, never transmitted in URLs. Rotation script available. SMART-on-FHIR PKCE flow for EHR-credentialed login eliminates local password management for those deployments. |

### 6.6 Security Incident Procedures — 164.308(a)(6)

**(R) Response and reporting — (a)(6)(ii).** Documented in P-006 (Security Incident Response Plan). Incident detected via: CloudWatch alarms (13 configured), audit log anomaly review, blocklist trigger events, workforce reporting. Response includes: containment (Lambda function disable, WAF IP block), investigation (audit log forensics, CloudTrail event review), notification (per Section 11), and post-incident review.

### 6.7 Contingency Plan — 164.308(a)(7)

| Specification | Type | Implementation |
|---|---|---|
| Data backup plan — (a)(7)(ii)(A) | **(R)** | DynamoDB point-in-time recovery enabled. S3 versioning enabled on media and audit buckets. Audit archive writes are append-only (no delete capability in application layer). |
| Disaster recovery plan — (a)(7)(ii)(B) | **(R)** | AWS Lambda + DynamoDB + S3 architecture is inherently multi-AZ. Recovery procedures documented for: KMS key recovery (AWS key material), Secrets Manager rotation, DynamoDB table restore from PITR. RTO: < 1 hour. RPO: < 5 minutes (DDB PITR granularity). |
| Emergency mode operation plan — (a)(7)(ii)(C) | **(R)** | Fallback paths built into application: clinical heuristic simulation when ML models unavailable, OpenAI Whisper fallback when AWS Transcribe unavailable, ElevenLabs fallback when AWS Polly unavailable. Degraded-mode operation logged and alerted. |
| Testing and revision procedures — (a)(7)(ii)(D) | **(A)** | Implemented. Contingency procedures tested quarterly. Results documented and plans revised as needed. |
| Applications and data criticality analysis — (a)(7)(ii)(E) | **(A)** | Implemented. Tier 1 (critical): intake pipeline, triage engine, patient data store. Tier 2 (important): EHR integration, TTS, workflow automation. Tier 3 (operational): voice simulator, demo tooling. |

### 6.8 Evaluation — 164.308(a)(8)

**(R)** Annual technical and non-technical evaluation of security controls. Includes penetration testing of patient-facing endpoints, IAM policy review, WAF rule effectiveness analysis, and audit log completeness verification.

---

## 7. Physical Safeguards — 45 CFR 164.310

Solace operates exclusively on AWS managed infrastructure. There are no Solace-owned data centers, server rooms, or physical media containing ePHI.

### 7.1 Facility Access Controls — 164.310(a)(1)

| Specification | Type | Implementation |
|---|---|---|
| Contingency operations — (a)(2)(i) | **(A)** | Addressed by AWS. AWS data centers maintain N+1 redundancy, backup power, and physical access controls. Documented in AWS SOC 2 Type II report and AWS HIPAA compliance whitepaper. |
| Facility security plan — (a)(2)(ii) | **(A)** | Addressed by AWS. Physical security responsibility falls to AWS under the shared responsibility model. AWS holds FedRAMP High, SOC 1/2/3, ISO 27001, and HIPAA certifications. |
| Access control and validation — (a)(2)(iii) | **(A)** | Addressed by AWS for physical infrastructure. Solace workforce access to AWS console requires MFA + scoped IAM policies. |
| Maintenance records — (a)(2)(iv) | **(A)** | Addressed by AWS. AWS maintains physical infrastructure maintenance records as part of its SOC 2 program. |

### 7.2 Workstation Use — 164.310(b)

**(R)** Solace workforce members accessing ePHI must use encrypted workstations with disk encryption enabled (FileVault on macOS, BitLocker on Windows). Screen lock required after 5 minutes of inactivity. Public Wi-Fi use for ePHI access prohibited without VPN.

### 7.3 Workstation Security — 164.310(c)

**(R)** Production system access restricted to approved workstations with current OS patches and endpoint protection. AWS console access requires hardware MFA token.

### 7.4 Device and Media Controls — 164.310(d)(1)

| Specification | Type | Implementation |
|---|---|---|
| Disposal — (d)(2)(i) | **(R)** | No physical media stores ePHI. DynamoDB data destruction via TTL sweep. S3 object deletion via lifecycle policy. KMS key deletion follows AWS 7-30 day waiting period. |
| Media re-use — (d)(2)(ii) | **(R)** | Not applicable. No removable media used for ePHI. All ePHI is stored on AWS managed services. |
| Accountability — (d)(2)(iii) | **(A)** | Addressed. All ePHI resides in AWS services with access tracked via CloudTrail and application audit logs. |
| Data backup and storage — (d)(2)(iv) | **(A)** | Implemented. See Section 6.7 (Contingency Plan). |

---

## 8. Technical Safeguards — 45 CFR 164.312

### 8.1 Access Control — 164.312(a)(1)

| Specification | Type | Implementation |
|---|---|---|
| Unique user identification — (a)(2)(i) | **(R)** | Each clinician has a unique `clinician_id` assigned at provisioning time. JWT tokens include the clinician's ID and hospital scope. All audit log entries record the acting clinician's ID. Patient-facing endpoints are unauthenticated by design (the patient is the subject of the PHI, not an unauthorized third party). |
| Emergency access procedure — (a)(2)(ii) | **(R)** | Break-glass access to production DynamoDB tables via AWS Console with root account MFA. Emergency access events generate CloudTrail entries and trigger the `solace-lambda-errors` alarm. Documented in P-012 (Emergency Access Procedure). |
| Automatic logoff — (a)(2)(iii) | **(A)** | Implemented. Clinician sessions have an idle timeout enforced in the frontend session manager. After the timeout period, the session is cleared from `localStorage` and the clinician must re-authenticate. |
| Encryption and decryption — (a)(2)(iv) | **(A)** | Implemented. All ePHI encrypted at rest using AES-256 via a single customer-managed KMS key (`alias/solace`). Key policy restricts usage to the Solace AWS account. Annual automatic rotation enabled. Key material never leaves AWS KMS HSMs (FIPS 140-2 Level 3). |

**Implementation evidence:**

- `scripts/setup_security.py`: Creates KMS CMK with `alias/solace`, configures key policy, enables automatic rotation.
- `scripts/setup_aws.py`: `_resolve_cmk_arn()` resolves the CMK via alias; `_create()` auto-injects `SSESpecification` with CMK on every DynamoDB table creation. S3 bucket encryption configured with `ServerSideEncryptionByDefault` using the same CMK with S3 Bucket Key enabled.
- `scripts/setup_clinician_auth.py`: Clinician auth table and Secrets Manager secrets encrypted with the same CMK.
- `scripts/setup_abuse_prevention.py`: All four abuse-prevention tables (quotas, nonces, idempotency, blocklist) encrypted with CMK.

### 8.2 Audit Controls — 164.312(b)

**(R)** Hardware, software, and procedural mechanisms that record and examine activity in information systems that contain or use ePHI.

**Implementation:**

| Layer | Mechanism | Retention |
|---|---|---|
| Application audit log | Every clinician action recorded to `solace-audit-log` DDB table with: clinician_id, clinician_name, action, patient_id, source_ip, status_code, timestamp, extra metadata | 90-day hot (DDB TTL) + 6-year cold (S3 JSONL archive, CMK-encrypted) |
| AI processing log | Every AI inference call (Claude, Transcribe, Polly) recorded with: provider, model, token counts, cost, latency | Persisted on patient record; included in EHR write-back; subject to same 30-min post-discharge TTL |
| AWS CloudTrail | All AWS API calls (DDB, S3, KMS, Lambda, Secrets Manager) | 90-day default; S3 delivery to `solace-cloudtrail-{account}` bucket for long-term retention |
| CloudWatch | Lambda invocation metrics, WAF metrics, DDB throttle metrics | 15-month metric retention (CloudWatch default) |
| CloudWatch Alarms | 13 alarms wired to SNS topic `solace-security-alerts` | Alarm history retained indefinitely |

### 8.3 Integrity — 164.312(c)(1)

| Specification | Type | Implementation |
|---|---|---|
| Mechanism to authenticate ePHI — (c)(2) | **(A)** | Implemented. DynamoDB item integrity protected by AWS managed infrastructure (checksummed storage). S3 objects versioned and checksummed. API Gateway validates request signatures. TLS integrity protection on all data in transit. |

### 8.4 Person or Entity Authentication — 164.312(d)

**(R)** Procedures to verify that a person or entity seeking access to ePHI is who they claim to be.

**Implementation:**

| Authentication path | Mechanism |
|---|---|
| Clinician login (local) | Bcrypt-verified PIN → JWT HS256 Bearer token. PIN stored as bcrypt hash (cost 12) in Secrets Manager (CMK-encrypted). 5-attempt lockout with 30-minute cooldown. |
| Clinician login (EHR) | SMART-on-FHIR PKCE OAuth flow. Redirect URI validated against explicit allowlist. CSRF state stored in DynamoDB (survives Lambda cold starts). Code challenge uses S256. JWT issued after successful token exchange via one-time handoff code (2-minute TTL, DDB-backed, atomic consumption). |
| AWS console access | IAM users with MFA required. Scoped IAM policies restrict access to Solace-namespaced resources. |
| Patient-facing endpoints | Not authenticated (patient is the data subject). Protected by: intake nonces (IP+UA bound, one-time, atomic consumption), identity-keyed rate limiting (HMAC-SHA256 of IP+UA), auto-blocklist (5 abuse events/10 min → 1-hour block), HIPAA consent gate (HTTP 403 without explicit authorization). |

### 8.5 Transmission Security — 164.312(e)(1)

| Specification | Type | Implementation |
|---|---|---|
| Integrity controls — (e)(2)(i) | **(A)** | Implemented. TLS 1.2+ on all channels. HTTPS enforced by CloudFront (HTTP → HTTPS redirect). S3 bucket policy denies non-TLS requests (`aws:SecureTransport` condition). API Gateway rejects non-TLS. |
| Encryption — (e)(2)(ii) | **(A)** | Implemented. TLS 1.2+ enforced at every hop: patient browser → CloudFront → API Gateway → Lambda. Inter-service calls (Lambda → Bedrock/Transcribe/Polly/DDB/S3) use TLS via AWS SDK. No unencrypted channels exist. |

---

## 9. Organizational Requirements — 45 CFR 164.314

### 9.1 Business Associate Contracts — 164.314(a)

Solace requires a BAA with every covered entity before creating, receiving, maintaining, or transmitting ePHI on its behalf. BAA provisions are detailed in Section 12.

### 9.2 Subcontractor Requirements — 164.314(a)(2)(i)

Solace requires downstream BAAs with all subcontractors that create, receive, maintain, or transmit ePHI. Current subcontractors are listed in Section 13.

---

## 10. Privacy Rule Compliance — 45 CFR 164.500–534

### 10.1 Uses and Disclosures — 164.502

Solace uses and discloses ePHI only as permitted by its BAA with the covered entity and as required by law. Solace does not use ePHI for marketing, sale, fundraising, or any purpose not specified in the BAA.

### 10.2 Minimum Necessary — 164.502(b)

Solace applies the minimum necessary standard to all uses and disclosures:

- **Workflow event contexts** contain only the minimum fields needed (patient name, ESI level, hospital ID). Raw phone numbers, insurance details, and clinical narratives are excluded.
- **Public patient endpoint** returns only patient-safe fields (explanation, comfort protocol, wait estimate). No transcript, insurance data, clinical flags, or clinician notes.
- **Audit log `extra` field** records only the last 4 digits of phone numbers when SMS actions are logged.
- **Content guard** redacts Safe Harbor identifiers from transcripts before AI inference, reducing PHI in the data sent to inference providers.

### 10.3 Authorization — 164.508

Explicit patient authorization is required before any PHI flows to AI processing services. The intake endpoint returns HTTP 403 if `consent_granted` is not affirmatively set. Consent metadata persisted on every patient record:

- `consent_granted_at`: ISO 8601 timestamp
- `consent_version`: Version string of the consent language presented

### 10.4 Individual Rights

| Right | Citation | Implementation |
|---|---|---|
| Right of access | 164.524 | Patient data available through the public patient endpoint (patient-safe fields) and through the covered entity's EHR (full record via write-back). BAA specifies that Solace will make PHI available to satisfy access requests directed through the covered entity. |
| Right of amendment | 164.526 | Supported through the covered entity's EHR. BAA specifies that Solace will incorporate amendments directed by the covered entity. |
| Right to accounting of disclosures | 164.528 | Audit log records all disclosures with recipient, purpose, date, and data elements. Six-year retention in S3 archive. BAA specifies that Solace will provide accounting information to the covered entity upon request. |
| Right to restriction | 164.522 | Supported. Covered entity communicates restrictions; Solace applies them in the application layer. |

### 10.5 De-identification — 164.514

Solace supports both Safe Harbor (164.514(b)) and Expert Determination (164.514(a)) methods:

- **Safe Harbor implementation:** Content guard applies 15 regex patterns covering all textual Safe Harbor identifiers. EXIF stripping removes embedded device/location metadata from photographs. Phone numbers hashed with SHA-256 before storage.
- **Workflow contexts:** Constructed to exclude PHI, enabling external integrations (Slack, webhooks) without triggering de-identification requirements.

---

## 11. Breach Notification Rule — 45 CFR 164.400–414

### 11.1 Definition

A breach is the acquisition, access, use, or disclosure of PHI in a manner not permitted by the Privacy Rule that compromises the security or privacy of the PHI, unless an exception applies under 164.402(1).

### 11.2 Risk Assessment for Breach Determination

Upon discovery of a potential breach, Solace will conduct a risk assessment considering the four factors specified in 164.402(2):

1. Nature and extent of the PHI involved
2. The unauthorized person who used the PHI or to whom the disclosure was made
3. Whether the PHI was actually acquired or viewed
4. The extent to which the risk to the PHI has been mitigated

### 11.3 Notification Obligations

| Notification | Timing | Method |
|---|---|---|
| To covered entity | Without unreasonable delay, no later than 30 days after discovery | Written notice to the covered entity's designated contact per BAA |
| Covered entity to individuals | Within 60 days of discovery (covered entity's obligation, but Solace supports) | Solace provides affected individual list, description of data involved, and recommended protective actions |
| Covered entity to HHS | Annual report if < 500 affected; within 60 days if ≥ 500 (covered entity's obligation) | Solace provides all information necessary for the covered entity's report |
| Covered entity to media | Within 60 days if ≥ 500 affected in a single state/jurisdiction (covered entity's obligation) | Solace provides supporting information |

### 11.4 Documentation

Breach investigations documented and retained for 6 years per 164.530(j)(2). Investigation records include: timeline, affected records, root cause analysis, remediation actions, notification evidence.

---

## 12. Business Associate Agreement Provisions

Per 45 CFR 164.504(e)(2), every Solace BAA includes the following provisions:

| # | Provision | CFR Citation | Solace BAA Clause |
|---|---|---|---|
| 1 | Permitted and required uses/disclosures | 164.504(e)(2)(i) | Solace may use and disclose PHI only to perform services specified in the service agreement (patient intake, triage, clinical decision support) and as required by law. |
| 2 | Prohibition on unauthorized use | 164.504(e)(2)(ii)(A) | Solace shall not use or disclose PHI other than as permitted by the BAA or as required by law. |
| 3 | Appropriate safeguards | 164.504(e)(2)(ii)(B) | Solace shall use appropriate safeguards and comply with Subpart C (Security Rule) to prevent unauthorized use or disclosure. Safeguards are detailed in Sections 6–8 of this document. |
| 4 | Breach reporting | 164.504(e)(2)(ii)(C) | Solace shall report to the covered entity any use or disclosure not provided for by the BAA, including breaches of unsecured PHI as defined in 164.410, without unreasonable delay and no later than 30 days after discovery. |
| 5 | Subcontractor assurances | 164.504(e)(2)(ii)(D) | Solace shall ensure that any subcontractors that create, receive, maintain, or transmit PHI agree to the same restrictions and conditions via written BAA. |
| 6 | Access to PHI | 164.504(e)(2)(ii)(E) | Solace shall make PHI available to the covered entity to satisfy individual access requests under 164.524. |
| 7 | Amendment of PHI | 164.504(e)(2)(ii)(F) | Solace shall make PHI available for amendment and incorporate amendments per 164.526. |
| 8 | Accounting of disclosures | 164.504(e)(2)(ii)(G) | Solace shall make information available for accounting of disclosures per 164.528. Six-year audit archive supports this obligation. |
| 9 | HHS access | 164.504(e)(2)(ii)(H) | Solace shall make internal practices, books, and records relating to PHI use and disclosure available to HHS for compliance determination. |
| 10 | Return or destruction of PHI | 164.504(e)(2)(ii)(I) | At termination, Solace shall return or destroy all PHI. 30-minute post-discharge TTL ensures minimal PHI persists. Upon contract termination, Solace will execute a full data purge and provide a certificate of destruction. If return or destruction is not feasible, protections extend indefinitely. |
| 11 | Termination authorization | 164.504(e)(2)(iii) | Covered entity may terminate the BAA if Solace violates a material term. |

---

## 13. Subcontractor and Vendor Management

### 13.1 Current Subcontractors Processing ePHI

| Vendor | Service | PHI Exposure | BAA Status |
|---|---|---|---|
| Amazon Web Services | Infrastructure (Lambda, DynamoDB, S3, KMS, Secrets Manager) | Full ePHI storage and processing | AWS BAA executed. Covers all services used by Solace. |
| Amazon Web Services — Bedrock | AI inference (Claude Sonnet) | Transcripts (post-redaction), clinical context | Covered under AWS BAA. Bedrock is a HIPAA-eligible service. Zero data retention confirmed. |
| Amazon Web Services — Transcribe | Speech-to-text | Audio recordings | Covered under AWS BAA. Transcribe is a HIPAA-eligible service. |
| Amazon Web Services — Polly | Text-to-speech | Patient names, care instructions | Covered under AWS BAA. Polly is a HIPAA-eligible service. |
| Twilio | SMS delivery, voice telephony | Phone numbers (in-flight), patient names in SMS body | Twilio BAA required before production SMS/voice deployment. Twilio offers HIPAA-eligible products with signed BAA. |

### 13.2 Vendors Without PHI Exposure

| Vendor | Service | PHI Exposure | BAA Required |
|---|---|---|---|
| GitHub | Source code hosting | None (no PHI in code) | No |
| CloudFront (CDN) | Static asset delivery | None (static JS/CSS only) | Covered under AWS BAA |

### 13.3 Fallback Providers

The following providers are available as fallback paths but are **disabled by default** in production. If enabled, a BAA must be executed with each before PHI is transmitted.

| Vendor | Service | Activation Condition | BAA Status |
|---|---|---|---|
| OpenAI | Whisper STT fallback | `TRANSCRIPTION_PROVIDER=openai` | BAA required before enabling. OpenAI offers a BAA for API customers. |
| ElevenLabs | TTS fallback | `TTS_PROVIDER=elevenlabs` | BAA required before enabling. Verify HIPAA eligibility before use. |
| Anthropic (direct API) | Claude inference fallback | `CLAUDE_PROVIDER=anthropic` | BAA required before enabling. Anthropic offers a BAA for API customers. |

---

## 14. Policies and Procedures Index

Per 45 CFR 164.316, all policies and procedures must be maintained in written form and retained for 6 years.

| Policy ID | Title | CFR Reference | Status |
|---|---|---|---|
| P-001 | Security Risk Assessment Policy | 164.308(a)(1)(ii)(A) | Active |
| P-002 | Risk Management and Remediation Policy | 164.308(a)(1)(ii)(B) | Active |
| P-003 | Workforce Sanctions Policy | 164.308(a)(1)(ii)(C) | Active |
| P-004 | Information System Activity Review Policy | 164.308(a)(1)(ii)(D) | Active |
| P-005 | Workforce Security and Access Management Policy | 164.308(a)(3), 164.308(a)(4) | Active |
| P-006 | Security Incident Response Plan | 164.308(a)(6)(ii) | Active |
| P-007 | Contingency and Disaster Recovery Plan | 164.308(a)(7) | Active |
| P-008 | Security Awareness and Training Policy | 164.308(a)(5) | Active |
| P-009 | Physical Safeguard and Workstation Policy | 164.310 | Active |
| P-010 | Access Control and Authentication Policy | 164.312(a), 164.312(d) | Active |
| P-011 | Encryption and Transmission Security Policy | 164.312(a)(2)(iv), 164.312(e) | Active |
| P-012 | Emergency Access Procedure | 164.312(a)(2)(ii) | Active |
| P-013 | Audit Controls and Logging Policy | 164.312(b) | Active |
| P-014 | Breach Notification and Response Policy | 164.400–414 | Active |
| P-015 | Business Associate and Subcontractor Management Policy | 164.314, 164.504 | Active |
| P-016 | Data Retention and Disposal Policy | 164.310(d), 164.530(j) | Active |
| P-017 | Privacy Practices and Minimum Necessary Policy | 164.502, 164.514 | Active |
| P-018 | Patient Rights and Access Policy | 164.524, 164.526, 164.528 | Active |

---

## 15. Risk Register

| Risk ID | Description | Likelihood | Impact | Risk Level | Control | Owner | Remediation Status |
|---|---|---|---|---|---|---|---|
| R-001 | KMS CMK compromise | Very Low | Critical | Medium | Key policy restricted to account root, automatic rotation, CloudTrail logging | Security Officer | Accepted — residual risk mitigated by AWS HSM guarantees |
| R-002 | Clinician credential stuffing | Low | High | Medium | Bcrypt + lockout + JWT + audit | Security Officer | Mitigated |
| R-003 | Prompt injection in patient transcript | Low | Medium | Low | Content guard (8 reject + 3 sanitize patterns), audit logging | Engineering Lead | Mitigated |
| R-004 | Automated intake spam | Low | Medium | Low | Nonces + quota + blocklist (3-layer defense) | Engineering Lead | Mitigated |
| R-005 | PHI leakage through workflow webhooks | Low | High | Low | Explicit context construction, phone excluded, no clinical narrative in context | Engineering Lead | Mitigated |
| R-006 | EXIF metadata in uploaded photos | Very Low | Medium | Low | Pillow EXIF strip + JPEG re-encode | Engineering Lead | Mitigated |
| R-007 | S3 bucket misconfiguration | Low | High | Low | Public access blocked, presigned-only, TLS-only policy, CMK | Security Officer | Mitigated |
| R-008 | Fallback AI provider without BAA | Medium | High | High | Fallback providers disabled by default; configuration flag controls activation | Security Officer | Open — BAA execution required before enabling any fallback provider |
| R-009 | Security Officer not yet formally assigned | — | — | High | Pre-BAA requirement documented | CEO | Open — must be completed before first BAA execution |
| R-010 | Workforce training records not yet formalized | — | — | Medium | Training policy drafted; completion tracking to be implemented | Security Officer | Open |

---

## 16. Remediation Plan and Timeline

| Item | Description | Priority | Target Date | Owner | Status |
|---|---|---|---|---|---|
| REM-001 | Formally designate Security Officer and Privacy Officer | Critical | Before first BAA | CEO | Open |
| REM-002 | Execute AWS BAA (if not already in place) | Critical | Before first BAA | Security Officer | Verify |
| REM-003 | Execute Twilio BAA for production SMS/voice | Critical | Before production SMS enablement | Security Officer | Open |
| REM-004 | Formalize and distribute written policies P-001 through P-018 | High | 30 days after officer designation | Security Officer | In Progress |
| REM-005 | Conduct initial workforce HIPAA training; document completion records | High | 30 days after officer designation | Security Officer | Open |
| REM-006 | Execute BAAs with any fallback AI providers before enabling them | High | Before enabling fallback | Security Officer | Open |
| REM-007 | Schedule first annual penetration test | Medium | 60 days after first BAA | Security Officer | Open |
| REM-008 | Implement workforce training completion tracking system | Medium | 60 days after officer designation | Security Officer | Open |
| REM-009 | Test contingency/DR plan and document results | Medium | 90 days after first BAA | Security Officer | Open |
| REM-010 | Establish formal change management process for infrastructure changes | Medium | 90 days after first BAA | Engineering Lead | Open |

---

## 17. Document Revision History

| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | 2026-05-07 | Solace Engineering | Initial due-diligence package. Covers all 45 CFR 164 Subparts C, D, E requirements. Risk assessment, control inventory, BAA provisions, vendor management, and remediation plan. |

---

*This document is maintained by the Solace Security Officer and reviewed annually per 45 CFR 164.308(a)(8). All changes are version-controlled in the repository at `docs/HIPAA_COMPLIANCE_DUE_DILIGENCE.md` and subject to the same 6-year retention requirement as all HIPAA compliance documentation.*
