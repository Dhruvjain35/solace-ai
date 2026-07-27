/* ============================================================================
   INTEGRATIONS — the single source of truth for every EHR platform Solace
   talks about. Ported from legacy/src/lib/integrations.tsx and
   legacy/src/components/integrations/guideSteps.tsx.

   The legacy record carried a React `mark` node full of vendor brand hex.
   This build drops it: the house lockup is the real 64px vendor mark set in
   grayscale next to the name in our own type (see IntegrationWall), so all a
   record needs is an optional path to that mark. Vendors we hold no file for
   render the name alone against a hollow glyph.
   ========================================================================= */

export type IntegrationTier = 'native' | 'smart';

export type Integration = {
  slug: string;
  name: string;
  /** 64px vendor mark in public/assets/logos. Absent where we hold no file. */
  logo?: string;
  /** One-line positioning used on the hub cards. */
  blurb: string;
  /** 'native' = shipped vendor adapter in the product; 'smart' = standard SMART on FHIR path. */
  tier: IntegrationTier;
};

export const INTEGRATIONS: Integration[] = [
  {
    slug: 'epic',
    name: 'Epic',
    logo: '/assets/logos/epic.png',
    blurb: 'SMART on FHIR R4 with USCDI reads and coded write-back into the Epic chart.',
    tier: 'native',
  },
  {
    slug: 'oracle-health',
    name: 'Oracle Health',
    logo: '/assets/logos/cerner.png',
    blurb: 'Cerner Millennium connectivity over SMART on FHIR R4 with write-back.',
    tier: 'native',
  },
  {
    slug: 'athenahealth',
    name: 'athenahealth',
    logo: '/assets/logos/athenahealth.png',
    blurb: 'Dual-surface adapter: FHIR R4 plus athena’s native REST for problems, allergies and vitals.',
    tier: 'native',
  },
  {
    slug: 'cerner',
    name: 'Cerner',
    logo: '/assets/logos/cerner.png',
    blurb: 'Millennium-era Cerner estates connect through the same Oracle Health pathway.',
    tier: 'native',
  },
  {
    slug: 'nextgen',
    name: 'NextGen Healthcare',
    logo: '/assets/logos/nextgen.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'elation',
    name: 'Elation Health',
    logo: '/assets/logos/elation.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'drchrono',
    name: 'DrChrono',
    logo: '/assets/logos/drchrono.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'eclinicalworks',
    name: 'eClinicalWorks',
    logo: '/assets/logos/eclinicalworks.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'advancedmd',
    name: 'AdvancedMD',
    logo: '/assets/logos/advancedmd.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'veradigm',
    name: 'Veradigm',
    logo: '/assets/logos/veradigm.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'meditech',
    name: 'MEDITECH',
    logo: '/assets/logos/meditech.png',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'practice-fusion',
    name: 'Practice Fusion',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'greenway',
    name: 'Greenway Health',
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'smart-on-fhir',
    name: 'SMART on FHIR',
    blurb: 'The open standard underneath every Solace connection. Try it on the public sandbox today.',
    tier: 'native',
  },
];

export const getIntegration = (slug: string): Integration | undefined =>
  INTEGRATIONS.find((i) => i.slug === slug);

export const tierLabel = (tier: IntegrationTier): string =>
  tier === 'native' ? 'Native adapter' : 'SMART on FHIR';

/* ── The connect guide ─────────────────────────────────────────────────────
   NATIVE vendors get the full, named vendor pathway (developer console,
   redirect URI + v2 scopes, workspace bind, SSO sign-in, write-back
   confirmation). SMART-tier vendors get the generic, sandbox-first SMART on
   FHIR R4 path. Copy is generated per vendor from the Integration record so it
   reads specific without a hand-written block each. Legacy paired every step
   with a lucide icon; the icons carried no information the numbered rule and
   the title do not, so they are gone. ──────────────────────────────────── */

export type GuideStep = { title: string; body: string };

/** Where each native vendor's SMART app is registered, by name. Falls back to a
    generic developer console for any native vendor not listed. */
const NATIVE_CONSOLE: Record<string, string> = {
  epic: 'the Epic on FHIR developer portal (and submit to App Orchard / Showroom for production)',
  'oracle-health': 'the Oracle Health (Cerner) code Console at code.cerner.com',
  cerner: 'the Oracle Health (Cerner) code Console at code.cerner.com',
  athenahealth: 'the athenahealth Marketplace developer portal (Developer Toolkit)',
  'smart-on-fhir': 'the SMART App Launcher and your FHIR server’s app registry',
};

export function getGuideSteps(item: Integration): GuideStep[] {
  if (item.tier === 'native') {
    const console = NATIVE_CONSOLE[item.slug] ?? `your ${item.name} developer console`;
    return [
      {
        title: `Register Solace in ${item.name}`,
        body: `Register the Solace SMART app in ${console}. You control the listing, so the connection lives inside your ${item.name} tenant, not a third-party bridge.`,
      },
      {
        title: 'Add the redirect URI and minimum scopes',
        body: 'Add Solace’s redirect URI and request only the minimum-necessary SMART v2 scopes: patient/observation.read, document.write and the few your workflow needs. Nothing broad, nothing unused.',
      },
      {
        title: 'Bind the app to your workspace',
        body: `In Solace, open Tools → EHR connections and bind the registered ${item.name} app to your workspace. Paste the client ID and FHIR base URL; secrets go straight into the vault.`,
      },
      {
        title: `Sign in with ${item.name} SSO`,
        body: `A clinician signs in with ${item.name} single sign-on. Solace launches in context, matches the patient and reads the chart, no separate password, no copy-paste.`,
      },
      {
        title: 'Confirm a coded write-back',
        body: `Push a test note and watch it land in ${item.name} as a coded FHIR DocumentReference, with problems and observations written back in standard codes. Every write is audited.`,
      },
    ];
  }

  // SMART-tier: the generic SMART on FHIR R4 path, sandbox-first.
  return [
    {
      title: 'Try it on the SMART sandbox first',
      body: `Point Solace at the public SMART Health IT sandbox to see the full read-and-write loop against ${item.name}-style FHIR R4 data, no ${item.name} credentials required.`,
    },
    {
      title: `Register Solace with ${item.name}`,
      body: `Register the Solace SMART app on your ${item.name} FHIR endpoint, add the redirect URI and request the minimum-necessary SMART v2 scopes for reads and document write-back.`,
    },
    {
      title: 'Bind the app to your workspace',
      body: `In Solace, open Tools → EHR connections, enter your ${item.name} FHIR base URL and client ID, and bind the connection to your workspace. Secrets stay in the vault.`,
    },
    {
      title: 'Sign in and read the chart',
      body: 'A clinician authorizes the launch; Solace matches the patient and reads demographics, problems, medications and allergies over standard FHIR R4 USCDI.',
    },
    {
      title: 'Write the visit back',
      body: `The ambient note posts back to ${item.name} as a coded DocumentReference. If your ${item.name} edition supports write, problems and observations follow as standard FHIR resources.`,
    },
  ];
}
