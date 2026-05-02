import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, ShieldCheck, AlertOctagon } from "lucide-react";
import { saveSession, type Session } from "../lib/session";

/**
 * SMART-on-FHIR redirect target.
 *
 * The backend exchanges the OAuth code for a FHIR access token + Practitioner
 * identity, then sends us back here with a `handoff` query param that already
 * contains everything we need to construct a Solace clinician session. We just
 * persist + bounce to the dashboard.
 *
 * Errors come back as `?error=...` from the backend redirect helper.
 */
export default function EHRCallback() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const err = params.get("error");
    if (err) {
      setError(prettyError(err));
      return;
    }
    const raw = params.get("handoff");
    if (!raw) {
      setError("EHR sign-in returned without a session payload.");
      return;
    }
    try {
      const data = JSON.parse(raw);
      const sess: Session = {
        token: data.token,
        clinician_id: data.clinician_id,
        name: data.name,
        role: data.role,
        hospital_id: data.hospital_id,
        expires_at: data.expires_at,
        ehr_vendor: data.ehr_vendor,
        ehr_label: data.ehr_label,
        ehr_color: data.ehr_color,
        ehr_sandbox: data.ehr_sandbox,
        fhir_base_url: data.fhir_base_url,
      };
      if (!sess.token || !sess.hospital_id) throw new Error("incomplete session payload");
      saveSession(sess);
      navigate(`/${sess.hospital_id}/clinician`, { replace: true });
    } catch (e: any) {
      setError(`Could not parse EHR session: ${e?.message || "malformed payload"}`);
    }
  }, [params, navigate]);

  return (
    <div
      className="min-h-screen flex items-center justify-center p-6"
      style={{
        background:
          "radial-gradient(800px 500px at 30% -10%, rgba(203,227,233,0.35) 0%, transparent 55%), " +
          "radial-gradient(600px 400px at 100% 110%, rgba(64,99,114,0.15) 0%, transparent 55%), " +
          "#F3F4F4",
      }}
    >
      <div className="w-full max-w-sm bg-surface-lowest rounded-xl shadow-card p-8 flex flex-col gap-4 text-center">
        {!error ? (
          <>
            <ShieldCheck className="mx-auto text-primary" size={32} />
            <div className="text-sm font-semibold tracking-tight">Finishing EHR sign-in…</div>
            <div className="text-xs text-text-muted">
              Verifying your Practitioner record and issuing a Solace session.
            </div>
            <Loader2 className="mx-auto animate-spin text-primary mt-2" size={20} />
          </>
        ) : (
          <>
            <AlertOctagon className="mx-auto text-error" size={32} />
            <div className="text-sm font-semibold tracking-tight">EHR sign-in failed</div>
            <div className="text-xs text-text-muted">{error}</div>
            <button
              onClick={() => navigate("/demo/clinician", { replace: true })}
              className="mt-2 h-10 rounded-md bg-primary text-white text-sm font-semibold"
            >
              Back to sign-in
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function prettyError(code: string): string {
  switch (code) {
    case "token_exchange_failed":
      return "We couldn't exchange the EHR auth code for a session. Try signing in again.";
    case "session_issue_failed":
      return "Your EHR identity verified, but Solace couldn't issue a session. Contact admin.";
    case "invalid_state":
      return "Sign-in link expired. Please start again.";
    default:
      return code;
  }
}
