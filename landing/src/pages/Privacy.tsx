import LegalLayout, {
  Section,
  P,
  UL,
  LI,
  Strong,
  Callout,
  type LegalSection,
} from '../components/legal/LegalLayout';

/*
 * Privacy, Solace's long-form privacy policy. Original content (not copied
 * from any company's policy) covering what is collected, how it is used, the
 * Business Associate relationship for patient PHI, subprocessor sharing,
 * retention/TTL, security, rights, children, international transfers, changes
 * and contact. Built on the shared LegalLayout shell with a sticky TOC. A
 * counsel-review notice sits up top and at the close, since this is a template.
 */

const SECTIONS: LegalSection[] = [
  { id: 'overview', title: 'Overview' },
  { id: 'information-we-collect', title: 'Information we collect' },
  { id: 'patient-phi', title: 'Patient PHI & the BA relationship' },
  { id: 'how-we-use-it', title: 'How we use information' },
  { id: 'how-we-share-it', title: 'How we share information' },
  { id: 'subprocessors', title: 'Subprocessors' },
  { id: 'retention-ttl', title: 'Retention & TTL' },
  { id: 'security', title: 'Security' },
  { id: 'your-rights', title: 'Your rights' },
  { id: 'cookies', title: 'Cookies & telemetry' },
  { id: 'children', title: "Children's privacy" },
  { id: 'international', title: 'International users' },
  { id: 'changes', title: 'Changes to this policy' },
  { id: 'contact', title: 'Contact us' },
];

