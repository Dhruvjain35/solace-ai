import { Link } from "react-router-dom";
import { ArrowRight, PlugZap, KeyRound, FileOutput, Boxes, RefreshCcw, FlaskConical } from "lucide-react";
import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { MarketingHero } from "../../components/marketing/MarketingHero";
import { SectionHeading } from "../../components/marketing/SectionHeading";
import { Reveal } from "../../components/marketing/Reveal";
import { FAQAccordion } from "../../components/marketing/FAQAccordion";
import { Button } from "../../components/ui/Button";

const vendors = [
  { initials: "Ep", name: "Epic", note: "SMART on FHIR R4 - USCDI reads - DocumentReference, Condition, Observation write-back" },
  { initials: "OH", name: "Oracle Health", note: "SMART on FHIR R4 - Cerner Millennium - coded write-back" },
  { initials: "at", name: "athenahealth", note: "FHIR R4 + native REST - notes, problems, allergies, vitals" },
  { initials: "SH", name: "SMART Health IT", note: "Open sandbox - evaluate the full integration with zero credentials" },
];

const capabilities = [
  { Icon: KeyRound, title: "SMART on FHIR, v2 scopes", desc: "Standards-based clinician sign-in with PKCE, OIDC nonce validation, and granular v2 resource scopes — minimum-necessary by default." },
  { Icon: RefreshCcw, title: "Read and write-back", desc: "Patient match, chart reads, and coded write-back — notes as DocumentReference, diagnoses as Condition, acuity as Observation — with provenance attached." },
  { Icon: FileOutput, title: "Bulk export ready", desc: "FHIR Bulk Data ($export) with Backend Services auth, plus Subscriptions for event-driven workflows." },
  { Icon: Boxes, title: "Per-workspace configuration", desc: "Each department or clinic binds its own EHR config — vendor, endpoints, scopes — with secrets held in AWS Secrets Manager, never in the app." },
  { Icon: FlaskConical, title: "Conformance-tested", desc: "US Core profiles and SMART v2 flows exercised by an automated conformance suite on every release." },
  { Icon: PlugZap, title: "One gateway, any vendor", desc: "A vendor-agnostic FHIR gateway routes each call through vendor-specific adapters — your workflows don't change when the EHR does." },
];

const faqs = [
  { q: "We're on Epic. What does setup look like?", a: "Connect Solace's registered SMART app from your Epic environment, bind it to a workspace in the EHR hub, and sign in with your Epic credentials. Sandbox-first evaluation is supported." },
  { q: "Can we try it without involving our EHR team?", a: "Yes — the SMART Health IT sandbox connection works out of the box with zero credentials, using synthetic patients." },
  { q: "What gets written back to our EHR?", a: "Only what a clinician confirms: notes, diagnoses, observations, and orders, each coded (LOINC/SNOMED/ICD-10/RxNorm) and tagged with decision-support provenance." },
  { q: "Do you store our EHR credentials?", a: "Client secrets and signing keys live in AWS Secrets Manager under customer-managed encryption. The app stores references, never raw secrets." },
];

export default function IntegrationsPage() {
  return (
    <MarketingLayout>
      <MarketingHero
        eyebrow="Integrations"
        title="Works with the EHR you already run."
        sub="SMART on FHIR R4 with v2 scopes, write-back, and bulk export — Epic, Oracle Health, athenahealth, and any SMART-conformant system."
        primaryCta={{ to: "/get-started", label: "Get started" }}
        secondaryCta={{ to: "/contact", label: "Talk to integrations" }}
      />

      {/* Vendor strip */}
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
        <SectionHeading
          eyebrow="Vendors"
          title="Standards over one-off integrations."
          sub="Built on FHIR R4 — so 'supported' means certified pathways, not brittle point connections."
        />
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {vendors.map((v, i) => (
            <Reveal key={v.name} delay={i * 0.06}>
              <div className="card-clean h-full rounded-xl p-6 text-center">
                <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary-dim/60 font-display text-lg text-primary">
                  {v.initials}
                </span>
                <h3 className="mt-4 font-medium text-ink">{v.name}</h3>
                <p className="mt-2 text-xs leading-relaxed text-text-muted">{v.note}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Capabilities */}
      <section className="section-low">
        <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
          <SectionHeading eyebrow="Under the hood" title="Interop that holds up in production." />
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {capabilities.map(({ Icon, title, desc }, i) => (
              <Reveal key={title} delay={i * 0.05}>
                <div className="card-clean h-full rounded-xl p-7">
                  <Icon size={20} className="text-primary" aria-hidden="true" />
                  <h3 className="mt-3 text-lg font-medium text-ink">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-text-muted">{desc}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* Sandbox CTA */}
      <section className="mx-auto max-w-4xl px-4 py-20 text-center sm:px-6">
        <Reveal>
          <div className="card-clean rounded-xl p-10">
            <h3 className="font-display text-2xl tracking-editorial text-ink sm:text-3xl">
              Evaluate the full integration today — no credentials needed.
            </h3>
            <p className="mx-auto mt-3 max-w-xl text-sm text-text-muted">
              Every workspace can connect the SMART Health IT sandbox in one click: synthetic patients, real
              FHIR, the exact same read and write-back paths we run against Epic.
            </p>
            <Link to="/get-started" className="mt-6 inline-block">
              <Button shape="pill" className="h-12 px-7">
                Create a workspace <ArrowRight size={16} aria-hidden="true" />
              </Button>
            </Link>
          </div>
        </Reveal>
      </section>

      <section className="section-low">
        <div className="mx-auto max-w-3xl px-4 py-20 sm:px-6">
          <SectionHeading eyebrow="FAQ" title="Questions, answered." />
          <Reveal className="mt-10">
            <FAQAccordion items={faqs} />
          </Reveal>
        </div>
      </section>
    </MarketingLayout>
  );
}
