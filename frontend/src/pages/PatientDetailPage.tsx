import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Mic } from "lucide-react";
import { getPatientDetail } from "../lib/api";
import { loadSession, type Session } from "../lib/session";
import type { PatientDetail } from "../types";
import { PatientDetailBody } from "../components/clinician/PatientDetailBody";

export default function PatientDetailPage() {
  const { hospitalId = "demo", patientId = "" } = useParams<{ hospitalId?: string; patientId?: string }>();
  const navigate = useNavigate();
  const [session, setSession] = useState<Session | null>(null);
  const [detail, setDetail] = useState<PatientDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSession(loadSession());
  }, []);

  useEffect(() => {
    if (!session?.token || !patientId) return;
    let cancelled = false;
    getPatientDetail(hospitalId, patientId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.response?.data?.detail || e?.message || "Could not load patient");
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId, patientId, session]);

  const reload = async () => {
    try {
      const d = await getPatientDetail(hospitalId, patientId);
      setDetail(d);
    } catch {
      /* swallow — caller already navigated */
    }
  };

  if (!session?.token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-low">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <h1 className="text-xl font-bold mb-2">Sign in required</h1>
          <p className="text-text-muted text-sm mb-4">Open the clinician dashboard to sign in first.</p>
          <Link
            to={`/${hospitalId}/clinician`}
            className="inline-flex items-center gap-1.5 h-10 px-4 rounded-md bg-primary text-white text-sm font-semibold"
          >
            Go to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-low">
      <header className="border-b border-line bg-surface-lowest sticky top-0 z-30">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-3">
          <Link
            to={`/${hospitalId}/clinician`}
            className="inline-flex items-center gap-1.5 text-text-muted hover:text-ink text-sm font-semibold"
          >
            <ArrowLeft size={16} /> Dashboard
          </Link>
          <div className="flex-1 min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
              Patient detail
            </div>
            <div className="text-lg font-bold tracking-tight truncate">
              {detail?.name || (error ? "Patient" : "Loading…")}
            </div>
          </div>
          {detail && (
            <Link
              to={`/${hospitalId}/clinician/patient/${detail.patient_id}/scribe`}
              className="inline-flex items-center gap-1.5 h-10 px-4 rounded-md bg-primary text-white text-sm font-semibold hover:opacity-90"
            >
              <Mic size={14} /> Open scribe
            </Link>
          )}
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6">
        {error && (
          <div className="mb-4 p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
        )}
        {!detail && !error && (
          <div className="text-text-muted text-sm">Loading patient record…</div>
        )}
        {detail && (
          <PatientDetailBody
            detail={detail}
            hospitalId={hospitalId}
            authenticated={!!session?.token}
            showScribeLink={false}
            onDetailChange={(updater) => setDetail((d) => updater(d))}
            onAfterMarkSeen={async () => {
              await reload();
              navigate(`/${hospitalId}/clinician`);
            }}
          />
        )}
      </main>
    </div>
  );
}
