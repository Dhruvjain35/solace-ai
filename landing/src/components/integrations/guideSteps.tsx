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

/*
 * The "what you get once connected" band no longer reuses static screenshots:
 * IntegrationGuide.tsx now renders the live Atlas EhrScreen (the chart Solace
 * reads/writes) plus the ScopeCard and WriteBackCard from GuideVisuals.tsx,
 * each a specific, in-DOM visual. The old CAPABILITIES array is gone.
 */
