/**
 * Clinician session management.
 *
 * Token + metadata kept in sessionStorage (clears on tab close) — not localStorage.
 * Idle timeout auto-logs-out the clinician after N minutes of inactivity.
 */

const STORAGE_KEY = "solace.session.v1";
const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 min

export type Session = {
  token: string;
  clinician_id: string;
  name: string;
  role: string;
  hospital_id: string;
  expires_at: number; // unix seconds
  // Optional EHR provenance — present when the clinician signed in via SMART-on-FHIR.
  // Tells the dashboard which vendor to badge and where to issue live FHIR queries.
  ehr_vendor?: string;        // "epic" | "cerner" | "athena"
  ehr_label?: string;         // "Epic" | "Oracle Cerner" | "Athenahealth"
  ehr_color?: string;         // brand accent hex
  ehr_sandbox?: boolean;      // true = non-PHI demo / sandbox
  fhir_base_url?: string;
};

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const sess = JSON.parse(raw) as Session;
    if (!sess.token || !sess.expires_at) return null;
    if (sess.expires_at * 1000 < Date.now()) {
      sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return sess;
  } catch {
    return null;
  }
}

export function saveSession(sess: Session): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(sess));
  bumpActivity();
}

export function clearSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
  sessionStorage.removeItem(STORAGE_KEY + ".lastActivity");
}

export function bumpActivity(): void {
  sessionStorage.setItem(STORAGE_KEY + ".lastActivity", String(Date.now()));
}

export function isIdleExpired(): boolean {
  const last = Number(sessionStorage.getItem(STORAGE_KEY + ".lastActivity") || 0);
  if (!last) return false;
  return Date.now() - last > IDLE_TIMEOUT_MS;
}
