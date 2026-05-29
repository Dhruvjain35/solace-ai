import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { QRCodeSVG } from "qrcode.react";
import {
  ArrowRight,
  Building2,
  Check,
  Copy,
  Mail,
  QrCode,
  UserPlus,
  Users2,
} from "lucide-react";
import { Button } from "../ui/Button";
import {
  approveAccessRequest,
  completeOnboarding,
  denyAccessRequest,
  getOnboarding,
  inviteTeammate,
  listAccessRequests,
  listCareTeam,
  type AccessRequest,
  type CareTeamMember,
  type OnboardingStatus,
} from "../../lib/api";
import { getRuntimeConfig } from "../../lib/runtime-config";

// First-run admin setup, shown over the dashboard until the workspace is marked
// onboarded. Three steps: confirm workspace, invite the team (and clear any
// pending join requests), share the patient QR. No emojis — clinical product.
type Props = {
  hospitalId: string;
  onDone: () => void;
};

const STEPS = ["Workspace", "Your team", "Patient check-in"] as const;
const ROLES = ["attending", "resident", "nurse", "clinician", "admin"];

export default function OnboardingWizard({ hospitalId, onDone }: Props) {
  const [step, setStep] = useState(0);
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [team, setTeam] = useState<CareTeamMember[]>([]);
  const [requests, setRequests] = useState<AccessRequest[]>([]);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteName, setInviteName] = useState("");
  const [inviteRole, setInviteRole] = useState("clinician");
  const [inviting, setInviting] = useState(false);
  const [inviteMsg, setInviteMsg] = useState<string | null>(null);
  const [inviteErr, setInviteErr] = useState<string | null>(null);

  const [finishing, setFinishing] = useState(false);
  const [copied, setCopied] = useState(false);

  const patientUrl = `${getRuntimeConfig().publicUrl || window.location.origin}/h/${hospitalId}`;

  async function refresh() {
    try {
      const [s, t, r] = await Promise.all([
        getOnboarding(hospitalId),
        listCareTeam(hospitalId),
        listAccessRequests(hospitalId),
      ]);
      setStatus(s);
      setTeam(t.members);
      setRequests(r.requests);
    } catch {
      /* non-fatal — wizard still renders with what it has */
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hospitalId]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (inviting || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(inviteEmail.trim())) {
      setInviteErr("Enter a valid email address.");
      return;
    }
    setInviteErr(null);
    setInviting(true);
    try {
      await inviteTeammate(hospitalId, inviteEmail.trim(), inviteName.trim(), inviteRole);
      setInviteMsg(`Invite sent to ${inviteEmail.trim()}.`);
      setInviteEmail("");
      setInviteName("");
      refresh();
    } catch (err: any) {
      setInviteErr(err?.response?.data?.detail || "Could not send that invite.");
    } finally {
      setInviting(false);
    }
  }

  async function handleApprove(id: string) {
    await approveAccessRequest(hospitalId, id);
    refresh();
  }
  async function handleDeny(id: string) {
    await denyAccessRequest(hospitalId, id);
    refresh();
  }

  async function handleFinish() {
    setFinishing(true);
    try {
      await completeOnboarding(hospitalId);
      onDone();
    } finally {
      setFinishing(false);
    }
  }

  async function copyPatientUrl() {
    try {
      await navigator.clipboard.writeText(patientUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-ink/40 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.2, 0.8, 0.2, 1] }}
        className="w-full max-w-lg bg-surface-lowest rounded-xl shadow-card max-h-[90vh] overflow-y-auto"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        <div className="p-7 flex flex-col gap-6">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold mb-1">
              Welcome to Solace · Set up {status?.name || "your workspace"}
            </div>
            <h1 className="text-2xl font-bold tracking-tight">Let&apos;s get your team live</h1>
          </div>

          {/* Step rail */}
          <div className="flex items-center gap-2">
            {STEPS.map((label, i) => (
              <div key={label} className="flex items-center gap-2 flex-1">
                <div
                  className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0 ${
                    i < step
                      ? "bg-primary text-white"
                      : i === step
                        ? "bg-primary-dim text-primary ring-2 ring-primary"
                        : "bg-surface-low text-text-muted"
                  }`}
                >
                  {i < step ? <Check size={14} /> : i + 1}
                </div>
                <span className={`text-xs font-medium ${i === step ? "text-ink" : "text-text-muted"}`}>
                  {label}
                </span>
              </div>
            ))}
          </div>

          {/* Step 0 — workspace */}
          {step === 0 && (
            <div className="flex flex-col gap-4">
              <div className="flex items-start gap-3 rounded-md bg-surface-low p-4">
                <Building2 size={20} className="text-primary mt-0.5 shrink-0" aria-hidden />
                <div>
                  <div className="text-sm font-semibold text-ink">{status?.name || hospitalId}</div>
                  <div className="text-[12px] text-text-muted mt-0.5">
                    Private workspace at <span className="font-mono">/h/{hospitalId}</span>. Clinician
                    and patient entry points are isolated to your practice.
                  </div>
                </div>
              </div>
              <p className="text-[13px] text-text-muted leading-relaxed">
                You&apos;re signed in as the admin. Next, invite your care team and share the patient
                check-in link. You can always change these later from the dashboard.
              </p>
            </div>
          )}

          {/* Step 1 — team + requests */}
          {step === 1 && (
            <div className="flex flex-col gap-5">
              <form onSubmit={handleInvite} className="flex flex-col gap-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                  <UserPlus size={16} className="text-primary" aria-hidden />
                  Invite a teammate
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => {
                      setInviteEmail(e.target.value);
                      if (inviteErr) setInviteErr(null);
                    }}
                    placeholder="teammate@hospital.org"
                    className="h-11 px-3 rounded-md bg-surface-low text-sm ring-1 ring-line focus:ring-2 focus:ring-primary outline-none"
                  />
                  <input
                    type="text"
                    value={inviteName}
                    onChange={(e) => setInviteName(e.target.value)}
                    placeholder="Name (optional)"
                    className="h-11 px-3 rounded-md bg-surface-low text-sm ring-1 ring-line focus:ring-2 focus:ring-primary outline-none"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value)}
                    className="h-11 px-3 rounded-md bg-surface-low text-sm ring-1 ring-line focus:ring-2 focus:ring-primary outline-none"
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <Button type="submit" loading={inviting} disabled={!inviteEmail.trim()} className="flex-1">
                    <Mail size={15} aria-hidden /> Send invite
                  </Button>
                </div>
                {inviteErr && <div className="text-sm text-error font-medium">{inviteErr}</div>}
                {inviteMsg && <div className="text-sm text-primary font-medium">{inviteMsg}</div>}
              </form>

              {requests.length > 0 && (
                <div className="flex flex-col gap-2">
                  <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                    Requests to join ({requests.length})
                  </div>
                  {requests.map((r) => (
                    <div key={r.request_id} className="flex items-center justify-between gap-2 rounded-md bg-surface-low px-3 py-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-ink truncate">{r.name}</div>
                        <div className="text-[12px] text-text-muted truncate">{r.email}</div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button onClick={() => handleApprove(r.request_id)} className="text-[12px] font-semibold text-primary hover:underline">
                          Approve
                        </button>
                        <span className="text-text-muted">·</span>
                        <button onClick={() => handleDeny(r.request_id)} className="text-[12px] font-semibold text-text-muted hover:text-error">
                          Deny
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-text-muted font-semibold">
                  <Users2 size={13} aria-hidden /> Care team ({team.length})
                </div>
                {team.map((m) => (
                  <div key={m.clinician_id} className="flex items-center justify-between text-sm">
                    <span className="text-ink truncate">{m.name || m.email}</span>
                    <span className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">{m.role}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Step 2 — patient QR */}
          {step === 2 && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink self-start">
                <QrCode size={16} className="text-primary" aria-hidden />
                Patients check in here
              </div>
              <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
                <QRCodeSVG value={patientUrl} size={168} />
              </div>
              <div className="flex items-center gap-2 w-full">
                <code className="flex-1 flex items-center h-11 px-3 truncate rounded-md bg-surface-low font-mono text-xs">
                  {patientUrl}
                </code>
                <Button variant="secondary" onClick={copyPatientUrl} className="px-3 shrink-0">
                  {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
                  {copied ? "Copied" : "Copy"}
                </Button>
              </div>
              <p className="text-[12px] text-text-muted leading-relaxed text-center">
                Print this QR for your waiting room, or share the link. Patients scan it to begin
                voice or text intake — no app download.
              </p>
            </div>
          )}

          {/* Footer nav */}
          <div className="flex items-center justify-between gap-3 pt-1">
            <button
              onClick={() => (step === 0 ? onDone() : setStep((s) => s - 1))}
              className="text-[12px] text-text-muted hover:text-ink font-semibold uppercase tracking-wider"
            >
              {step === 0 ? "Skip for now" : "Back"}
            </button>
            {step < STEPS.length - 1 ? (
              <Button onClick={() => setStep((s) => s + 1)}>
                Continue <ArrowRight size={16} aria-hidden />
              </Button>
            ) : (
              <Button onClick={handleFinish} loading={finishing}>
                Finish setup <Check size={16} aria-hidden />
              </Button>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