export default function Privacy() {
  return (
    <LegalLayout
      eyebrow="Privacy policy"
      title="Your data, treated like it matters."
      sub="How Solace collects, uses, shares and protects information, including the protected health information we process on behalf of covered entities."
      lastUpdated="June 2026"
      sections={SECTIONS}
    >
      <Section title="Overview" reduce={null} index={0}>
        <Callout>
          This is a template policy provided for information only. It is not legal
          advice and must be reviewed and adapted by qualified counsel before
          launch.
        </Callout>
        <P>
          This Privacy Policy explains how Solace AI, Inc. (&ldquo;Solace,&rdquo;
          &ldquo;we,&rdquo; &ldquo;us&rdquo;) handles information in connection
          with our patient-intake and clinical-triage services (the
          &ldquo;Services&rdquo;). Solace serves healthcare organizations. Most
          patient health information we touch is handled as a{' '}
          <Strong>Business Associate</Strong> on behalf of a covered entity, and
          is governed first by the Business Associate Agreement (BAA) and HIPAA,
          not by this consumer-facing policy.
        </P>
      </Section>

      <Section title="Information we collect" reduce={null} index={0}>
        <UL>
          <LI>
            <Strong>Clinician &amp; account data.</Strong> Name, work email,
            organization, role and authentication metadata for the people who use
            Solace at a customer site.
          </LI>
          <LI>
            <Strong>Patient PHI processed for covered entities.</Strong> Intake
            responses, demographics, insurance details and related clinical data
            submitted during a visit, processed under the BAA. See the next
            section.
          </LI>
          <LI>
            <Strong>Usage &amp; telemetry.</Strong> Log data, device and browser
            details, and aggregate performance and reliability metrics, used to
            operate and improve the Services.
          </LI>
          <LI>
            <Strong>Cookies &amp; similar technologies.</Strong> Strictly
            necessary and analytics cookies as described below.
          </LI>
        </UL>
      </Section>

      <Section title="Patient PHI & the BA relationship" reduce={null} index={0}>
        <P>
          When Solace processes patient PHI, it does so as a{' '}
          <Strong>Business Associate</Strong> of the covered entity, strictly to
          deliver the Services and only as the BAA permits. The covered entity,
          not Solace, is the steward of the patient relationship and the primary
          point of contact for patient privacy rights.
        </P>
        <UL>
          <LI>We do not sell patient PHI.</LI>
          <LI>We never use patient PHI to train or fine-tune AI models.</LI>
          <LI>
            Our AI plans and narrates over coded, de-identified metadata and slot
            tokens; raw identifiers are stripped before any model prompt, enforced
            by an automated leak-gate test in the build.
          </LI>
        </UL>
      </Section>

      <Section title="How we use information" reduce={null} index={0}>
        <UL>
          <LI>To provide, secure, maintain and improve the Services.</LI>
          <LI>To authenticate users and protect against fraud and abuse.</LI>
          <LI>To communicate about your account, the Services and support.</LI>
          <LI>
            To meet legal, regulatory and contractual obligations, including
            those under the BAA.
          </LI>
        </UL>
        <P>
          We do not use patient PHI for advertising, and we do not use it to train
          models. Aggregate, de-identified usage metrics that contain no PHI may
          be used to improve the Services.
        </P>
      </Section>

      <Section title="How we share information" reduce={null} index={0}>
        <UL>
          <LI>
            <Strong>With the covered entity.</Strong> Patient PHI is returned to
            and shared with the covered entity that owns the patient relationship.
          </LI>
          <LI>
            <Strong>With subprocessors.</Strong> Vetted vendors that help us run
            the Services under contract and, where PHI is involved, under a BAA.
          </LI>
          <LI>
            <Strong>For legal reasons.</Strong> When required by law or to protect
            rights, safety and the integrity of the Services.
          </LI>
          <LI>
            <Strong>In a business transfer.</Strong> Subject to this policy and
            the BAA, in connection with a merger, acquisition or sale of assets.
          </LI>
        </UL>
        <P>We do not sell personal information or patient PHI.</P>
      </Section>

      <Section title="Subprocessors" reduce={null} index={0}>
        <P>
          We rely on a small set of infrastructure subprocessors, each bound by
          contract and, where PHI is involved, by a BAA:
        </P>
        <UL>
          <LI>
            <Strong>Amazon Web Services (AWS).</Strong> HIPAA-eligible cloud
            hosting, storage and key management, under AWS&rsquo;s BAA.
          </LI>
          <LI>
            <Strong>Anthropic, via AWS Bedrock.</Strong> Model inference runs
            through Bedrock in covered regions under BAA; prompts contain only
            coded, de-identified metadata, never raw PHI.
          </LI>
        </UL>
        <P>
          A current list of subprocessors is available to customers on request.
        </P>
      </Section>

      <Section title="Retention & TTL" reduce={null} index={0}>
        <P>
          We practice data minimization. Intake sessions are short-lived, and
          patient records and media carry an <Strong>automatic TTL</Strong> that
          expires them on schedule. Magic-link tokens are single-use and stored
          only as hashes. Account and contract data are retained for as long as
          your organization uses the Services and as required by law, then
          deleted or de-identified. PHI retention and disposal follow the terms of
          the BAA.
        </P>
      </Section>

      <Section title="Security" reduce={null} index={0}>
        <P>
          We protect data with customer-managed AWS KMS encryption in transit and
          at rest, secrets held in AWS Secrets Manager, passwordless magic-link
          sign-in with short-lived JWT sessions, role-scoped access with
          tenant-isolation checks, a CloudFront + WAF edge, SSRF guards on
          outbound calls, and an append-only audit log. See our{' '}
          <Strong>Security</Strong> page for the full set of controls.
        </P>
      </Section>

      <Section title="Your rights" reduce={null} index={0}>
        <P>
          Depending on your jurisdiction, you may have rights to access, correct,
          delete, port or restrict the processing of your personal information.
          For <Strong>patient PHI</Strong>, individual rights requests are
          directed to and fulfilled by the covered entity that owns the patient
          relationship; Solace supports the covered entity in meeting them. For
          clinician and account data, contact us using the details below.
        </P>
      </Section>

      <Section title="Cookies & telemetry" reduce={null} index={0}>
        <P>
          We use strictly necessary cookies to run the Services and limited
          analytics to understand performance and reliability. Where required, we
          obtain consent for non-essential cookies, and you can control cookies
          through your browser settings.
        </P>
      </Section>

      <Section title="Children's privacy" reduce={null} index={0}>
        <P>
          The Services are intended for healthcare organizations and their staff,
          not for direct use by children. Any pediatric PHI processed during a
          visit is handled as PHI under the BAA and the covered entity&rsquo;s
          direction, not collected by Solace for its own purposes.
        </P>
      </Section>

      <Section title="International users" reduce={null} index={0}>
        <P>
          The Services are operated from, and data is processed in, the United
          States. If you access the Services from outside the United States, you
          understand that your information will be processed in the U.S., and
          where applicable we rely on appropriate safeguards for any cross-border
          transfer.
        </P>
      </Section>

      <Section title="Changes to this policy" reduce={null} index={0}>
        <P>
          We may update this policy from time to time. When we make material
          changes, we will update the &ldquo;Last updated&rdquo; date above and,
          where appropriate, provide additional notice. Your continued use of the
          Services after an update means you accept the revised policy.
        </P>
      </Section>

      <Section title="Contact us" reduce={null} index={0}>
        <P>
          Questions about this policy or our data practices? Email{' '}
          <Strong>privacy@solace.health</Strong>. We respond within one business
          day.
        </P>
        <Callout>
          Reminder: this template requires review by counsel before launch to
          ensure it reflects your final practices and the laws that apply to your
          organization.
        </Callout>
      </Section>
    </LegalLayout>
  );
}
