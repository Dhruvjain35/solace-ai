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
 * Terms — Solace's long-form Terms of Service. Original content covering
 * acceptance, eligibility, accounts, acceptable use, the BAA governing PHI,
 * intellectual property, the clinical-decision-support disclaimer (triage aid
 * only, not a medical device claim), warranties, limitation of liability,
 * indemnity, termination, governing law, changes and contact. Built on the
 * shared LegalLayout shell with a sticky TOC; a counsel-review notice frames it.
 */

const SECTIONS: LegalSection[] = [
  { id: 'acceptance', title: 'Acceptance of terms' },
  { id: 'eligibility', title: 'Eligibility' },
  { id: 'accounts', title: 'Accounts & access' },
  { id: 'acceptable-use', title: 'Acceptable use' },
  { id: 'phi-and-the-baa', title: 'PHI & the BAA' },
  { id: 'clinical-disclaimer', title: 'Clinical-decision-support disclaimer' },
  { id: 'intellectual-property', title: 'Intellectual property' },
  { id: 'warranties', title: 'Warranties & disclaimers' },
  { id: 'limitation-of-liability', title: 'Limitation of liability' },
  { id: 'indemnification', title: 'Indemnification' },
  { id: 'term-termination', title: 'Term & termination' },
  { id: 'governing-law', title: 'Governing law' },
  { id: 'changes', title: 'Changes to these terms' },
  { id: 'contact', title: 'Contact us' },
];

