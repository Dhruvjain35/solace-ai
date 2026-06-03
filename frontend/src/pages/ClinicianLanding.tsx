import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Building2,
  Check,
  ClipboardList,
  Copy,
  LogIn,
  Mail,
  Mic,
  ShieldCheck,
  Stethoscope,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { provisionHospital, requestMagicLink, type ProvisionedHospital } from "../lib/api";

// Marketing / entry landing page for the clinician side of Solace.
// Hero -> value props -> "for hospitals" workspace provisioning -> sign-in CTA.
// Not a patient screen — but Solace is a clinical product, so no emoji here either.

type ValueProp = {
  icon: typeof Mic;
  title: string;
  body: string;
};

const VALUE_PROPS: ValueProp[] = [
  {
    icon: Mic,
    title: "Ambient scribe",
    body: "Visit audio becomes a structured note while you stay with the patient. Review, edit, sign — no after-hours charting.",
  },
  {
    icon: Activity,
    title: "Calibrated triage",
    body: "A 5-fold gradient-boosted ensemble assigns ESI levels with SHAP explanations, so every acuity call is auditable.",
  },
  {
    icon: ClipboardList,
    title: "EHR write-back",
    body: "Notes, orders, and dispositions flow back through SMART-on-FHIR. Solace works inside your chart, not beside it.",
  },
  {
    icon: ShieldCheck,
    title: "Admin automation",
    body: "Eligibility checks, prior-auth packets, coding suggestions, and inbox drafts handled — clinicians stay clinical.",
  },
];

