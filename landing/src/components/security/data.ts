import type { LucideIcon } from 'lucide-react';
import {
  ShieldCheck,
  EyeOff,
  FileCheck2,
  Lock,
  KeyRound,
  Network,
  ScrollText,
  Workflow,
  Timer,
} from 'lucide-react';

/*
 * Security page content. The nine controls map 1:1 to Solace's real
 * architecture, grouped into three categories (AI safety, Infrastructure,
 * Governance) so the grid reads as a deliberate, structured set rather than a
 * generic 3-col. The stat row and the attestation posture cards live here too,
 * so the page file stays focused on layout and under budget.
 */

export type Control = {
  icon: LucideIcon;
  kicker: string;
  cat: string;
  title: string;
  body: string;
  points: string[];
};

export const CONTROL_CATEGORIES = [
  'AI safety',
  'Infrastructure',
  'Governance',
] as const;

export const CONTROLS: Control[] = [
  {
    icon: EyeOff,
    kicker: 'PHI isolation',
    cat: 'AI safety',
    title: 'The model never sees raw PHI.',
    body: 'Our AI plans and narrates over coded, de-identified metadata and {slot} tokens. Names, MRNs, dates of birth and free-text notes are stripped before any prompt is built.',
    points: [
      'Raw identifiers replaced with slot tokens at the boundary',
      'An automated leak-gate test fails the build if real PHI reaches a prompt',
      'Re-identification happens only in your trusted runtime, never in a model call',
    ],
  },
  {
    icon: ShieldCheck,
    kicker: 'Consent gate',
    cat: 'AI safety',
    title: 'No consent, no AI. Enforced at the boundary.',
    body: 'A recorded-consent chokepoint sits in front of every AI request. With no consent on file the request is refused before it leaves your environment, and the refusal is logged.',
    points: [
      'Consent state checked on every AI invocation',
      'Refusals are explicit and recorded, not silent',
      'Patient can decline; the visit still works without the AI',
    ],
  },
  {
    icon: FileCheck2,
    kicker: 'Confirm-gated writes',
    cat: 'AI safety',
    title: 'Nothing reaches the chart without a click.',
    body: 'Solace runs a Plan to Execute to Narrate pipeline. The model proposes; it never executes tools directly. Every write-back is staged for a clinician to review and approve.',
    points: [
      'The model plans actions; your runtime executes them',
      'Write-backs are confirm-gated, never automatic',
      'The clinician always makes the final call',
    ],
  },
  {
    icon: Lock,
    kicker: 'Encryption',
    cat: 'Infrastructure',
    title: 'Encrypted in transit and at rest.',
    body: 'Data is encrypted everywhere with customer-managed AWS KMS keys. Application secrets live in AWS Secrets Manager and are never inlined into code or configuration.',
    points: [
      'Customer-managed KMS keys, in transit and at rest',
      'TLS-only storage; no plaintext object access',
      'Secrets in AWS Secrets Manager, rotated, never hardcoded',
    ],
  },
  {
    icon: KeyRound,
    kicker: 'Access control',
    cat: 'Infrastructure',
    title: 'Passwordless, role-scoped, tenant-isolated.',
    body: 'Sign-in is a single-use magic link, sessions are short-lived JWTs, and admin powers are role-scoped. Every workspace query carries a tenant-isolation check.',
    points: [
      'Passwordless magic-link sign-in, JWT sessions',
      'Role-scoped admin, least-privilege by default',
      'Tenant-isolation check enforced on every workspace query',
    ],
  },
  {
    icon: Network,
    kicker: 'Network & edge',
    cat: 'Infrastructure',
    title: 'Hardened at the edge with CloudFront + WAF.',
    body: 'Traffic enters through CloudFront and a WAF tuned with IP-reputation filters, OWASP managed rules and rate limiting. Outbound EHR calls are guarded against SSRF.',
    points: [
      'WAF: IP reputation, OWASP managed rules, rate limiting',
      'SSRF guards on every outbound EHR request',
      'TLS-only transport end to end',
    ],
  },
  {
    icon: ScrollText,
    kicker: 'Audit trail',
    cat: 'Governance',
    title: 'Append-only, on every sensitive action.',
    body: 'Chart reads, AI requests, write-backs, sign-ins and admin changes all land in an append-only audit log, so a covered entity can reconstruct exactly what happened and when.',
    points: [
      'Append-only log of reads, AI calls and write-backs',
      'Sign-ins and admin changes recorded',
      'Available to covered entities for review under the BAA',
    ],
  },
  {
    icon: Workflow,
    kicker: 'Interoperability',
    cat: 'Governance',
    title: 'SMART on FHIR v2, minimum-necessary scopes.',
    body: 'We connect over SMART on FHIR v2 and request only the minimum-necessary scopes for the task, in line with HIPAA section 164.502(b). We never ask for access we do not use.',
    points: [
      'SMART on FHIR v2 authorization',
      'Minimum-necessary scopes (HIPAA 164.502(b))',
      'No standing access beyond the active workflow',
    ],
  },
  {
    icon: Timer,
    kicker: 'Data minimization',
    cat: 'Governance',
    title: 'Short-lived sessions, automatic expiry.',
    body: 'Intake sessions are short-lived and patient records and media carry an automatic TTL. Magic-link tokens are single-use and stored only as hashes, never in the clear.',
    points: [
      'Automatic TTL expiry on patient records and media',
      'Short-lived intake sessions',
      'Single-use magic-link tokens stored as hashes only',
    ],
  },
];

export type Stat = { big: string; label: string };
export const STATS: Stat[] = [
  { big: '749', label: 'automated tests every release' },
  { big: '0', label: 'raw PHI tokens allowed in any prompt' },
  { big: '100%', label: 'AI write-backs confirm-gated by a clinician' },
  { big: '1', label: 'tenant-isolation check on every query' },
];

export const POSTURE = [
  {
    title: 'HIPAA Business Associate',
    status: 'In place',
    body: 'Solace operates as a Business Associate and will sign a BAA before any PHI is processed. Infrastructure runs on HIPAA-eligible AWS under a BAA; model inference runs via AWS Bedrock in covered regions.',
  },
  {
    title: 'SOC 2 Type II',
    status: 'In progress',
    body: 'Our SOC 2 program is underway. Current status, scope and the most recent observation period are available on request under NDA.',
  },
  {
    title: 'Penetration testing',
    status: 'On request',
    body: 'Independent testing summaries, our security questionnaire responses and architecture diagrams are available to qualified buyers during review.',
  },
] as const;
