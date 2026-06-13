import { Link } from 'react-router-dom';
import Logo from './ui/Logo';

const COLS = [
  { title: 'Product', links: [['Voice Intake', '/product'], ['Triage Engine', '/product'], ['Pre-Brief & Scribe', '/product'], ['Phone Agent', '/product']] },
  { title: 'Use cases', links: [['Emergency Departments', '/clinicians'], ['Urgent Care', '/clinicians'], ['Triage Nurses', '/clinicians'], ['Patients (LEP)', '/clinicians']] },
  { title: 'Company', links: [['About', '/company'], ['How it works', '/how-it-works'], ['Integrations', '/integrations'], ['Pricing', '/pricing'], ['Contact', '/contact']] },
  { title: 'Legal', links: [['Security', '/security'], ['HIPAA', '/hipaa'], ['Privacy', '/privacy'], ['Terms', '/terms']] },
] as const;


export default function Footer() {
  return (
    <footer id="footer" className="border-t border-black/5 bg-offwhite px-6 pt-20 pb-10 text-ink">
      <div className="mx-auto max-w-[1200px]">
        <div className="grid gap-12 md:grid-cols-[1.6fr_repeat(4,1fr)]">
          <div className="max-w-xs">
            <Logo />
            <p className="mt-4 text-sm leading-relaxed text-muted">
              AI-native patient intake and clinical triage for the emergency department.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-2.5">
              <span className="inline-flex items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2">
                {/* the recognized HIPAA shield mark, drawn inline */}
                <svg viewBox="0 0 24 28" className="h-5 w-auto" aria-hidden="true">
                  <path
                    d="M12 0 L24 4.5 V13 c0 7.6-5 12.6-12 15-7-2.4-12-7.4-12-15 V4.5 Z"
                    fill="#1c6bb5"
                  />
                  <path
                    d="M10.3 6.5 h3.4 v3.8 h3.8 v3.4 h-3.8 v3.8 h-3.4 v-3.8 H6.5 v-3.4 h3.8 Z"
                    fill="#ffffff"
                  />
                </svg>
                <span className="font-sofia text-lg font-semibold leading-none tracking-[-0.02em] text-[#1c6bb5]">
                  HIPAA
                </span>
                <span className="font-sofia text-[11px] font-medium uppercase tracking-wide text-muted">Compliant</span>
              </span>
              <span className="inline-flex items-center gap-2 rounded-xl border border-black/10 bg-white px-3 py-2">
                <img src="/assets/logos/aws.svg" alt="AWS" className="h-5 w-auto" />
                <span className="font-sofia text-[11px] font-medium uppercase tracking-wide text-muted">BAA signed</span>
              </span>
            </div>
          </div>
          {COLS.map((col) => (
            <div key={col.title}>
              <p className="text-sm font-semibold text-ink">{col.title}</p>
              <ul className="mt-4 space-y-3">
                {col.links.map(([label, to]) => (
                  <li key={label}>
                    <Link to={to} className="text-sm text-muted transition-colors hover:text-solace-green-700">
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-16 flex flex-col items-center justify-between gap-4 border-t border-black/8 pt-8 text-xs text-muted sm:flex-row">
          <p>© {new Date().getFullYear()} Solace AI, Inc. All rights reserved.</p>
          <p className="mx-auto max-w-sm text-center [text-wrap:balance]">Encrypted at rest &amp; in transit · PHI redacted before any model call</p>
        </div>
      </div>
    </footer>
  );
}
