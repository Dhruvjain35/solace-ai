import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { AnimatePresence, motion } from "framer-motion";
import { X, ShieldCheck, Activity, Clock3, Bell } from "lucide-react";
import { PatientCard } from "../components/clinician/PatientCard";
import { PrescriptionPanel } from "../components/clinician/PrescriptionPanel";
import { NotesPanel } from "../components/clinician/NotesPanel";
import { VitalsPanel } from "../components/clinician/VitalsPanel";
import { EHRPanel } from "../components/clinician/EHRPanel";
import { DifferentialPanel } from "../components/clinician/DifferentialPanel";
import { WorkupPanel } from "../components/clinician/WorkupPanel";
import { DispositionPanel } from "../components/clinician/DispositionPanel";
import { PainAlarm } from "../components/clinician/PainAlarm";
import { Button } from "../components/ui/Button";
import { usePollingPatients } from "../hooks/usePollingPatients";
import {
  buildEHRLaunchURL,
  getPatientDetail,
  listEHRVendors,
  loginClinician,
  markSeen,
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
import type { PatientDetail } from "../types";

const DEMO_CLINICIANS = ["Dr. Chen", "Dr. Patel", "Dr. Kim"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-2">
        {title}
      </div>
      {children}
    </section>
  );
}

function formatMedicalInfo(info: NonNullable<import("../types").PatientDetail["medical_info"]>): string {
  const parts: string[] = [];
  if (info.age) parts.push(`${info.age}yo`);
  if (info.sex) parts.push(info.sex);
  if (info.pregnant) {
    parts.push(info.gestational_weeks ? `pregnant ${info.gestational_weeks}w` : "pregnant");
  }
  if (info.smoker) parts.push("smoker");

  // Allergies with severity
  const allergies = (info.allergies || []).filter((x) => x.toLowerCase() !== "none");
  if (allergies.length) {
    const labeled = allergies.map((a) => {
      const sev = info.allergy_severity?.[a];
      return sev ? `${a} (${sev})` : a;
    });
    parts.push(`allergies: ${labeled.join(", ")}`);
  }

  // Meds with blood-thinner specifier
  const meds = (info.medications || []).filter((x) => x.toLowerCase() !== "none");
  if (meds.length) {
    const labeled = meds.map((m) =>
      m === "Blood thinners" && info.blood_thinner_name ? `${m} (${info.blood_thinner_name})` : m,
    );
    parts.push(`meds: ${labeled.join(", ")}`);
  }

  // Conditions with type specifier
  const conds = (info.conditions || []).filter((x) => x.toLowerCase() !== "none");
  if (conds.length) {
    const labeled = conds.map((c) => {
      if (c === "Diabetes" && info.diabetes_type) return `${c} (${info.diabetes_type})`;
      if (c === "Heart failure" && info.heart_failure_class) return `${c} (NYHA ${info.heart_failure_class})`;
      return c;
    });
    parts.push(`hx: ${labeled.join(", ")}`);
  }
  return parts.join(" · ") || "none reported";
}

