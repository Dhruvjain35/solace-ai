import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { motion } from "framer-motion";
import { X, ShieldCheck, Activity, Clock3, Bell, Workflow as WorkflowIcon, Mic, FileText, Inbox, BookOpen, Network, AlertCircle, Mail } from "lucide-react";
import { PainAlarm } from "../components/clinician/PainAlarm";
import { StudioBoard } from "../components/clinician/StudioBoard";
import { Button } from "../components/ui/Button";
import { TourLauncher } from "../components/tour/TourLauncher";
import OnboardingWizard from "../components/clinician/OnboardingWizard";
import { usePollingPatients } from "../hooks/usePollingPatients";
import {
  buildEHRLaunchURL,
  getOnboarding,
  listEHRVendors,
  loginClinician,
  requestMagicLink,
  resetDemo,
  type EHRVendorOption,
} from "../lib/api";
import { getRuntimeConfig } from "../lib/runtime-config";
import {
  bumpActivity,
  clearSession,
  isIdleExpired,
  loadSession,
  saveSession,
  type Session,
} from "../lib/session";

const DEMO_CLINICIANS = ["Dr. Chen", "Dr. Patel", "Dr. Kim"];

export default function ClinicianDashboard() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();
  // Clicking a patient opens the full Patient Workspace (tabbed tool suite).
  const openWorkspace = (id: string) =>
    navigate(`/${hospitalId}/clinician/patient/${id}`);
  const [session, setSession] = useState<Session | null>(null);
  const [loginName, setLoginName] = useState(DEMO_CLINICIANS[0]);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [pinChecking, setPinChecking] = useState(false);
  // Magic-link sign-in (primary auth for real workspaces).
  const [email, setEmail] = useState("");
  const [magicSending, setMagicSending] = useState(false);
  const [magicSent, setMagicSent] = useState(false);
  const [magicError, setMagicError] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  // PIN sign-in is a demo-only convenience; real tenants use email links.
  const isDemo = hospitalId === "demo";
  // First-run admin setup wizard, gated by the workspace's onboarded flag.
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"waiting" | "all">("waiting");
  const [ehrVendors, setEhrVendors] = useState<EHRVendorOption[]>([]);

  // Load EHR vendor list for the Sign-in-with buttons. Cheap GET, no auth needed.
  useEffect(() => {
    listEHRVendors().then(setEhrVendors).catch(() => setEhrVendors([]));
  }, []);
  const authenticated = !!session?.token;
  // Track arrivals — whenever the set of patient_ids grows, briefly flash a banner
  const [newArrivals, setNewArrivals] = useState<string[]>([]);
  const seenIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    setSession(loadSession());
  }, []);

  // Idle timeout + activity listener. Checks every 60s.
  useEffect(() => {
    if (!session) return;
    const onActivity = () => bumpActivity();
    ["mousemove", "keydown", "click", "touchstart"].forEach((evt) =>
      window.addEventListener(evt, onActivity, { passive: true })
    );
    bumpActivity();
    const timer = window.setInterval(() => {
      if (isIdleExpired()) {
        clearSession();
        setSession(null);
        setPinError("Signed out due to inactivity.");
      }
    }, 60_000);
    return () => {
      clearInterval(timer);
      ["mousemove", "keydown", "click", "touchstart"].forEach((evt) =>
        window.removeEventListener(evt, onActivity)
      );
    };
  }, [session]);

  // 4s polling so new patients show up "live-ish" without manual refresh.
  // The endpoint is throttled at 200 rps and DDB queries are sub-50ms, so this is
  // negligible cost even with 50 concurrent patients in the queue.
  const { patients, loading, error, refetch } = usePollingPatients(hospitalId, authenticated, 4_000, statusFilter);

  // Detect brand-new patient arrivals between polls → pulse a banner
  useEffect(() => {
    if (!patients.length) return;
    const seen = seenIdsRef.current;
    // First render — seed without firing any arrivals
    if (seen.size === 0) {
      patients.forEach((p) => seen.add(p.patient_id));
      return;
    }
    const fresh = patients.filter((p) => !seen.has(p.patient_id));
    if (fresh.length) {
      fresh.forEach((p) => seen.add(p.patient_id));
      setNewArrivals(fresh.map((p) => p.name || p.patient_id.slice(0, 8)));
      // Auto-dismiss after 8 seconds
      const t = window.setTimeout(() => setNewArrivals([]), 8000);
      return () => window.clearTimeout(t);
    }
  }, [patients]);

  // Any 401 in polling = token expired or revoked → kick to login
  useEffect(() => {
    if (error && /401|unauthorized|expired|incorrect/i.test(error)) {
      clearSession();
      setSession(null);
      setPinError("Session expired — please sign in again.");
    }
  }, [error]);

  async function submitLogin() {
    if (pinChecking || pinInput.length < 4) return;
    setPinError(null);
    setPinChecking(true);
    try {
      const resp = await loginClinician(hospitalId, loginName, pinInput);
      saveSession(resp);
      setSession(resp);
      setPinInput("");
    } catch (e: any) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail || "";
      if (status === 401 || /incorrect/i.test(detail)) {
        setPinError("Incorrect name or PIN");
      } else {
        setPinError(detail || e?.message || "Could not sign in");
      }
      setPinInput("");
    } finally {
      setPinChecking(false);
    }
  }

  async function submitMagicLink() {
    const addr = email.trim();
    if (magicSending || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(addr)) {
      setMagicError("Enter a valid email address.");
      return;
    }
    setMagicError(null);
    setMagicSending(true);
    try {
      const resp = await requestMagicLink(hospitalId, addr);
      setMagicSent(true);
      // dev_link only present in local/sandbox — lets us follow the link without email.
      if (resp.dev_link) setDevLink(resp.dev_link);
    } catch (e: any) {
      setMagicError(e?.response?.data?.detail || e?.message || "Could not send your link.");
    } finally {
      setMagicSending(false);
    }
  }

  function signOut() {
    clearSession();
    setSession(null);
  }

  // Admins of a real (non-demo) workspace see the setup wizard until they
  // complete it. Non-admins and the demo workspace never see it.
  useEffect(() => {
    if (!session || isDemo || session.role !== "admin") return;
    getOnboarding(hospitalId)
      .then((s) => setShowOnboarding(!s.onboarded))
      .catch(() => setShowOnboarding(false));
  }, [session, hospitalId, isDemo]);

  // Summary stats for the dashboard header strip — calculated once per poll.
  // MUST live above the `if (!session)` early return so hook order stays constant
  // across renders. Calling useMemo after a conditional return crashes the dashboard
  // ("Rendered more hooks than during the previous render"); white-screening.
  const statBar = useMemo(() => {
    const waiting = patients.filter((p) => p.status === "waiting");
    const activeAlarms = patients.filter(
      (p) =>
        p.pain_flagged &&
        p.pain_flagged_at &&
        (!p.pain_flag_acknowledged_at ||
          (p.pain_flag_acknowledged_at as string) < (p.pain_flagged_at as string))
    );
    const refined = patients.filter((p) => p.refined_esi_level != null);
    const avgWaitMinutes =
      waiting.length === 0
        ? 0
        : Math.round(
            waiting.reduce((s, p) => s + (p.waited_minutes || 0), 0) / waiting.length
          );
    return {
      waiting: waiting.length,
      alarms: activeAlarms.length,
      refinedPct: patients.length === 0 ? 0 : Math.round((refined.length / patients.length) * 100),
      avgWaitMinutes,
    };
  }, [patients]);

  if (!session) {
    return (
      <div
        className="min-h-screen flex items-center justify-center p-4"
        style={{
          background:
            "radial-gradient(800px 500px at 30% -10%, rgba(203,227,233,0.35) 0%, transparent 55%), " +
            "radial-gradient(600px 400px at 100% 110%, rgba(64,99,114,0.15) 0%, transparent 55%), " +
            "#F3F4F4",
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
          className="w-full max-w-sm bg-surface-lowest rounded-xl shadow-card p-7 flex flex-col gap-5"
        >
          <div>
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-1">
              Solace Atlas
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
            <p className="text-[13px] text-text-muted mt-1.5 leading-snug">
              Enter your work email and we'll send a single-use sign-in link. No password to
              remember. You can also sign in through your hospital's EHR.
            </p>
          </div>

          {magicSent ? (
            <div className="rounded-md bg-surface-low ring-1 ring-line px-4 py-3.5 flex flex-col gap-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Mail className="h-4 w-4 text-primary" strokeWidth={1.75} />
                Check your inbox
              </div>
              <p className="text-[12px] text-text-muted leading-relaxed">
                If <span className="font-medium text-ink">{email.trim()}</span> is registered at
                this workspace, a secure sign-in link is on its way. It expires shortly and can
                be used once.
              </p>
              {devLink && (
                <a
                  href={devLink}
                  className="text-[12px] font-semibold text-primary hover:underline break-all"
                >
                  Dev mode: follow your sign-in link
                </a>
              )}
              <button
                type="button"
                onClick={() => {
                  setMagicSent(false);
                  setDevLink(null);
                }}
                className="self-start text-[11px] text-text-muted hover:text-ink font-semibold uppercase tracking-wider"
              >
                Use a different email
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <label className="flex flex-col gap-1.5 text-[11px] text-text-muted font-semibold uppercase tracking-wider">
                Work email
                <input
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (magicError) setMagicError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitMagicLink();
                  }}
                  placeholder="you@hospital.org"
                  className={`h-11 px-3 rounded-md bg-surface-low ring-1 focus:ring-2 text-sm outline-none transition-all ${
                    magicError ? "ring-error focus:ring-error" : "ring-line focus:ring-primary"
                  }`}
                />
              </label>
              {magicError && <div className="text-sm text-error font-medium">{magicError}</div>}
              <Button
                variant="primary"
                fullWidth
                disabled={magicSending}
                onClick={submitMagicLink}
              >
                {magicSending ? "Sending link…" : "Email me a sign-in link"}
              </Button>
            </div>
          )}

          {ehrVendors.length > 0 && (
            <div className="relative flex items-center gap-3 my-1">
              <div className="flex-1 h-px bg-line" />
              <span className="text-[10px] uppercase tracking-wider text-text-muted">or</span>
              <div className="flex-1 h-px bg-line" />
            </div>
          )}

          {ehrVendors.length > 0 && (
            <div className="flex flex-col gap-2">
              {ehrVendors.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => {
                    const redirectUri = `${window.location.origin}/ehr/callback`;
                    window.location.href = buildEHRLaunchURL(v.id, hospitalId, redirectUri);
                  }}
                  className="group h-11 px-4 rounded-md flex items-center justify-between gap-3 text-left transition-all hover:shadow-soft border-2 border-line hover:border-primary/60"
                  style={{ background: "white" }}
                >
                  <span className="flex items-center gap-3 min-w-0">
                    <span
                      className="h-7 w-7 rounded shrink-0 flex items-center justify-center text-white text-[12px] font-bold"
                      style={{ background: v.color }}
                    >
                      {v.label.slice(0, 1)}
                    </span>
                    <span className="text-sm font-semibold truncate">Sign in with {v.label}</span>
                  </span>
                  {v.sandbox && (
                    <span className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                      sandbox
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          {isDemo && (
            <>
              <div className="relative flex items-center gap-3 my-1">
                <div className="flex-1 h-px bg-line" />
                <span className="text-[10px] uppercase tracking-wider text-text-muted">
                  or PIN sign-in
                </span>
                <div className="flex-1 h-px bg-line" />
              </div>

              <label className="flex flex-col gap-1.5 text-[11px] text-text-muted font-semibold uppercase tracking-wider">
                Name
                <select
                  value={loginName}
                  onChange={(e) => setLoginName(e.target.value)}
                  className="h-11 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm font-medium text-ink outline-none transition-all"
                >
                  {DEMO_CLINICIANS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5 text-[11px] text-text-muted font-semibold uppercase tracking-wider">
                PIN
                <input
                  type="password"
                  value={pinInput}
                  onChange={(e) => {
                    setPinInput(e.target.value);
                    if (pinError) setPinError(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitLogin();
                  }}
                  placeholder="••••••"
                  className={`h-11 px-4 rounded-md bg-surface-low ring-1 focus:ring-2 text-base font-mono tracking-[0.2em] outline-none transition-all ${
                    pinError ? "ring-error focus:ring-error" : "ring-line focus:ring-primary"
                  }`}
                />
              </label>
              {pinError && (
                <div className="-mt-2 text-sm text-error font-medium">{pinError}</div>
              )}
              <div className="-mt-1 rounded-md bg-surface-low ring-1 ring-line px-3 py-2 text-[11px] text-text-muted leading-relaxed">
                <span className="font-semibold text-ink">Demo access</span> — Dr. Chen 224466 ·
                Dr. Patel 113355 · Dr. Kim 667788
              </div>
              <Button
                variant="primary"
                fullWidth
                disabled={pinInput.length < 4 || pinChecking}
                onClick={submitLogin}
              >
                {pinChecking ? "Signing in…" : "Sign in with PIN"}
              </Button>
            </>
          )}
          <p className="text-[11px] text-text-muted text-center leading-relaxed">
            Sessions expire after 30 min absolute · 15 min idle.
          </p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-full grid grid-cols-[268px_1fr] gap-0">
      {/* Self-contained product tour. Auto-runs once per clinician, replayable
          from the help button. Anchors are the data-tour attributes below. */}
      <TourLauncher tourId="clinician-dashboard-v1" subjectId={session.clinician_id} />
      {showOnboarding && (
        <OnboardingWizard hospitalId={hospitalId} onDone={() => setShowOnboarding(false)} />
      )}
      <aside className="bg-surface-low p-6 flex flex-col gap-6 min-h-screen border-r border-line/70">
        <div>
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-16 w-auto max-w-full select-none"
            draggable={false}
          />
          <p className="text-[11px] text-text-muted uppercase tracking-wider font-semibold mt-2">
            Atlas
          </p>
        </div>

        {session && (
          <div className="flex flex-col gap-2.5 bg-surface-lowest rounded-lg p-3 shadow-soft">
            <div className="flex items-center gap-2.5">
              <div
                className="w-9 h-9 rounded-full bg-primary text-white flex items-center justify-center font-semibold text-sm shrink-0"
                aria-hidden
              >
                {session.name
                  .replace(/^Dr\.\s*/i, "")
                  .split(" ")
                  .map((s) => s[0])
                  .join("")
                  .slice(0, 2)
                  .toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold truncate">{session.name}</div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">
                  {session.role}
                </div>
              </div>
              <button
                onClick={signOut}
                className="text-[10px] text-text-muted hover:text-error font-semibold uppercase tracking-wider transition-colors"
                title="Sign out"
              >
                Sign out
              </button>
            </div>

            {session.ehr_vendor && (
              <div
                className="flex items-center gap-2 text-[11px] -mx-1 -mb-1 px-2 py-1.5 rounded-md"
                style={{
                  background: `${session.ehr_color || "#2A474E"}10`,
                  color: session.ehr_color || "#2A474E",
                }}
                title="Connected via SMART-on-FHIR"
              >
                <ShieldCheck size={12} />
                <span className="font-semibold">Connected to {session.ehr_label}</span>
                {session.ehr_sandbox && (
                  <span className="ml-auto text-[9px] uppercase tracking-wider opacity-70 font-bold">
                    sandbox
                  </span>
                )}
              </div>
            )}
          </div>
        )}

        <div className="flex flex-col gap-1">
          <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1 px-1">
            Queue
          </div>
          <button
            className={`text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === "waiting"
                ? "bg-primary-fixed text-primary"
                : "text-text-muted hover:bg-surface-lowest"
            }`}
            onClick={() => setStatusFilter("waiting")}
          >
            <span>Waiting</span>
            <span className="ml-2 text-[12px] text-text-muted font-semibold">
              {patients.filter((p) => p.status === "waiting").length}
            </span>
          </button>
          <button
            className={`text-left px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === "all"
                ? "bg-primary-fixed text-primary"
                : "text-text-muted hover:bg-surface-lowest"
            }`}
            onClick={() => setStatusFilter("all")}
          >
            <span>All</span>
            <span className="ml-2 text-[12px] text-text-muted font-semibold">{patients.length}</span>
          </button>
        </div>

        <div className="flex flex-col gap-1 mt-2" data-tour="admin-nav">
          <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1 px-1">
            Admin
          </div>
          <Link
            to={`/${hospitalId}/clinician/scribe`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <Mic size={14} /> Ambient scribe
          </Link>
          <Link
            to={`/${hospitalId}/clinician/inbox`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <Inbox size={14} /> Inbox + admin
          </Link>
          <Link
            to={`/${hospitalId}/clinician/letters`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <FileText size={14} /> Letters & forms
          </Link>
          <Link
            to={`/${hospitalId}/clinician/tools`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <BookOpen size={14} /> Evidence + EWS + HCC + Handoff
          </Link>
          <Link
            to={`/${hospitalId}/clinician/ops`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <Network size={14} /> Portal + Cohort + Sepsis + Telehealth + HL7
          </Link>
          <Link
            to={`/${hospitalId}/clinician/workflows`}
            className="text-left px-3 py-2.5 rounded-lg text-sm font-medium text-text-muted hover:bg-surface-lowest inline-flex items-center gap-2"
          >
            <WorkflowIcon size={14} /> Workflows
          </Link>
        </div>
        <div className="mt-auto flex flex-col items-center gap-2 bg-surface-lowest rounded-lg p-4 shadow-soft" data-tour="checkin-qr">
          <QRCodeSVG
            value={`${getRuntimeConfig().publicUrl || window.location.origin}/${hospitalId}`}
            size={160}
            bgColor="#FFFFFF"
            fgColor="#2A474E"
          />
          <p className="text-xs text-text-muted text-center tracking-wide">Patients scan to check in</p>
        </div>
        {isDemo && (
          <button
            type="button"
            onClick={async () => {
              if (!authenticated) return;
              if (!window.confirm("Reset demo? This deletes all non-canonical patients and clears refined/notes/prescriptions on the 5 seeded ones.")) return;
              try {
                const r = await resetDemo(hospitalId);
                alert(`Reset complete.\nDeleted ${r.deleted_test_patients.length} test patient(s).\nCleared ${r.cleared_canonical_patients.length} canonical patient(s).`);
                window.location.reload();
              } catch (e: any) {
                alert("Reset failed: " + (e?.response?.data?.detail || e.message));
              }
            }}
            className="text-[11px] text-text-muted hover:text-error font-semibold py-1 transition-colors"
            title="Clears non-canonical patients and resets the 5 seeded ones"
          >
            Reset demo
          </button>
        )}
      </aside>

      <main className="p-8 lg:p-10 relative bg-surface-lowest">
        {/* Summary stat strip — info-dense + scannable. Refresh on every poll. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8" data-tour="stat-strip">
          <StatTile
            icon={Activity}
            label="Patients waiting"
            value={statBar.waiting}
            tone="primary"
          />
          <StatTile
            icon={Bell}
            label="Active pain alarms"
            value={statBar.alarms}
            tone={statBar.alarms > 0 ? "error" : "muted"}
          />
          <StatTile
            icon={Clock3}
            label="Avg wait"
            value={formatWaitShort(statBar.avgWaitMinutes)}
            tone="muted"
          />
          <StatTile
            icon={ShieldCheck}
            label="ML-refined"
            value={`${statBar.refinedPct}%`}
            tone="muted"
          />
        </div>

        {authenticated && (
          <PainAlarm
            hospitalId={hospitalId}
            patients={patients}
            onOpenPatient={(id) => openWorkspace(id)}
            onAfterAck={refetch}
          />
        )}
        {newArrivals.length > 0 && (
          <div
            role="status"
            className="mb-4 flex items-center gap-3 px-4 py-3 rounded-lg bg-primary text-white shadow-card"
          >
            <span className="h-6 w-6 rounded-full bg-white/15 flex items-center justify-center shrink-0">
              <Bell size={13} aria-hidden />
            </span>
            <span className="text-[10px] uppercase tracking-[0.14em] font-bold shrink-0">
              New arrival
            </span>
            <span className="text-sm font-medium truncate">
              {newArrivals.length === 1
                ? `${newArrivals[0]} just checked in.`
                : `${newArrivals.length} patients just checked in: ${newArrivals.join(", ")}.`}
            </span>
            <button
              type="button"
              onClick={() => setNewArrivals([])}
              aria-label="Dismiss new arrival notice"
              className="ml-auto h-7 w-7 rounded-md flex items-center justify-center text-white/70 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            >
              <X size={15} aria-hidden />
            </button>
          </div>
        )}
        {error && (
          <div className="mb-4 flex items-start gap-2.5 p-3 rounded-md bg-error-container text-error text-sm">
            <AlertCircle size={16} className="shrink-0 mt-0.5" aria-hidden />
            <span className="font-medium">{error}</span>
          </div>
        )}
        <StudioBoard
          hospitalId={hospitalId}
          patients={patients}
          loading={loading}
          authenticated={authenticated}
          clinicianId={session.clinician_id}
        />
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------------

/** Compact human-readable wait for the stat strip: 100 → "1h 40m", 45 → "45m". */
function formatWaitShort(mins: number): string {
  if (!mins || mins <= 0) return "—";
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function StatTile({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Activity;
  label: string;
  value: string | number;
  tone: "primary" | "muted" | "error";
}) {
  const toneClasses = {
    primary: "text-primary bg-primary-fixed",
    muted: "text-text-muted bg-surface-low",
    error: "text-error bg-error-container",
  }[tone];
  return (
    <div className="bg-surface-lowest rounded-xl p-4 ring-1 ring-line/45 flex items-center gap-3">
      <div className={`h-10 w-10 rounded-xl flex items-center justify-center shrink-0 ${toneClasses}`}>
        <Icon size={18} aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold leading-none">
          {label}
        </div>
        <div className="text-2xl font-bold tracking-tight text-ink leading-none mt-1.5">
          {value}
        </div>
      </div>
    </div>
  );
}
