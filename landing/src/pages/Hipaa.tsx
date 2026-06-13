import LegalLayout, {
  Section,
  P,
  UL,
  LI,
  Strong,
  Callout,
  type LegalSection,
} from '../components/legal/LegalLayout';
import { SafeguardsMatrix, TrustChain } from '../components/legal/HipaaVisuals';

/*
 * HIPAA — Solace's compliance page, framed honestly: Solace is a Business
 * Associate, not a Covered Entity. It explains how Solace meets the Privacy,
 * Security and Breach Notification rules as a BA, maps the administrative,
 * technical and physical safeguards to what Solace actually does, and tells a
 * covered entity exactly what it gets (a BAA, audit access, a breach IR
 * commitment). Built on the shared LegalLayout shell (hero + prose + sticky
 * TOC) so it reads like the rest of the legal set while staying marketing-calm.
 */

const SECTIONS: LegalSection[] = [
  { id: 'our-role', title: 'Our role: Business Associate' },
  { id: 'privacy-rule', title: 'The Privacy Rule' },
  { id: 'security-rule', title: 'The Security Rule' },
  { id: 'administrative-safeguards', title: 'Administrative safeguards' },
  { id: 'technical-safeguards', title: 'Technical safeguards' },
  { id: 'physical-safeguards', title: 'Physical safeguards' },
  { id: 'phi-isolation', title: 'PHI isolation & minimum necessary' },
  { id: 'breach-notification', title: 'Breach notification' },
  { id: 'what-you-get', title: 'What a covered entity gets' },
  { id: 'requests', title: 'Compliance requests' },
];

