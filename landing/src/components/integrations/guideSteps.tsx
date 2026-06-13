import type { LucideIcon } from 'lucide-react';
import {
  AppWindow,
  KeyRound,
  Link2,
  LogIn,
  CheckCircle2,
  FlaskConical,
  Search,
  PenLine,
} from 'lucide-react';
import type { Integration } from '../../lib/integrations';

/*
 * The connect guide for each platform. NATIVE vendors get the full, named
 * vendor pathway (developer console, redirect URI + v2 scopes, workspace bind,
 * SSO sign-in, write-back confirmation). SMART-tier vendors get the generic,
 * sandbox-first SMART on FHIR R4 path. Copy is generated per vendor from the
 * Integration record so it reads specific without a hand-written block each.
 */

export type GuideStep = {
  title: string;
  body: string;
  Icon: LucideIcon;
};

// Where each native vendor's SMART app is registered, by name. Falls back to a
// generic developer console for any native vendor not listed.
const NATIVE_CONSOLE: Record<string, string> = {
  epic: 'the Epic on FHIR developer portal (and submit to App Orchard / Showroom for production)',
  'oracle-health':
    'the Oracle Health (Cerner) code Console at code.cerner.com',
  cerner: 'the Oracle Health (Cerner) code Console at code.cerner.com',
  athenahealth:
    'the athenahealth Marketplace developer portal (Developer Toolkit)',
  'smart-on-fhir': 'the SMART App Launcher and your FHIR server’s app registry',
};

export function getGuideSteps(item: Integration): GuideStep[] {
  if (item.tier === 'native') {
    const console = NATIVE_CONSOLE[item.slug] ?? `your ${item.name} developer console`;
    return [
      {
        title: `Register Solace in ${item.name}`,
        body: `Register the Solace SMART app in ${console}. You control the listing, so the connection lives inside your ${item.name} tenant, not a third-party bridge.`,
        Icon: AppWindow,
      },
      {
        title: 'Add the redirect URI and minimum scopes',
        body: `Add Solace’s redirect URI and request only the minimum-necessary SMART v2 scopes — patient/observation.read, document.write and the few your workflow needs. Nothing broad, nothing unused.`,
        Icon: KeyRound,
      },
      {
        title: 'Bind the app to your workspace',
        body: `In Solace, open Tools → EHR connections and bind the registered ${item.name} app to your workspace. Paste the client ID and FHIR base URL; secrets go straight into the vault.`,
        Icon: Link2,
      },
      {
        title: `Sign in with ${item.name} SSO`,
        body: `A clinician signs in with ${item.name} single sign-on. Solace launches in context, matches the patient and reads the chart — no separate password, no copy-paste.`,
        Icon: LogIn,
      },
      {
        title: `Confirm a coded write-back`,
        body: `Push a test note and watch it land in ${item.name} as a coded FHIR DocumentReference, with problems and observations written back in standard codes. Every write is audited.`,
        Icon: CheckCircle2,
      },
    ];
  }

  // SMART-tier: the generic SMART on FHIR R4 path, sandbox-first.
  return [
    {
      title: 'Try it on the SMART sandbox first',
      body: `Point Solace at the public SMART Health IT sandbox to see the full read-and-write loop against ${item.name}-style FHIR R4 data — no ${item.name} credentials required.`,
      Icon: FlaskConical,
    },
    {
      title: `Register Solace with ${item.name}`,
      body: `Register the Solace SMART app on your ${item.name} FHIR endpoint, add the redirect URI and request the minimum-necessary SMART v2 scopes for reads and document write-back.`,
      Icon: AppWindow,
    },
    {
      title: 'Bind the app to your workspace',
      body: `In Solace, open Tools → EHR connections, enter your ${item.name} FHIR base URL and client ID, and bind the connection to your workspace. Secrets stay in the vault.`,
      Icon: Link2,
    },
    {
      title: 'Sign in and read the chart',
      body: `A clinician authorizes the launch; Solace matches the patient and reads demographics, problems, medications and allergies over standard FHIR R4 USCDI.`,
      Icon: Search,
    },
    {
      title: 'Write the visit back',
      body: `The ambient note posts back to ${item.name} as a coded DocumentReference. If your ${item.name} edition supports write, problems and observations follow as standard FHIR resources.`,
      Icon: PenLine,
    },
  ];
}

// "What you can do once connected" — four capabilities, each paired with a real
// product or patient-app screenshot framed in a rounded card on the guide page.
export type Capability = {
  title: string;
  body: string;
  Icon: LucideIcon;
  shot: string;
  shotAlt: string;
  caption: string;
};

export const CAPABILITIES: Capability[] = [
  {
    title: 'Patient match & chart read',
    body: 'Solace matches the patient on launch and reads demographics, problems, medications and allergies over USCDI — the chart is open before the clinician walks in.',
    Icon: Search,
    shot: '/assets/shots/ehr-clean.png',
    shotAlt: 'The Solace clinician view with the patient chart read in',
    caption: 'The chart, read and summarized on launch.',
  },
  {
    title: 'Ambient scribe write-back',
    body: 'The visit note drafts as the clinician talks, then posts back as a coded FHIR DocumentReference for review and sign-off in the chart you already keep.',
    Icon: PenLine,
    shot: '/assets/shots/working.png',
    shotAlt: 'The ambient scribe drafting a note during the visit',
    caption: 'The note drafts live, then writes back coded.',
  },
  {
    title: 'Coded problems, observations & orders',
    body: 'Problems, observations and suggested orders are written as standard FHIR resources in real codes — not free text — so they flow straight into your downstream systems.',
    Icon: CheckCircle2,
    shot: '/assets/shots/ehr.png',
    shotAlt: 'Coded problems and observations in the Solace clinician view',
    caption: 'Coded resources, ready for the record.',
  },
  {
    title: 'Patient-reported intake, structured',
    body: 'Everything the patient tells Solace on their own phone — symptoms, history, insurance — lands as a clean structured record that maps to the chart, no clipboard.',
    Icon: AppWindow,
    shot: '/assets/screens/symptoms.png',
    shotAlt: 'The Solace patient intake app capturing symptoms',
    caption: 'Patient-reported intake, captured in their words.',
  },
];
