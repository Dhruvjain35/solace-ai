/**
 * Clinician session management.
 *
 * Token + metadata in localStorage so opening the printable patient note in a
 * new tab can re-use the same session. The 30-min absolute JWT expiry + 15-min
 * idle timeout below still enforce automatic logout — moving from sessionStorage
 * to localStorage trades "browser-close clears" for "multi-tab works", which
 * matches a real clinical workflow (clinician opens a chart in tab A, hits
 * Print, the print preview opens in tab B and just works).
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

// Read from localStorage primarily; fall back to sessionStorage for any clinician
// who's still mid-session under the old storage model. Same-tab logic is unchanged.
function _read(key: string): string | null {
  return localStorage.getItem(key) ?? sessionStorage.getItem(key);
}

export function loadSession(): Session | null {
  try {
    const raw = _read(STORAGE_KEY);
    if (!raw) return null;
    const sess = JSON.parse(raw) as Session;
    if (!sess.token || !sess.expires_at) return null;
    if (sess.expires_at * 1000 < Date.now()) {
      clearSession();
      return null;
    }
    return sess;
  } catch {
    return null;
  }
}

export function saveSession(sess: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sess));
  // Drop any leftover sessionStorage copy from older builds so loadSession is unambiguous.
  sessionStorage.removeItem(STORAGE_KEY);
  bumpActivity();
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(STORAGE_KEY + ".lastActivity");
  sessionStorage.removeItem(STORAGE_KEY);
  sessionStorage.removeItem(STORAGE_KEY + ".lastActivity");
}

export function bumpActivity(): void {
  localStorage.setItem(STORAGE_KEY + ".lastActivity", String(Date.now()));
}

export function isIdleExpired(): boolean {
  const last = Number(_read(STORAGE_KEY + ".lastActivity") || 0);
  if (!last) return false;
  return Date.now() - last > IDLE_TIMEOUT_MS;
}
