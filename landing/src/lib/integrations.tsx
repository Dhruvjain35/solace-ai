import type { ReactNode } from 'react';
import { Leaf, Asterisk } from 'lucide-react';

/*
 * The single source of truth for every EHR platform Solace talks about:
 * the marquee, the /integrations hub and the per-platform guide pages all
 * read from this list. `logo` files live in public/assets/integrations/
 * (<slug>.png, transparent); when a file is missing the brand-styled
 * wordmark renders instead, so logos can be dropped in with zero code.
 */

export type Integration = {
  slug: string;
  name: string;
  /** Brand-styled wordmark fallback when no logo file exists. */
  mark: ReactNode;
  /** One-line positioning used on the hub cards. */
  blurb: string;
  /** 'native' = shipped vendor adapter in the product; 'smart' = standard SMART on FHIR path. */
  tier: 'native' | 'smart';
};

export const INTEGRATIONS: Integration[] = [
  {
    slug: 'epic',
    name: 'Epic',
    mark: <span className="text-[24px] font-extrabold italic tracking-tight text-[#A4123F]">Epic</span>,
    blurb: 'SMART on FHIR R4 with USCDI reads and coded write-back into the Epic chart.',
    tier: 'native',
  },
  {
    slug: 'oracle-health',
    name: 'Oracle Health',
    mark: <span className="text-[20px] font-semibold tracking-tight text-[#C74634]">Oracle Health</span>,
    blurb: 'Cerner Millennium connectivity over SMART on FHIR R4 with write-back.',
    tier: 'native',
  },
  {
    slug: 'athenahealth',
    name: 'athenahealth',
    mark: (
      <span className="flex items-center gap-1.5 text-[19px] font-semibold tracking-tight text-[#582C83]">
        <Leaf size={17} className="text-[#7AB800]" aria-hidden="true" />athenahealth
      </span>
    ),
    blurb: 'Dual-surface adapter: FHIR R4 plus athena’s native REST for problems, allergies and vitals.',
    tier: 'native',
  },
  {
    slug: 'cerner',
    name: 'Cerner',
    mark: <span className="text-[22px] font-semibold tracking-tight text-[#1A9CA6]">Cerner</span>,
    blurb: 'Millennium-era Cerner estates connect through the same Oracle Health pathway.',
    tier: 'native',
  },
  {
    slug: 'nextgen',
    name: 'NextGen Healthcare',
    mark: <span className="text-[21px] font-bold lowercase tracking-tight text-[#E0531F]">nextgen<span className="text-ink">.</span></span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'elation',
    name: 'Elation Health',
    mark: (
      <span className="flex items-center text-[21px] font-medium tracking-tight text-[#16A3C7]">
        <Asterisk size={18} strokeWidth={2.5} aria-hidden="true" />Elation
      </span>
    ),
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'drchrono',
    name: 'DrChrono',
    mark: <span className="text-[20px] font-semibold tracking-tight text-[#3CAE2B]">dr<span className="text-ink">chrono</span></span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'eclinicalworks',
    name: 'eClinicalWorks',
    mark: <span className="whitespace-nowrap text-[18px] font-semibold italic tracking-tight text-[#1C2B4A]">eClinicalWorks</span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'advancedmd',
    name: 'AdvancedMD',
    mark: <span className="text-[20px] font-semibold tracking-tight text-[#3C4651]">Advanced<span className="text-[#E8772E]">MD</span></span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'veradigm',
    name: 'Veradigm',
    mark: <span className="text-[20px] font-semibold tracking-tight text-[#2A1A57]">veradigm</span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'meditech',
    name: 'MEDITECH',
    mark: <span className="text-[18px] font-bold tracking-[0.04em] text-[#3FAE6B]">MEDITECH</span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'practice-fusion',
    name: 'Practice Fusion',
    mark: <span className="whitespace-nowrap text-[18px] font-semibold tracking-tight text-[#1C3D6E]">practice<span className="text-[#3AA6E0]">fusion</span></span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'greenway',
    name: 'Greenway Health',
    mark: <span className="whitespace-nowrap text-[19px] font-bold tracking-tight text-[#3C4651]">Greenway <span className="text-[#2BB673]">Health</span></span>,
    blurb: 'Standards-based connection over SMART on FHIR R4.',
    tier: 'smart',
  },
  {
    slug: 'smart-on-fhir',
    name: 'SMART on FHIR',
    mark: <span className="whitespace-nowrap text-[19px] font-semibold tracking-tight text-ink">SMART <span className="text-solace-green-600">on FHIR</span></span>,
    blurb: 'The open standard underneath every Solace connection. Try it on the public sandbox today.',
    tier: 'native',
  },
];

export const getIntegration = (slug: string) =>
  INTEGRATIONS.find((i) => i.slug === slug);
