import { FormEvent, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CheckCircle2,
  LogIn,
  Mail,
  ShieldCheck,
  Users,
} from "lucide-react";
import { MarketingLayout } from "../components/marketing/MarketingLayout";
import { Eyebrow } from "../components/marketing/Eyebrow";
import { Button } from "../components/ui/Button";
import { provisionHospital, requestAccess, type ProvisionedHospital } from "../lib/api";

type Path = "start" | "join";

const practiceTypes = ["Hospital / ER", "Urgent care", "Primary care", "Specialty clinic"];
const roles = ["Physician", "Nurse / NP / PA", "Practice administrator", "Other"];

// Step ids per path; "choose" is shared.
const startSteps = ["choose", "practice", "admin", "review", "done"] as const;
const joinSteps = ["choose", "join", "done"] as const;

function Field({
  id,
  label,
  optional,
  children,
}: {
  id: string;
  label: string;
  optional?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-text-muted">
        {label}
        {optional && <span className="ml-1 text-xs text-text-muted/70">(optional)</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls =
  "w-full rounded-md bg-surface-lowest px-3.5 py-2.5 text-sm text-ink ring-1 ring-line placeholder:text-text-muted/60 focus:outline-none focus:ring-2 focus:ring-primary/40";

export default function GetStarted() {
  const reduced = useReducedMotion();
  const [path, setPath] = useState<Path>("start");
  const [stepIdx, setStepIdx] = useState(0);
  const prevIdxRef = useRef(0);

  // Path A — practice + admin details. Extra fields (type, role, NPI) stay
  // client-side for the review summary; the provision API takes name/slug/admin.
  const [practiceName, setPracticeName] = useState("");
  const [slug, setSlug] = useState("");
  const [practiceType, setPracticeType] = useState(practiceTypes[0]);
  const [adminName, setAdminName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [role, setRole] = useState(roles[0]);
  const [npi, setNpi] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ProvisionedHospital | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Path B — join existing.
  const [joinSlug, setJoinSlug] = useState("");
  const [joinName, setJoinName] = useState("");
  const [joinEmail, setJoinEmail] = useState("");

  const steps = path === "start" ? startSteps : joinSteps;
  const step = steps[stepIdx];
  const dir = stepIdx >= prevIdxRef.current ? 1 : -1;

  const go = (next: number) => {
    prevIdxRef.current = stepIdx;
    setError(null);
    setStepIdx(Math.max(0, Math.min(steps.length - 1, next)));
  };

  const emailOk = (v: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim());
  const cleanSlug = (v: string) =>
    v.trim().toLowerCase().replace(/^.*\/h\//, "").replace(/\/.*$/, "");

  async function submitApplication() {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const r = await provisionHospital(practiceName.trim(), slug.trim() || undefined, adminEmail.trim(), adminName.trim());
      setResult(r);
      go(stepIdx + 1);
    } catch (e: unknown) {
      const resp = (e as { response?: { status?: number } })?.response;
      setError(
        resp?.status === 409
          ? "That workspace URL is taken — try a different short name."
          : resp?.status === 429
            ? "Too many requests right now. Please wait a minute and try again."
            : !resp
              ? "We couldn't reach Solace — check your connection and try again."
              : "Something went wrong creating your workspace. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function submitJoin(e: FormEvent) {
    e.preventDefault();
    const s = cleanSlug(joinSlug);
    if (submitting || !s || !emailOk(joinEmail) || !joinName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await requestAccess(s, joinEmail.trim(), joinName.trim());
      go(stepIdx + 1);
    } catch (err: unknown) {
      const resp = (err as { response?: { status?: number } })?.response;
      setError(
        resp?.status === 404
          ? "We couldn't find that workspace. Double-check the workspace name with your admin."
          : resp?.status === 429
            ? "Too many requests right now. Please wait a minute and try again."
            : !resp
              ? "We couldn't reach Solace — check your connection and try again."
              : "Something went wrong sending your request. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const progress = useMemo(() => {
    const total = steps.length - 1; // exclude done
    return Math.min(stepIdx / total, 1);
  }, [stepIdx, steps.length]);

  // Directional variants driven by `custom` (the PatientIntake pattern): the
  // exiting card reads the CURRENT direction from AnimatePresence's custom
  // prop instead of the stale value captured at its last render, so Back
  // slides everything the opposite way of Next.
  const stepVariants = {
    enter: (d: number) => ({ opacity: 0, x: 36 * d }),
    center: { opacity: 1, x: 0 },
    exit: (d: number) => ({ opacity: 0, x: -36 * d }),
  };

  return (
    <MarketingLayout>
      <div className="hero-surface relative">
        <div className="mx-auto max-w-2xl px-4 pb-24 pt-14 sm:px-6">
          <div className="mb-8 flex flex-col items-center gap-4 text-center">
            <Eyebrow>Get started</Eyebrow>
            <h1 className="font-display text-4xl tracking-editorial text-ink sm:text-5xl">
              {step === "done" ? "Welcome to Solace." : "Bring Solace to your team."}
            </h1>
            {/* Progress bar */}
            {step !== "done" && (
              <div className="mt-1 h-1 w-48 overflow-hidden rounded-full bg-surface-high">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-300"
                  style={{ width: `${Math.max(progress * 100, 8)}%` }}
                />
              </div>
            )}
          </div>

          <AnimatePresence mode="wait" custom={dir}>
            <motion.div
              key={`${path}-${step}`}
              custom={dir}
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: reduced ? 0 : 0.28, ease: [0.4, 0, 0.2, 1] }}
            >
              {step === "choose" && (
                <div className="space-y-4">
                  {(
                    [
                      {
                        p: "start" as Path,
                        Icon: Building2,
                        title: "Start a new practice or hospital",
                        desc: "Create a workspace, become its admin, and invite your care team.",
                      },
                      {
                        p: "join" as Path,
                        Icon: Users,
                        title: "Join your team on Solace",
                        desc: "Your organization already uses Solace — request access from your admin.",
                      },
                    ] as const
                  ).map(({ p, Icon, title, desc }) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => {
                        setPath(p);
                        prevIdxRef.current = 0;
                        setStepIdx(1);
                      }}
                      className="card-clean group flex w-full items-start gap-4 rounded-xl p-6 text-left transition-shadow hover:shadow-lifted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    >
                      <span className="rounded-lg bg-primary-dim/60 p-2.5 text-primary">
                        <Icon size={20} aria-hidden="true" />
                      </span>
                      <span className="flex-1">
                        <span className="block font-medium text-ink">{title}</span>
                        <span className="mt-1 block text-sm text-text-muted">{desc}</span>
                      </span>
                      <ArrowRight
                        size={18}
                        className="mt-1 text-text-muted transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </button>
                  ))}
                  <p className="pt-2 text-center text-sm text-text-muted">
                    Just exploring?{" "}
                    <Link to="/contact" className="font-medium text-primary hover:underline">
                      Book a demo
                    </Link>
                  </p>
                </div>
              )}

              {step === "practice" && (
                <form
                  className="card-clean space-y-5 rounded-xl p-7"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (practiceName.trim()) go(2);
                  }}
                >
                  <h2 className="font-medium text-ink">About your practice</h2>
                  <Field id="gs-name" label="Practice or hospital name">
                    <input
                      id="gs-name"
                      className={inputCls}
                      value={practiceName}
                      onChange={(e) => setPracticeName(e.target.value)}
                      placeholder="St. David's Medical Center"
                      required
                    />
                  </Field>
                  <Field id="gs-type" label="Practice type">
                    <select id="gs-type" className={inputCls} value={practiceType} onChange={(e) => setPracticeType(e.target.value)}>
                      {practiceTypes.map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  </Field>
                  <Field id="gs-slug" label="Workspace URL" optional>
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-text-muted">solace.health/h/</span>
                      <input
                        id="gs-slug"
                        className={inputCls}
                        value={slug}
                        onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
                        placeholder="st-davids"
                      />
                    </div>
                  </Field>
                  <div className="flex justify-between pt-2">
                    <Button type="button" variant="secondary" shape="pill" onClick={() => go(0)} className="h-11 px-5 text-sm">
                      <ArrowLeft size={15} aria-hidden="true" /> Back
                    </Button>
                    <Button type="submit" shape="pill" disabled={!practiceName.trim()} className="h-11 px-6 text-sm">
                      Continue <ArrowRight size={15} aria-hidden="true" />
                    </Button>
                  </div>
                </form>
              )}

              {step === "admin" && (
                <form
                  className="card-clean space-y-5 rounded-xl p-7"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (adminName.trim() && emailOk(adminEmail)) go(3);
                  }}
                >
                  <h2 className="font-medium text-ink">Your details</h2>
                  <p className="-mt-3 text-sm text-text-muted">You'll be the workspace admin.</p>
                  <Field id="gs-admin-name" label="Full name">
                    <input id="gs-admin-name" className={inputCls} value={adminName} onChange={(e) => setAdminName(e.target.value)} placeholder="Dr. Asha Patel" required />
                  </Field>
                  <Field id="gs-admin-email" label="Work email">
                    <input id="gs-admin-email" type="email" className={inputCls} value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} placeholder="a.patel@stdavids.org" required />
                  </Field>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <Field id="gs-role" label="Role">
                      <select id="gs-role" className={inputCls} value={role} onChange={(e) => setRole(e.target.value)}>
                        {roles.map((r) => (
                          <option key={r}>{r}</option>
                        ))}
                      </select>
                    </Field>
                    <Field id="gs-npi" label="NPI number" optional>
                      <input id="gs-npi" inputMode="numeric" className={inputCls} value={npi} onChange={(e) => setNpi(e.target.value.replace(/\D/g, "").slice(0, 10))} placeholder="1234567890" />
                    </Field>
                  </div>
                  <div className="flex justify-between pt-2">
                    <Button type="button" variant="secondary" shape="pill" onClick={() => go(1)} className="h-11 px-5 text-sm">
                      <ArrowLeft size={15} aria-hidden="true" /> Back
                    </Button>
                    <Button type="submit" shape="pill" disabled={!adminName.trim() || !emailOk(adminEmail)} className="h-11 px-6 text-sm">
                      Review application <ArrowRight size={15} aria-hidden="true" />
                    </Button>
                  </div>
                </form>
              )}

              {step === "review" && (
                <div className="card-clean space-y-5 rounded-xl p-7">
                  <h2 className="font-medium text-ink">Review your application</h2>
                  <dl className="divide-y divide-line text-sm">
                    {[
                      ["Practice", practiceName],
                      ["Type", practiceType],
                      ["Workspace URL", slug ? `/h/${slug}` : "Auto-generated"],
                      ["Admin", adminName],
                      ["Email", adminEmail],
                      ["Role", role],
                      ["NPI", npi || "Not provided"],
                    ].map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-4 py-2.5">
                        <dt className="text-text-muted">{k}</dt>
                        <dd className="text-right font-medium text-ink">{v}</dd>
                      </div>
                    ))}
                  </dl>
                  {error && <p className="rounded-md bg-error-container px-3 py-2 text-sm text-error">{error}</p>}
                  <div className="flex justify-between pt-1">
                    <Button type="button" variant="secondary" shape="pill" onClick={() => go(2)} className="h-11 px-5 text-sm" disabled={submitting}>
                      <ArrowLeft size={15} aria-hidden="true" /> Back
                    </Button>
                    <Button type="button" shape="pill" loading={submitting} onClick={submitApplication} className="h-11 px-6 text-sm">
                      Submit application
                    </Button>
                  </div>
                </div>
              )}

              {step === "join" && path === "join" && (
                <form className="card-clean space-y-5 rounded-xl p-7" onSubmit={submitJoin}>
                  <h2 className="font-medium text-ink">Request access</h2>
                  <p className="-mt-3 text-sm text-text-muted">
                    Your workspace admin approves requests — you'll get a sign-in link by email.
                  </p>
                  <Field id="gs-join-slug" label="Workspace name or URL">
                    <input id="gs-join-slug" className={inputCls} value={joinSlug} onChange={(e) => setJoinSlug(e.target.value)} placeholder="st-davids or solace.health/h/st-davids" required />
                  </Field>
                  <Field id="gs-join-name" label="Full name">
                    <input id="gs-join-name" className={inputCls} value={joinName} onChange={(e) => setJoinName(e.target.value)} placeholder="Dr. Lee Kim" required />
                  </Field>
                  <Field id="gs-join-email" label="Work email">
                    <input id="gs-join-email" type="email" className={inputCls} value={joinEmail} onChange={(e) => setJoinEmail(e.target.value)} placeholder="l.kim@stdavids.org" required />
                  </Field>
                  {error && <p className="rounded-md bg-error-container px-3 py-2 text-sm text-error">{error}</p>}
                  <div className="flex justify-between pt-1">
                    <Button type="button" variant="secondary" shape="pill" onClick={() => go(0)} className="h-11 px-5 text-sm" disabled={submitting}>
                      <ArrowLeft size={15} aria-hidden="true" /> Back
                    </Button>
                    <Button type="submit" shape="pill" loading={submitting} disabled={!cleanSlug(joinSlug) || !joinName.trim() || !emailOk(joinEmail)} className="h-11 px-6 text-sm">
                      Send request <ArrowRight size={15} aria-hidden="true" />
                    </Button>
                  </div>
                </form>
              )}

              {step === "done" && (
                <div className="card-clean rounded-xl p-8 text-center">
                  <CheckCircle2 size={36} className="mx-auto text-success" aria-hidden="true" />
                  {path === "start" && result ? (
                    <>
                      <h2 className="mt-4 font-display text-2xl tracking-editorial text-ink">
                        Application approved — workspace created.
                      </h2>
                      <p className="mx-auto mt-2 max-w-md text-sm text-text-muted">
                        We sent a secure sign-in link to <span className="font-medium text-ink">{adminEmail}</span>.
                        It signs you in as the admin of{" "}
                        <span className="font-medium text-ink">{result.name}</span>.
                      </p>
                      <div className="mx-auto mt-6 max-w-md space-y-2.5 text-left">
                        {[
                          { Icon: Mail, text: "Check your email and open the sign-in link" },
                          { Icon: LogIn, text: "Sign in — you land in the setup wizard" },
                          { Icon: Users, text: "Invite your care team from the wizard" },
                          { Icon: ShieldCheck, text: "Connect your EHR under Tools, then EHR connections" },
                        ].map(({ Icon, text }) => (
                          <div key={text} className="flex items-center gap-3 rounded-lg bg-surface-low px-4 py-3 text-sm text-ink">
                            <Icon size={16} className="shrink-0 text-primary" aria-hidden="true" />
                            {text}
                          </div>
                        ))}
                      </div>
                      <div className="mt-6 space-y-1 font-mono text-xs text-text-muted">
                        <p>Clinician workspace: {result.clinician_url}</p>
                        <p>Patient intake: {result.patient_url}</p>
                      </div>
                      {result.admin_dev_link && (
                        <a href={result.admin_dev_link} className="mt-2 inline-block text-sm font-medium text-primary hover:underline">
                          Open sign-in link (sandbox)
                        </a>
                      )}
                    </>
                  ) : (
                    <>
                      <h2 className="mt-4 font-display text-2xl tracking-editorial text-ink">Request sent.</h2>
                      <p className="mx-auto mt-2 max-w-md text-sm text-text-muted">
                        Your workspace admin has been notified. Once they approve, a secure sign-in
                        link arrives at <span className="font-medium text-ink">{joinEmail}</span>.
                      </p>
                    </>
                  )}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </MarketingLayout>
  );
}
