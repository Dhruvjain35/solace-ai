import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Reveal } from "./Reveal";
import { Button } from "../ui/Button";

const columns: { title: string; links: { to: string; label: string }[] }[] = [
  {
    title: "Products",
    links: [
      { to: "/scribe", label: "AI Scribe" },
      { to: "/triage", label: "Smart Triage" },
      { to: "/copilot", label: "EHR Copilot" },
      { to: "/integrations", label: "Integrations" },
    ],
  },
  {
    title: "Company",
    links: [
      { to: "/about", label: "About" },
      { to: "/contact", label: "Contact" },
      { to: "/get-started", label: "Get started" },
    ],
  },
  {
    title: "Trust",
    links: [
      { to: "/security", label: "Security" },
      { to: "/trust", label: "Trust report" },
    ],
  },
];

/** Dark CTA band + site footer used on every marketing page. */
export function MarketingFooter() {
  return (
    <footer>
      {/* CTA band */}
      <div className="bg-primary bg-primary-gradient">
        <Reveal className="mx-auto flex max-w-6xl flex-col items-center gap-7 px-4 py-20 text-center sm:px-6">
          <h2 className="max-w-3xl font-display text-3xl leading-[1.1] tracking-editorial text-white sm:text-5xl">
            Calm technology for the front lines of care.
          </h2>
          <p className="max-w-xl text-primary-fixed/85">
            Stand up a workspace in minutes, invite your team, and connect the EHR you already run.
          </p>
          <Link to="/get-started">
            <Button
              shape="pill"
              className="h-12 bg-white !bg-none px-7 text-primary shadow-lifted hover:brightness-95"
            >
              Get started <ArrowRight size={16} aria-hidden="true" />
            </Button>
          </Link>
        </Reveal>
      </div>

      {/* Footer */}
      <div className="bg-ink">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <div className="flex items-center gap-2.5">
                <img src="/solace-logo.png" alt="" className="h-8 w-8 rounded-md object-contain" />
                <span className="font-display text-xl tracking-editorial text-white">Solace</span>
              </div>
              <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/55">
                The clinical AI platform for triage, ambient documentation, and a copilot that works
                inside the EHR you already run.
              </p>
            </div>
            {columns.map((col) => (
              <div key={col.title}>
                <p className="font-mono text-[11px] uppercase tracking-[0.12em] text-white/45">{col.title}</p>
                <ul className="mt-4 space-y-2.5">
                  {col.links.map((l) => (
                    <li key={l.to}>
                      <Link to={l.to} className="text-sm text-white/75 hover:text-white">
                        {l.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-12 flex flex-col gap-2 border-t border-white/10 pt-6 text-xs text-white/45 sm:flex-row sm:items-center sm:justify-between">
            <p>© {new Date().getFullYear()} Solace Health, Inc.</p>
            <p>Built for clinicians. Designed for calm.</p>
          </div>
        </div>
      </div>
    </footer>
  );
}
