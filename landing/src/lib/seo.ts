/*
 * Per-route SEO. The site is a SPA, so every route would otherwise share the
 * one static <title>/description baked into index.html. applyMeta() updates the
 * title, description, and the Open Graph / Twitter card fields on navigation, so
 * every page tells search engines and social previews the right story.
 */
import { getIntegration } from './integrations';

type Meta = { title: string; description: string };

const SITE = 'Solace';

const DEFAULT: Meta = {
  title: 'Solace — AI-native intake & triage for the emergency department',
  description:
    'Solace turns ED intake into a calm, AI-native workflow: multilingual voice intake for patients and an instant, explainable acuity pre-brief for clinicians.',
};

const MAP: Record<string, Meta> = {
  '/': DEFAULT,
  '/how-it-works': {
    title: 'How it works — from QR check-in to explainable triage · Solace',
    description:
      'The whole Solace flow: a patient checks in by voice from a QR code, and the care team meets an explainable acuity pre-brief before the patient reaches a bed.',
  },
  '/clinicians': {
    title: 'For clinicians — meet the story before the patient · Solace',
    description:
      'A clear summary, the dangerous causes to rule out, and the suggested tests, ready while your patient is still in the waiting room.',
  },
  '/integrations': {
    title: 'Integrations — connect Solace to the EHR you already run',
    description:
      'Built on SMART on FHIR R4. Solace connects to Epic, Oracle Health, athenahealth and any standards-based EHR, with coded write-back and no rip-and-replace.',
  },
  '/security': {
    title: 'Security — built so the model never touches PHI · Solace',
    description:
      'PHI isolation enforced in code, consent-gated AI, confirm-gated write-backs, customer-managed encryption, and a leak-gate test that fails the build if PHI could reach a prompt.',
  },
  '/hipaa': {
    title: 'HIPAA compliance — handled as a Business Associate · Solace',
    description:
      'How Solace meets the Privacy, Security and Breach Notification Rules as a HIPAA Business Associate, and exactly what your organization gets when you bring us in.',
  },
  '/privacy': {
    title: 'Privacy Policy · Solace',
    description:
      'How Solace collects, uses and protects information, the Business-Associate relationship for patient PHI, subprocessors, retention, and your rights.',
  },
  '/terms': {
    title: 'Terms of Service · Solace',
    description:
      'The terms that govern your use of Solace, written for licensed clinicians and healthcare organizations, including the clinical-decision-support disclaimer.',
  },
  '/contact': {
    title: 'Contact Solace — book a demo or a security review',
    description:
      'Demos, security reviews, integration questions, support or press — tell us what you need and the right person on our team will reply within one business day.',
  },
  '/demo': {
    title: 'Book a demo — see Solace on your floor',
    description:
      'A live walkthrough on a workflow that looks like yours, in about 20 minutes. Nothing to install, HIPAA-grade from the first call.',
  },
  '/pricing': {
    title: 'Pricing — simple, honest pricing · Solace',
    description:
      'Start free on your own, then bring the whole team. Everything in your tier is included, nothing sold back to you feature by feature.',
  },
  '/company': {
    title: 'Company — calm should be standard care · Solace',
    description:
      'We are building emergency rooms where no one waits in the dark, not patients, and not the people caring for them.',
  },
};

export function metaForPath(path: string): Meta {
  if (MAP[path]) return MAP[path];
  const m = path.match(/^\/integrations\/(.+)$/);
  if (m) {
    const item = getIntegration(m[1]);
    if (item) {
      return {
        title: `${item.name} integration — connect over SMART on FHIR · ${SITE}`,
        description: `Connect Solace to ${item.name}: a step-by-step guide, the minimum-necessary scopes, and coded, confirm-gated write-back.`,
      };
    }
  }
  return DEFAULT;
}

function setTag(key: string, content: string, attr: 'name' | 'property' = 'name') {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

export function applyMeta(path: string): void {
  const { title, description } = metaForPath(path);
  document.title = title;
  setTag('description', description);
  setTag('og:title', title, 'property');
  setTag('og:description', description, 'property');
  setTag('og:url', `${window.location.origin}${path}`, 'property');
  setTag('twitter:title', title);
  setTag('twitter:description', description);
}