export default function Terms() {
  return (
    <LegalLayout
      eyebrow="Terms of service"
      title="The terms behind the trust."
      sub="The agreement that governs your use of Solace, written for the clinicians and organizations who depend on it."
      lastUpdated="[DATE]"
      sections={SECTIONS}
    >
      <Section title="Acceptance of terms" reduce={null} index={0}>
        <Callout>
          This is a template agreement provided for information only. It is not
          legal advice and must be reviewed and adapted by qualified counsel
          before launch.
        </Callout>
        <P>
          These Terms of Service (the &ldquo;Terms&rdquo;) govern your access to
          and use of the Solace patient-intake and clinical-triage services (the
          &ldquo;Services&rdquo;) provided by Solace AI, Inc.
          (&ldquo;Solace&rdquo;). By accessing or using the Services, you agree to
          these Terms. Where a separate master services agreement or order form
          exists between Solace and your organization, that agreement controls if
          it conflicts with these Terms.
        </P>
      </Section>

      <Section title="Eligibility" reduce={null} index={0}>
        <P>
          The Services are intended solely for use by{' '}
          <Strong>licensed clinicians and healthcare organizations</Strong> and
          their authorized staff, in the course of providing or supporting care.
          By using the Services you represent that you are authorized to act on
          behalf of your organization and to bind it to these Terms.
        </P>
      </Section>

      <Section title="Accounts & access" reduce={null} index={0}>
        <UL>
          <LI>
            Access is granted through passwordless magic-link sign-in; keep your
            access credentials and devices secure.
          </LI>
          <LI>
            You are responsible for activity under your account and for ensuring
            your staff use the Services in line with these Terms and applicable
            law.
          </LI>
          <LI>
            Notify us promptly of any unauthorized access or suspected security
            incident.
          </LI>
        </UL>
      </Section>

      <Section title="Acceptable use" reduce={null} index={0}>
        <P>You agree not to:</P>
        <UL>
          <LI>Use the Services unlawfully or in violation of any patient&rsquo;s rights.</LI>
          <LI>Attempt to bypass the consent gate, PHI-isolation or access controls.</LI>
          <LI>
            Reverse engineer, probe or interfere with the Services except as the
            law expressly permits.
          </LI>
          <LI>Submit data you lack the right or authorization to submit.</LI>
          <LI>Use the Services to build a competing product or to train models.</LI>
        </UL>
      </Section>

      <Section title="PHI & the BAA" reduce={null} index={0}>
        <P>
          To the extent the Services involve protected health information,{' '}
          <Strong>the Business Associate Agreement (BAA)</Strong> between Solace
          and your organization governs the handling of that PHI. The BAA controls
          over these Terms with respect to PHI. Solace processes PHI only as the
          BAA permits, applies the minimum-necessary standard, and does not use
          PHI to train models or for advertising.
        </P>
      </Section>

      <Section title="Clinical-decision-support disclaimer" reduce={null} index={0}>
        <P>
          Solace is a <Strong>clinical-decision-support and triage aid</Strong>.
          It surfaces summaries, prioritization signals and drafted documentation
          to assist qualified clinicians. It does not practice medicine, does not
          diagnose, and does not replace clinical judgment.
        </P>
        <UL>
          <LI>
            <Strong>The clinician makes the final call</Strong> on every triage
            decision, order and chart entry.
          </LI>
          <LI>
            Write-backs are confirm-gated; nothing reaches the chart without a
            clinician&rsquo;s explicit approval.
          </LI>
          <LI>
            The Services are not intended to be, and are not marketed as, a
            regulated medical device, and no medical-device claim is made.
          </LI>
        </UL>
      </Section>

      <Section title="Intellectual property" reduce={null} index={0}>
        <P>
          Solace and its licensors own all rights in the Services, including the
          software, models, interfaces and content, excluding your data. We grant
          your organization a limited, non-exclusive, non-transferable right to
          use the Services during your subscription. Your organization retains all
          rights in the data it submits, subject to the BAA.
        </P>
      </Section>

      <Section title="Warranties & disclaimers" reduce={null} index={0}>
        <P>
          The Services are provided on an &ldquo;as is&rdquo; and &ldquo;as
          available&rdquo; basis. To the fullest extent permitted by law, Solace
          disclaims all warranties, express or implied, including merchantability,
          fitness for a particular purpose and non-infringement. We do not warrant
          that the Services will be uninterrupted, error-free or that any output
          is appropriate for a particular clinical situation.
        </P>
      </Section>

      <Section title="Limitation of liability" reduce={null} index={0}>
        <P>
          To the fullest extent permitted by law, neither party will be liable for
          indirect, incidental, special, consequential or punitive damages, or for
          lost profits or revenues. Solace&rsquo;s aggregate liability arising out
          of or related to the Services will not exceed the amounts paid by your
          organization for the Services in the twelve months preceding the claim,
          except where a higher limit is set in your master services agreement.
        </P>
      </Section>

      <Section title="Indemnification" reduce={null} index={0}>
        <P>
          Your organization will defend and indemnify Solace against third-party
          claims arising from your misuse of the Services, your breach of these
          Terms, or your violation of applicable law or any patient&rsquo;s
          rights, except to the extent caused by Solace&rsquo;s own breach.
        </P>
      </Section>

      <Section title="Term & termination" reduce={null} index={0}>
        <P>
          These Terms apply while you use the Services. Either party may terminate
          as set out in your master services agreement, or for material breach
          that goes uncured after notice. On termination, your right to use the
          Services ends, and PHI is returned or disposed of as the BAA requires.
        </P>
      </Section>

      <Section title="Governing law" reduce={null} index={0}>
        <P>
          These Terms are governed by the laws of the State of Delaware, without
          regard to its conflict-of-laws rules, unless your master services
          agreement specifies otherwise. The parties consent to the exclusive
          jurisdiction of the courts located there for disputes not subject to
          that agreement.
        </P>
      </Section>

      <Section title="Changes to these terms" reduce={null} index={0}>
        <P>
          We may update these Terms from time to time. When changes are material,
          we will update the &ldquo;Last updated&rdquo; date above and, where
          appropriate, provide additional notice. Continued use of the Services
          after an update means you accept the revised Terms.
        </P>
      </Section>

      <Section title="Contact us" reduce={null} index={0}>
        <P>
          Questions about these Terms? Email <Strong>legal@solace.health</Strong>.
          We respond within one business day.
        </P>
        <Callout>
          Reminder: this template requires review by counsel before launch to
          ensure it reflects your final commercial terms and the laws that apply
          to your organization.
        </Callout>
      </Section>
    </LegalLayout>
  );
}