export default function ClinicianLanding() {
  const navigate = useNavigate();
  const [hospitalName, setHospitalName] = useState("");
  const [requestedSlug, setRequestedSlug] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [provisioning, setProvisioning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ProvisionedHospital | null>(null);
  const [copied, setCopied] = useState(false);

  // Two onboarding paths: start a new practice (provision) vs join an existing one.
  const [path, setPath] = useState<"start" | "join">("start");
  const [joinSlug, setJoinSlug] = useState("");
  const [joinEmail, setJoinEmail] = useState("");
  const [joinSending, setJoinSending] = useState(false);
  const [joinSent, setJoinSent] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  async function handleJoin(e: React.FormEvent) {
    e.preventDefault();
    const slug = joinSlug.trim().toLowerCase().replace(/^.*\/h\//, "").replace(/\/.*$/, "");
    const addr = joinEmail.trim();
    if (joinSending || !slug || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(addr)) {
      setJoinError("Enter your workspace and a valid work email.");
      return;
    }
    setJoinError(null);
    setJoinSending(true);
    try {
      // If this email is already a clinician at that workspace (e.g. invited by
      // an admin), a sign-in link is emailed. Otherwise nothing is sent — the
      // response is generic, so this never reveals who belongs where.
      await requestMagicLink(slug, addr);
      setJoinSent(true);
    } catch (err: any) {
      setJoinError(err?.response?.data?.detail || "We could not reach that workspace. Check the name.");
    } finally {
      setJoinSending(false);
    }
  }

  async function handleProvision(e: React.FormEvent) {
    e.preventDefault();
    if (!hospitalName.trim() || provisioning) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(adminEmail.trim())) {
      setError("Enter a valid admin email — that's the account you'll sign in with.");
      return;
    }
    setProvisioning(true);
    setError(null);
    try {
      const result = await provisionHospital(
        hospitalName.trim(),
        requestedSlug.trim(),
        adminEmail.trim(),
      );
      setCreated(result);
    } catch {
      setError("We could not create that workspace. Try a different name.");
    } finally {
      setProvisioning(false);
    }
  }

  async function handleCopy() {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.clinician_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copy failed — select the URL manually.");
    }
  }

  return (
    <div className="min-h-screen bg-surface text-ink font-sans">
      {/* Top bar */}
      <header className="sticky top-0 z-40 backdrop-blur-md bg-surface/70 border-b border-line/60">
        <div className="flex items-center justify-between w-full max-w-6xl mx-auto px-6 py-4">
          <div className="flex items-center gap-2">
            <Stethoscope size={22} className="text-primary" aria-hidden />
            <span className="text-lg font-semibold tracking-editorial">Solace</span>
          </div>
          <Button variant="secondary" shape="pill" onClick={() => navigate("/demo/clinician")}>
            Clinician sign-in
          </Button>
        </div>
      </header>

      {/* Hero — clean teal-tinted band with a decorative brand orb */}
      <section className="relative overflow-hidden hero-surface">
        {/* decorative orb (purely ornamental) */}
        <div
          aria-hidden
          className="hero-blob pointer-events-none absolute -top-40 -right-32 w-[640px] h-[640px]"
        />
        <div className="relative w-full max-w-6xl mx-auto px-6 pt-20 pb-24 md:pt-28 md:pb-32">
          <div className="max-w-3xl">
            <span className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-surface-lowest/80 ring-1 ring-line text-primary text-sm font-semibold">
              <ShieldCheck size={14} aria-hidden />
              HIPAA-aligned clinical AI
            </span>
            <h1 className="mt-7 font-display font-semibold text-5xl md:text-7xl leading-[1.02] tracking-[-0.025em]">
              The doctor&apos;s pal for the whole encounter.
            </h1>
            <p className="mt-7 text-lg md:text-2xl text-text-muted leading-relaxed max-w-2xl">
              Solace listens, triages, charts, and clears the administrative
              backlog — so your clinicians spend their attention on patients,
              not paperwork.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 mt-10">
              <Button shape="pill" onClick={() => navigate("/demo/clinician")}>
                Open the clinician dashboard
                <ArrowRight size={16} aria-hidden />
              </Button>
              <Button variant="secondary" shape="pill" onClick={() => navigate("/demo")}>
                See the patient experience
              </Button>
            </div>
            <p className="mt-5 text-sm text-text-muted">No install — patients scan and go.</p>
          </div>
        </div>
      </section>

      {/* Value props */}
      <section className="w-full bg-surface">
        <div className="w-full max-w-6xl mx-auto px-6 py-24">
          <h2 className="font-display font-semibold text-3xl md:text-5xl tracking-[-0.02em] leading-tight">
            One platform across the visit
          </h2>
          <p className="mt-4 text-lg text-text-muted max-w-2xl leading-relaxed">
            Every Solace surface writes back to the chart and leaves an
            immutable audit trail.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-14">
            {VALUE_PROPS.map(({ icon: Icon, title, body }) => (
              <div
                key={title}
                className="card-clean rounded-2xl p-7 flex flex-col gap-4 transition-all duration-200 hover:shadow-card hover:-translate-y-0.5"
              >
                <span className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-primary-dim text-primary">
                  <Icon size={22} aria-hidden />
                </span>
                <h3 className="text-xl font-semibold tracking-editorial">{title}</h3>
                <p className="text-text-muted leading-relaxed">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Get started — two paths: start a new practice, or join an existing one */}
      <section id="get-started" className="w-full bg-surface-low">
       <div className="w-full max-w-6xl mx-auto px-6 py-24">
        {/* Path toggle */}
        <div className="inline-flex p-1 rounded-full bg-surface-lowest ring-1 ring-line mb-12">
          <button
            type="button"
            onClick={() => setPath("start")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold transition-all ${
              path === "start" ? "bg-primary text-white shadow-soft" : "text-text-muted hover:text-ink"
            }`}
          >
            <Building2 size={15} aria-hidden />
            Start your own practice
          </button>
          <button
            type="button"
            onClick={() => setPath("join")}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-semibold transition-all ${
              path === "join" ? "bg-primary text-white shadow-soft" : "text-text-muted hover:text-ink"
            }`}
          >
            <LogIn size={15} aria-hidden />
            Join an existing hospital
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
          <div>
            {path === "start" ? (
              <>
                <span className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-secondary-container text-secondary text-sm font-semibold">
                  <Building2 size={14} aria-hidden />
                  For hospitals &amp; solo practices
                </span>
                <h2 className="mt-5 font-display text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
                  Spin up your own workspace
                </h2>
                <p className="mt-3 text-text-muted leading-relaxed">
                  Create a private Solace workspace at a unique URL and become its
                  first admin. Invite your care team by email, share the patient
                  intake link, and you are live — everything isolated to your
                  practice.
                </p>
                <ul className="mt-6 space-y-3">
                  {[
                    "Dedicated, URL-safe workspace slug",
                    "You become the admin and invite teammates by email",
                    "Cross-hospital data access blocked at the auth layer",
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2 text-text-muted">
                      <Check size={18} className="text-success mt-0.5 shrink-0" aria-hidden />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <>
                <span className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-secondary-container text-secondary text-sm font-semibold">
                  <LogIn size={14} aria-hidden />
                  For clinicians
                </span>
                <h2 className="mt-5 font-display text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
                  Join your hospital&apos;s workspace
                </h2>
                <p className="mt-3 text-text-muted leading-relaxed">
                  Already on a care team using Solace? Enter your workspace and work
                  email and we will send a single-use sign-in link. No password
                  needed.
                </p>
                <ul className="mt-6 space-y-3">
                  {[
                    "Passwordless, single-use email sign-in",
                    "Your admin invites you — links never expose who belongs where",
                    "Not invited yet? Ask your workspace admin to add your email",
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2 text-text-muted">
                      <Check size={18} className="text-success mt-0.5 shrink-0" aria-hidden />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          {path === "join" ? (
            <Card tone="lowest" radius="xl" className="flex flex-col gap-5">
              {joinSent ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2 text-ink">
                    <Mail size={20} className="text-primary" aria-hidden />
                    <h3 className="text-lg font-semibold tracking-editorial">Check your inbox</h3>
                  </div>
                  <p className="text-text-muted leading-relaxed">
                    If <span className="font-medium text-ink">{joinEmail.trim()}</span> is on the
                    care team at that workspace, a single-use sign-in link is on its way. It
                    expires shortly.
                  </p>
                  <p className="text-sm text-text-muted">
                    Not invited yet? Ask your workspace admin to add your email — they can do it
                    from the workspace settings.
                  </p>
                  <Button variant="tertiary" onClick={() => setJoinSent(false)} className="self-start">
                    Use a different email
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleJoin} className="flex flex-col gap-5">
                  <h3 className="text-lg font-semibold tracking-editorial">Sign in to your workspace</h3>
                  <div>
                    <label htmlFor="join-slug" className="block text-sm font-medium text-text-muted mb-1">
                      Workspace name or URL
                    </label>
                    <input
                      id="join-slug"
                      type="text"
                      value={joinSlug}
                      onChange={(e) => setJoinSlug(e.target.value)}
                      placeholder="riverside-general"
                      required
                      className="w-full h-11 px-3.5 rounded-lg bg-surface-low font-mono text-sm text-ink ring-1 ring-line placeholder:text-text-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    />
                    <p className="mt-1 text-xs text-text-muted">
                      The slug from your workspace link, e.g. /h/&lt;slug&gt;.
                    </p>
                  </div>
                  <div>
                    <label htmlFor="join-email" className="block text-sm font-medium text-text-muted mb-1">
                      Work email
                    </label>
                    <input
                      id="join-email"
                      type="email"
                      inputMode="email"
                      autoComplete="email"
                      value={joinEmail}
                      onChange={(e) => setJoinEmail(e.target.value)}
                      placeholder="you@hospital.org"
                      required
                      className="w-full h-11 px-3.5 rounded-lg bg-surface-low text-sm text-ink ring-1 ring-line placeholder:text-text-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    />
                  </div>
                  {joinError && (
                    <p className="text-sm text-error" role="alert">
                      {joinError}
                    </p>
                  )}
                  <Button type="submit" shape="pill" loading={joinSending} disabled={!joinSlug.trim() || !joinEmail.trim()}>
                    {joinSending ? "Sending link" : "Email me a sign-in link"}
                    {!joinSending && <ArrowRight size={16} aria-hidden />}
                  </Button>
                </form>
              )}
            </Card>
          ) : (
          <Card tone="lowest" radius="xl" className="flex flex-col gap-5">
            {created ? (
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-2 text-success">
                  <Check size={20} aria-hidden />
                  <h3 className="text-lg font-semibold tracking-editorial">
                    Workspace created
                  </h3>
                </div>
                <p className="text-text-muted">
                  {created.name} is live at the workspace slug{" "}
                  <span className="font-mono text-ink">{created.slug}</span>.
                </p>

                <div>
                  <span className="block text-sm font-medium text-text-muted mb-1">
                    Clinician URL
                  </span>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 flex items-center h-11 px-3 truncate rounded-md bg-surface-low font-mono text-sm">
                      {created.clinician_url}
                    </code>
                    <Button
                      variant="secondary"
                      onClick={handleCopy}
                      aria-label="Copy clinician URL"
                      className="px-3 shrink-0"
                    >
                      {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
                      {copied ? "Copied" : "Copy"}
                    </Button>
                  </div>
                </div>

                <div>
                  <span className="block text-sm font-medium text-text-muted mb-1">
                    Patient intake URL
                  </span>
                  <code className="flex items-center h-11 px-3 truncate rounded-md bg-surface-low font-mono text-sm">
                    {created.patient_url}
                  </code>
                </div>

                {created.admin_invited && (
                  <div className="rounded-md bg-surface-low ring-1 ring-line px-4 py-3 flex flex-col gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                      <Mail size={16} className="text-primary" aria-hidden />
                      Finish setup from your inbox
                    </div>
                    <p className="text-[13px] text-text-muted leading-relaxed">
                      We emailed a single-use sign-in link to{" "}
                      <span className="font-medium text-ink">{adminEmail.trim()}</span>. Open it to
                      land in your onboarding wizard and invite your team.
                    </p>
                    {created.admin_dev_link && (
                      <a
                        href={created.admin_dev_link}
                        className="text-[13px] font-semibold text-primary hover:underline break-all"
                      >
                        Dev mode: follow your admin sign-in link
                      </a>
                    )}
                  </div>
                )}

                <div className="flex flex-col sm:flex-row gap-3 pt-1">
                  {!created.admin_invited && (
                    <Button shape="pill" onClick={() => navigate(created.clinician_path)}>
                      Open clinician workspace
                      <ArrowRight size={16} aria-hidden />
                    </Button>
                  )}
                  <Button
                    variant="tertiary"
                    onClick={() => {
                      setCreated(null);
                      setHospitalName("");
                      setRequestedSlug("");
                      setAdminEmail("");
                    }}
                  >
                    Create another
                  </Button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleProvision} className="flex flex-col gap-5">
                <h3 className="text-lg font-semibold tracking-editorial">
                  Create your workspace
                </h3>

                <div>
                  <label
                    htmlFor="hospital-name"
                    className="block text-sm font-medium text-text-muted mb-1"
                  >
                    Hospital name
                  </label>
                  <input
                    id="hospital-name"
                    type="text"
                    value={hospitalName}
                    onChange={(e) => setHospitalName(e.target.value)}
                    placeholder="Riverside General Hospital"
                    required
                    className="w-full h-11 px-3.5 rounded-lg bg-surface-low text-ink ring-1 ring-line placeholder:text-text-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  />
                </div>

                <div>
                  <label
                    htmlFor="admin-email"
                    className="block text-sm font-medium text-text-muted mb-1"
                  >
                    Your work email <span className="text-text-muted/70">(admin)</span>
                  </label>
                  <input
                    id="admin-email"
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    placeholder="you@hospital.org"
                    required
                    className="w-full h-11 px-3.5 rounded-lg bg-surface-low text-ink ring-1 ring-line placeholder:text-text-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  />
                  <p className="mt-1 text-xs text-text-muted">
                    You become the workspace admin. We email you a single-use sign-in link to
                    finish setup — no password.
                  </p>
                </div>

                <div>
                  <label
                    htmlFor="hospital-slug"
                    className="block text-sm font-medium text-text-muted mb-1"
                  >
                    Preferred URL slug{" "}
                    <span className="text-text-muted/70">(optional)</span>
                  </label>
                  <input
                    id="hospital-slug"
                    type="text"
                    value={requestedSlug}
                    onChange={(e) => setRequestedSlug(e.target.value)}
                    placeholder="riverside-general"
                    className="w-full h-11 px-3.5 rounded-lg bg-surface-low font-mono text-sm text-ink ring-1 ring-line placeholder:text-text-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  />
                  <p className="mt-1 text-xs text-text-muted">
                    Becomes /h/&lt;slug&gt;/clinician. We make it unique
                    automatically if it is taken.
                  </p>
                </div>

                {error && (
                  <p className="text-sm text-error" role="alert">
                    {error}
                  </p>
                )}

                <Button type="submit" shape="pill" loading={provisioning} disabled={!hospitalName.trim()}>
                  {provisioning ? "Creating workspace" : "Create workspace"}
                  {!provisioning && <ArrowRight size={16} aria-hidden />}
                </Button>
              </form>
            )}
          </Card>
          )}
        </div>
       </div>
      </section>

      {/* Sign-in CTA — inset rounded gradient panel */}
      <section className="w-full bg-surface">
        <div className="w-full max-w-6xl mx-auto px-6 py-20">
          <div className="relative overflow-hidden rounded-3xl bg-primary bg-primary-gradient text-white px-8 py-14 md:px-14 md:py-16 shadow-card">
            <div
              aria-hidden
              className="hero-blob pointer-events-none absolute -bottom-40 -right-24 w-[460px] h-[460px] opacity-30"
            />
            <div className="relative flex flex-col md:flex-row md:items-center md:justify-between gap-8">
              <div className="max-w-xl">
                <h2 className="font-display text-3xl md:text-5xl font-semibold tracking-[-0.02em] leading-tight">
                  Ready when your shift is
                </h2>
                <p className="mt-4 text-lg text-white/75 leading-relaxed">
                  Sign in to the clinician dashboard and pick up the waiting room.
                </p>
              </div>
              <Button
                variant="secondary"
                shape="pill"
                onClick={() => navigate("/demo/clinician")}
                className="bg-white text-primary hover:bg-white/90 shrink-0"
              >
                Clinician sign-in
                <ArrowRight size={16} aria-hidden />
              </Button>
            </div>
          </div>
        </div>
      </section>

      <footer className="w-full max-w-6xl mx-auto px-6 py-10 text-sm text-text-muted">
        Solace is a clinical decision-support tool. It does not replace
        clinician judgment.
      </footer>
    </div>
  );
}

ClinicianLanding.displayName = "ClinicianLanding";