export default function ClinicianDashboard() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const [session, setSession] = useState<Session | null>(null);
  const [loginName, setLoginName] = useState(DEMO_CLINICIANS[0]);
  const [pinInput, setPinInput] = useState("");
  const [pinError, setPinError] = useState<string | null>(null);
  const [pinChecking, setPinChecking] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"waiting" | "all">("waiting");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PatientDetail | null>(null);
  const [ehrVendors, setEhrVendors] = useState<EHRVendorOption[]>([]);

  // Load EHR vendor list for the Sign-in-with buttons. Cheap GET, no auth needed.
  useEffect(() => {
    listEHRVendors().then(setEhrVendors).catch(() => setEhrVendors([]));
  }, []);
  // `pin` remains the dep for polling hook — we pass session.token (string) to re-key polling
  const pin = session?.token ?? null;
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

  const { patients, loading, error, refetch } = usePollingPatients(hospitalId, pin, 10_000, statusFilter);

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

  function signOut() {
    clearSession();
    setSession(null);
  }

  useEffect(() => {
    if (!selectedId || !session) return;
    getPatientDetail(hospitalId, selectedId, session.token)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [selectedId, session, hospitalId]);

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
              Solace · Clinician Terminal
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Sign in</h1>
            <p className="text-[13px] text-text-muted mt-1.5 leading-snug">
              Use your hospital's EHR to sign in. We map your Practitioner record to a Solace
              session and pull the patient list, allergies, meds, and prior encounters from
              your EHR automatically.
            </p>
          </div>

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
          <Button
            variant="primary"
            fullWidth
            disabled={pinInput.length < 4 || pinChecking}
            onClick={submitLogin}
          >
            {pinChecking ? "Signing in…" : "Sign in with PIN"}
          </Button>
          <p className="text-[11px] text-text-muted text-center leading-relaxed">
            Sessions expire after 30 min absolute · 15 min idle.
          </p>
        </motion.div>
      </div>
    );
  }

  // Summary stats for the dashboard header strip — calculated once per poll.
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

  return (
    <div className="min-h-full grid grid-cols-[260px_1fr] gap-0">
      <aside className="bg-surface-low p-5 flex flex-col gap-5 min-h-screen border-r border-line">
        <div>
          <img
            src="/solace-logo.png"
            alt="Solace"
            className="h-16 w-auto max-w-full select-none"
            draggable={false}
          />
          <p className="text-[11px] text-text-muted uppercase tracking-wider font-semibold mt-2">
            Clinician Terminal
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
            className={`text-left px-3 py-2 rounded-md text-sm font-medium transition-colors ${
              statusFilter === "waiting"
                ? "bg-primary-fixed text-primary"
                : "text-text-muted hover:bg-surface-lowest"
            }`}
            onClick={() => setStatusFilter("waiting")}
          >
            <span>Waiting</span>
            <span className="ml-2 text-[11px] font-mono">
              {patients.filter((p) => p.status === "waiting").length}
            </span>
          </button>
          <button
            className={`text-left px-3 py-2 rounded-md text-sm font-medium transition-colors ${
              statusFilter === "all"
                ? "bg-primary-fixed text-primary"
                : "text-text-muted hover:bg-surface-lowest"
            }`}
            onClick={() => setStatusFilter("all")}
          >
            <span>All</span>
            <span className="ml-2 text-[11px] font-mono">{patients.length}</span>
          </button>
        </div>
        <div className="mt-auto flex flex-col items-center gap-2 bg-surface-lowest rounded-lg p-4 shadow-soft">
          <QRCodeSVG
            value={`${getRuntimeConfig().publicUrl || window.location.origin}/${hospitalId}`}
            size={160}
            bgColor="#FFFFFF"
            fgColor="#2A474E"
          />
          <p className="text-xs text-text-muted text-center tracking-wide">Patients scan to check in</p>
        </div>
        <button
          type="button"
          onClick={async () => {
            if (!pin) return;
            if (!window.confirm("Reset demo? This deletes all non-canonical patients and clears refined/notes/prescriptions on the 5 seeded ones.")) return;
            try {
              const { resetDemo } = await import("../lib/api");
              const r = await resetDemo(hospitalId, pin);
              alert(`Reset complete.\nDeleted ${r.deleted_test_patients.length} test patient(s).\nCleared ${r.cleared_canonical_patients.length} canonical patient(s).`);
              window.location.reload();
            } catch (e: any) {
              alert("Reset failed: " + (e?.response?.data?.detail || e.message));
            }
          }}
          className="text-[11px] text-text-muted hover:text-error font-mono tracking-[0.1em] uppercase py-1 transition-colors"
          title="Clears non-canonical patients and resets the 5 seeded ones"
        >
          Reset demo
        </button>
      </aside>

      <main
        className="p-8 relative"
        style={{
          background:
            "radial-gradient(1200px 600px at 20% -10%, rgba(203,227,233,0.25) 0%, transparent 60%), " +
            "radial-gradient(1000px 500px at 100% 100%, rgba(203,227,233,0.18) 0%, transparent 55%), " +
            "#F8F9F9",
        }}
      >
        {/* Summary stat strip — info-dense + scannable. Refresh on every poll. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-6">
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
            label="Avg wait (min)"
            value={statBar.avgWaitMinutes}
            tone="muted"
          />
          <StatTile
            icon={ShieldCheck}
            label="ML-refined"
            value={`${statBar.refinedPct}%`}
            tone="muted"
          />
        </div>

        {pin && (
          <PainAlarm
            hospitalId={hospitalId}
            pin={pin}
            patients={patients}
            onOpenPatient={(id) => setSelectedId(id)}
            onAfterAck={refetch}
          />
        )}
        {newArrivals.length > 0 && (
          <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-lg bg-primary text-white shadow-soft animate-pulse">
            <span className="text-xs uppercase tracking-[0.14em] font-bold">New arrival</span>
            <span className="text-sm font-medium">
              {newArrivals.length === 1
                ? `${newArrivals[0]} just checked in.`
                : `${newArrivals.length} patients just checked in: ${newArrivals.join(", ")}.`}
            </span>
            <button
              type="button"
              onClick={() => setNewArrivals([])}
              className="ml-auto text-[11px] uppercase tracking-wider opacity-70 hover:opacity-100"
            >
              Dismiss
            </button>
          </div>
        )}
        {error && (
          <div className="mb-4 p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
        )}
        {loading && patients.length === 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-[124px] rounded-lg bg-surface-lowest shadow-soft animate-pulse"
              />
            ))}
          </div>
        )}
        {!loading && patients.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-20 text-text-muted">
            <div className="text-lg">No waiting patients.</div>
            <div className="text-sm">Share the QR code in the sidebar for patients to check in.</div>
          </div>
        )}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {patients.map((p, i) => (
            <PatientCard
              key={p.patient_id}
              patient={p}
              index={i}
              onClick={() => setSelectedId(p.patient_id)}
            />
          ))}
        </div>
      </main>

      <AnimatePresence>
        {selectedId && (
          <motion.aside
            key={selectedId}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="fixed top-0 right-0 h-full w-full lg:w-[640px] bg-surface border-l border-line shadow-lifted overflow-y-auto z-50 p-6"
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                  Patient detail
                </div>
                <h2 className="text-2xl font-bold tracking-tight mt-0.5">
                  {detail?.name || "Loading…"}
                </h2>
              </div>
              <button
                onClick={() => {
                  setSelectedId(null);
                  setDetail(null);
                }}
                aria-label="Close"
                className="w-10 h-10 rounded-md hover:bg-surface-alt flex items-center justify-center"
              >
                <X size={22} />
              </button>
            </div>

            {!detail ? (
              <div className="text-text-muted">Loading...</div>
            ) : (
              <div className="flex flex-col gap-6">
                <div className="text-sm text-text-muted font-mono">
                  waited {detail.waited_minutes}m · {detail.language.toUpperCase()}
                </div>

                {/* ESI reconciliation banner — provisional vs refined */}
                <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
                  <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-2">
                    Triage acuity
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex flex-col gap-0.5">
                      <div className="text-[10px] uppercase tracking-wider text-text-muted">Provisional · on intake</div>
                      <div className="flex items-baseline gap-2">
                        <span className="text-2xl font-bold text-primary">ESI {detail.esi_level}</span>
                        {detail.esi_confidence != null && (
                          <span className="text-xs font-mono text-text-muted">
                            {(detail.esi_confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="text-xl text-text-muted mx-1">→</div>
                    <div className="flex flex-col gap-0.5">
                      <div className="text-[10px] uppercase tracking-wider text-text-muted">
                        {detail.refined_esi_level ? "Refined · bedside ML" : "Refined · vitals pending"}
                      </div>
                      <div className="flex items-baseline gap-2">
                        {detail.refined_esi_level ? (
                          <>
                            <span className="text-2xl font-bold text-primary">ESI {detail.refined_esi_level}</span>
                            {detail.refined_confidence != null && (
                              <span className="text-xs font-mono text-text-muted">
                                {(detail.refined_confidence * 100).toFixed(0)}%
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="text-base text-text-muted italic">take vitals to refine</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-primary-fixed/40 rounded-lg p-4">
                  <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-1">
                    Pre-brief
                  </div>
                  <div className="text-[15px] leading-relaxed text-ink">{detail.clinician_prebrief}</div>
                </div>

                {detail.clinical_scribe_note && (
                  <Section title="Scribe note (AI draft)">
                    <pre className="font-mono text-[13px] whitespace-pre-wrap bg-surface-low rounded-lg p-4 leading-relaxed">
                      {detail.clinical_scribe_note}
                    </pre>
                  </Section>
                )}

                {detail.clinical_flags.length > 0 && (
                  <Section title="Clinical flags">
                    <div className="flex flex-wrap gap-2">
                      {detail.clinical_flags.map((f) => (
                        <span
                          key={f}
                          className="px-2.5 py-1 rounded-full text-xs font-medium bg-error/10 text-error"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Composite scores (qSOFA/SIRS/shock_index/cv_risk) are vitals-driven.
                    Self-serve intake doesn't capture vitals, so these would be identical
                    (default normals) for every patient — misleading. Only show them once
                    real bedside vitals are measured via the VitalsPanel. */}
                {detail.refined_esi_level && detail.measured_vitals ? (
                  <Section title="Composite scores · from measured vitals">
                    <div className="grid grid-cols-4 gap-2 font-mono text-sm">
                      {(["qsofa", "sirs", "shock_index", "cv_risk"] as const).map((k) => (
                        <div key={k} className="bg-surface-lowest rounded-lg p-3 shadow-soft">
                          <div className="text-[10px] uppercase tracking-wider text-text-muted">{k}</div>
                          <div className="text-lg font-bold tracking-editorial">
                            {detail.composites[k] ?? "—"}
                          </div>
                        </div>
                      ))}
                    </div>
                  </Section>
                ) : (
                  <Section title="Composite scores">
                    <div className="bg-surface-lowest rounded-lg p-4 text-[13px] text-text-muted shadow-soft italic">
                      Awaiting bedside vitals. qSOFA / SIRS / shock index / CV-risk composites
                      require HR, BP, respiratory rate, and SpO₂ — use the "Bedside vitals" panel
                      below to enter them, and the ML ensemble will refine the ESI.
                    </div>
                  </Section>
                )}

                {detail.triage_recommendation && (
                  <Section title="Recommended next steps">
                    <div className="bg-surface-lowest rounded-lg p-4 text-[14px] leading-relaxed shadow-soft">
                      {detail.triage_recommendation}
                    </div>
                  </Section>
                )}

                {detail.differential && detail.differential.length > 0 && (
                  <DifferentialPanel entries={detail.differential} />
                )}

                {detail.workup_orders && (
                  <WorkupPanel orders={detail.workup_orders} />
                )}

                {detail.disposition && detail.disposition.disposition && (
                  <DispositionPanel disposition={detail.disposition} />
                )}

                <Section title="Raw transcript">
                  <pre className="font-mono text-[13px] whitespace-pre-wrap bg-surface-low rounded-lg p-4 leading-relaxed">
                    {detail.transcript}
                  </pre>
                </Section>

                {detail.followup_qa.length > 0 && (
                  <Section title="Follow-up Q&A">
                    <div className="flex flex-col gap-2">
                      {detail.followup_qa.map((qa, i) => (
                        <div key={i} className="text-sm">
                          <span className="text-text-muted">Q: </span>
                          <span className="font-medium">{qa.question}</span>
                          <br />
                          <span className="text-text-muted">A: </span>
                          <span className="font-mono">{qa.answer}</span>
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {detail.medical_info && (
                  <Section title="Reported history">
                    <div className="text-sm leading-relaxed text-ink">
                      {formatMedicalInfo(detail.medical_info)}
                    </div>
                  </Section>
                )}

                {detail.insurance_info && (
                  <Section title="Insurance">
                    <div className="grid grid-cols-2 gap-2 text-sm font-mono text-ink">
                      {detail.insurance_info.provider && (
                        <div className="col-span-2">
                          <span className="text-text-muted">Provider · </span>
                          {detail.insurance_info.provider}
                        </div>
                      )}
                      {detail.insurance_info.member_id && (
                        <div>
                          <span className="text-text-muted">Member · </span>
                          {detail.insurance_info.member_id}
                        </div>
                      )}
                      {detail.insurance_info.group_number && (
                        <div>
                          <span className="text-text-muted">Group · </span>
                          {detail.insurance_info.group_number}
                        </div>
                      )}
                      {detail.insurance_info.plan_name && (
                        <div className="col-span-2">
                          <span className="text-text-muted">Plan · </span>
                          {detail.insurance_info.plan_name}
                        </div>
                      )}
                    </div>
                  </Section>
                )}

                <EHRPanel hospitalId={hospitalId} patientId={detail.patient_id} />

                <VitalsPanel
                  hospitalId={hospitalId}
                  patientId={detail.patient_id}
                  pin={session!.token}
                  existing={
                    detail.refined_esi_level
                      ? {
                          esi_level: detail.refined_esi_level,
                          confidence: detail.refined_confidence ?? 0,
                          probabilities: detail.refined_probabilities
                            ? JSON.parse(detail.refined_probabilities)
                            : {},
                          conformal_set: detail.refined_conformal_set
                            ? JSON.parse(detail.refined_conformal_set)
                            : [detail.refined_esi_level],
                          conformal_q_hat: 0,
                          top_features: detail.refined_top_features
                            ? JSON.parse(detail.refined_top_features)
                            : [],
                          source: detail.refined_source ?? "lgbm",
                        }
                      : null
                  }
                  onRefined={(r, v) =>
                    setDetail((d) =>
                      d
                        ? {
                            ...d,
                            refined_esi_level: r.esi_level,
                            refined_confidence: r.confidence,
                            refined_probabilities: JSON.stringify(r.probabilities),
                            refined_conformal_set: JSON.stringify(r.conformal_set),
                            refined_top_features: JSON.stringify(r.top_features),
                            refined_source: r.source,
                            measured_vitals: d.measured_vitals ?? JSON.stringify(v),
                          }
                        : d
                    )
                  }
                />

                <NotesPanel
                  hospitalId={hospitalId}
                  patientId={detail.patient_id}
                  pin={session!.token}
                  initialNotes={detail.notes}
                  initialEducation={detail.patient_education}
                  publishedAt={detail.patient_education_published_at}
                />

                <PrescriptionPanel
                  hospitalId={hospitalId}
                  patientId={detail.patient_id}
                  pin={session!.token}
                  medicalInfo={detail.medical_info}
                />


                {detail.photo_url && (
                  <Section title="Photo">
                    <img src={detail.photo_url} alt="Injury" className="max-w-full rounded-lg shadow-soft" />
                    {detail.photo_analysis?.description && (
                      <p className="text-sm text-ink mt-2">{detail.photo_analysis.description}</p>
                    )}
                  </Section>
                )}

                {detail.shap_values && Object.keys(detail.shap_values).length > 0 && (
                  <Section title="What drove this ESI">
                    <div className="flex flex-col gap-1.5 font-mono text-xs">
                      {Object.entries(detail.shap_values)
                        .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
                        .slice(0, 8)
                        .map(([feature, value]) => (
                          <div key={feature} className="flex items-center gap-2">
                            <span className="w-48 truncate text-text-muted">{feature}</span>
                            <div className="flex-1 h-4 bg-surface-low rounded-sm relative">
                              <div
                                className="h-full rounded-sm"
                                style={{
                                  background: value >= 0 ? "#B05436" : "#557D6E",
                                  width: `${Math.min(100, Math.abs(value) * 100)}%`,
                                }}
                              />
                            </div>
                            <span className="w-12 text-right">{value.toFixed(2)}</span>
                          </div>
                        ))}
                    </div>
                    {detail.triage_source === "heuristic_stub" && (
                      <p className="text-xs text-error mt-2">
                        ⚠ Using heuristic stub — Triage.ai model not loaded.
                      </p>
                    )}
                  </Section>
                )}

                <Button
                  variant="primary"
                  fullWidth
                  onClick={async () => {
                    if (!pin || !selectedId) return;
                    await markSeen(hospitalId, selectedId, pin, "Clinician");
                    setSelectedId(null);
                    setDetail(null);
                    await refetch();
                  }}
                >
                  Mark Seen
                </Button>
              </div>
            )}
          </motion.aside>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------------

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
    error: "text-error bg-error/15",
  }[tone];
  return (
    <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex items-center gap-3">
      <div className={`h-9 w-9 rounded-md flex items-center justify-center shrink-0 ${toneClasses}`}>
        <Icon size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold leading-none">
          {label}
        </div>
        <div className="text-xl font-bold tracking-tight text-ink leading-tight mt-1">
          {value}
        </div>
      </div>
    </div>
  );
}