export default function Hipaa() {
  return (
    <LegalLayout
      eyebrow="HIPAA compliance"
      title="HIPAA, handled as a Business Associate."
      sub="How Solace meets the Privacy, Security and Breach Notification Rules, and exactly what your organization gets when you bring us in."
      lastUpdated="June 2026"
      sections={SECTIONS}
    >
      <Section title="Our role: Business Associate" reduce={null} index={0}>
        <P>
          Solace is a <Strong>Business Associate (BA)</Strong> under HIPAA, not a
          Covered Entity. We process protected health information (PHI) on behalf
          of covered entities, such as hospitals, emergency departments and
          urgent care groups, strictly to deliver the services you contract us
          for. We are not the treating provider and we do not bill payers; the
          covered entity remains the steward of the patient relationship.
        </P>
        <P>
          Before any PHI is processed, Solace executes a{' '}
          <Strong>Business Associate Agreement (BAA)</Strong> with the covered
          entity. Our infrastructure runs on HIPAA-eligible AWS services under
          AWS&rsquo;s BAA, and model inference runs through AWS Bedrock in
          covered regions, so the obligations flow all the way down our
          subprocessor chain.
        </P>
        <Callout>
          We are deliberate about scope. Framing Solace as a BA, not a CE, is the
          honest description of what we do, and it shapes every commitment on this
          page.
        </Callout>
        <div className="pt-2">
          <TrustChain />
        </div>
      </Section>

      <Section title="The Privacy Rule" reduce={null} index={0}>
        <P>
          As a BA, Solace uses and discloses PHI only as permitted by the BAA and
          the Privacy Rule. We honor the <Strong>minimum-necessary</Strong>{' '}
          standard, requesting and processing only the data a given task
          requires. We do not sell PHI, we do not use PHI for our own marketing,
          and we never use PHI to train or fine-tune models.
        </P>
        <UL>
          <LI>Uses and disclosures limited to what the BAA permits.</LI>
          <LI>Minimum-necessary applied to data access and interop scopes.</LI>
          <LI>We support the covered entity in meeting individual rights requests.</LI>
        </UL>
      </Section>

      <Section title="The Security Rule" reduce={null} index={0}>
        <P>
          The Security Rule requires administrative, technical and physical
          safeguards for electronic PHI. Solace implements all three. Here is the
          map at a glance; the sections below give the detail.
        </P>
        <div className="pt-3">
          <SafeguardsMatrix />
        </div>
      </Section>

      <Section title="Administrative safeguards" reduce={null} index={0}>
        <UL>
          <LI>
            <Strong>Access management.</Strong> Role-scoped admin, least-privilege
            defaults, and a tenant-isolation check enforced on every workspace
            query so staff only ever reach the data they are entitled to.
          </LI>
          <LI>
            <Strong>Audit controls.</Strong> An append-only audit log records
            chart reads, AI requests, write-backs, sign-ins and admin changes.
          </LI>
          <LI>
            <Strong>Workforce &amp; change discipline.</Strong> 749 automated
            tests run every release, including dedicated PHI-isolation,
            tenant-isolation and consent-gate suites that block the build on
            failure.
          </LI>
          <LI>
            <Strong>Risk posture.</Strong> Our SOC 2 program is in progress;
            current status, scope and testing summaries are available on request.
          </LI>
        </UL>
      </Section>

      <Section title="Technical safeguards" reduce={null} index={0}>
        <UL>
          <LI>
            <Strong>Access control.</Strong> Passwordless magic-link sign-in,
            short-lived JWT sessions, and single-use link tokens stored only as
            hashes.
          </LI>
          <LI>
            <Strong>Encryption.</Strong> Customer-managed AWS KMS keys protect
            data in transit and at rest; secrets live in AWS Secrets Manager,
            never inline.
          </LI>
          <LI>
            <Strong>Transmission security.</Strong> TLS-only storage and
            transport, a CloudFront + WAF edge (IP reputation, OWASP managed
            rules, rate limiting), and SSRF guards on outbound EHR calls.
          </LI>
          <LI>
            <Strong>Integrity.</Strong> Confirm-gated writes mean nothing reaches
            the chart without a clinician&rsquo;s explicit approval.
          </LI>
        </UL>
      </Section>

      <Section title="Physical safeguards" reduce={null} index={0}>
        <P>
          Solace runs on HIPAA-eligible AWS infrastructure. The physical
          safeguards for the data centers, facility access, media controls and
          device hardening are inherited from AWS&rsquo;s audited environment
          under AWS&rsquo;s BAA, which is where electronic PHI is stored and
          processed. Solace adds the application-layer controls described above.
        </P>
      </Section>

      <Section title="PHI isolation & minimum necessary" reduce={null} index={0}>
        <P>
          Our AI is engineered so the model never sees raw PHI. Solace plans and
          narrates over coded, de-identified metadata and{' '}
          <Strong>{'{slot}'}</Strong> tokens; names, MRNs, dates of birth and
          free-text notes are stripped before any prompt is built. An automated
          leak-gate test fails the build if real PHI could reach a prompt.
        </P>
        <P>
          A recorded-consent chokepoint sits in front of every AI request. With
          no consent on file, the request is refused at the boundary and logged.
          And because we connect over SMART on FHIR v2 with minimum-necessary
          scopes (HIPAA &sect;164.502(b)), we never hold standing access beyond the
          active workflow.
        </P>
      </Section>

      <Section title="Breach notification" reduce={null} index={0}>
        <P>
          As a BA, Solace will notify the affected covered entity of a breach of
          unsecured PHI without unreasonable delay and within the timeframe set
          by the Breach Notification Rule and our BAA. Our notice includes the
          information a covered entity needs to meet its own downstream
          obligations: what happened, the PHI involved, and the steps taken to
          mitigate and remediate.
        </P>
        <UL>
          <LI>Prompt notification to the covered entity per the BAA.</LI>
          <LI>Documented incident response and remediation.</LI>
          <LI>Cooperation with the covered entity&rsquo;s investigation and reporting.</LI>
        </UL>
      </Section>

      <Section title="What a covered entity gets" reduce={null} index={0}>
        <UL>
          <LI>A signed BAA before any PHI is processed.</LI>
          <LI>Access to the audit trail for reads, AI requests and write-backs.</LI>
          <LI>A breach incident-response commitment with defined notice timing.</LI>
          <LI>Our security documentation and SOC 2 status on request, under NDA.</LI>
        </UL>
      </Section>

      <Section title="Compliance requests" reduce={null} index={0}>
        <P>
          For a BAA, security documentation, or our current SOC 2 status, contact{' '}
          <Strong>security@solace.health</Strong>. We respond within one business
          day.
        </P>
        <Callout>
          This page describes Solace&rsquo;s practices and is provided for
          information only; it is not legal advice and does not replace the terms
          of an executed BAA. Have your privacy officer and counsel review the BAA
          before launch.
        </Callout>
      </Section>
    </LegalLayout>
  );
}
