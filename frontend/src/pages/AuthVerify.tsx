import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, useSearchParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Loader2, CircleCheck, CircleAlert } from "lucide-react";
import { verifyMagicLink } from "../lib/api";
import { saveSession } from "../lib/session";

// Landing page for the emailed magic link: /:hospitalId/auth/verify?token=...
// Redeems the single-use token for a session, then drops the clinician into
// their workspace dashboard. No emojis — clinical product.
type Phase = "verifying" | "ok" | "error";

export default function AuthVerify() {
  const { hospitalId = "" } = useParams<{ hospitalId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [phase, setPhase] = useState<Phase>("verifying");
  const [message, setMessage] = useState("Verifying your sign-in link…");
  const ran = useRef(false); // guard React 18 StrictMode double-invoke (token is single-use)

  // Preserve whichever prefix the link used: provisioned `/h/:id` vs legacy `/:id`.
  const prefix = location.pathname.startsWith("/h/") ? "/h" : "";
  const dashboard = `${prefix}/${hospitalId}/clinician`;

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const token = params.get("token");
    if (!token) {
      setPhase("error");
      setMessage("This link is missing its sign-in token. Request a new one.");
      return;
    }

    verifyMagicLink(hospitalId, token)
      .then((resp) => {
        saveSession(resp);
        setPhase("ok");
        setMessage("Signed in. Taking you to your workspace…");
        window.setTimeout(() => navigate(dashboard, { replace: true }), 700);
      })
      .catch((e: any) => {
        setPhase("error");
        setMessage(
          e?.response?.data?.detail ||
            "This link is invalid or has expired. Request a new one.",
        );
      });
  }, [hospitalId, params, navigate, dashboard]);

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{
        background:
          "radial-gradient(800px 500px at 30% -10%, rgba(203,227,233,0.35) 0%, transparent 55%), #F3F4F4",
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
        className="w-full max-w-sm bg-surface-lowest rounded-xl shadow-card p-7 flex flex-col items-center gap-4 text-center"
      >
        {phase === "verifying" && <Loader2 className="h-9 w-9 text-primary animate-spin" strokeWidth={1.5} />}
        {phase === "ok" && <CircleCheck className="h-9 w-9 text-primary" strokeWidth={1.5} />}
        {phase === "error" && <CircleAlert className="h-9 w-9 text-error" strokeWidth={1.5} />}
        <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
          Solace Atlas
        </div>
        <p className="text-sm text-ink leading-snug">{message}</p>
        {phase === "error" && (
          <Link
            to={dashboard}
            className="mt-1 text-sm font-semibold text-primary hover:underline"
          >
            Back to sign in
          </Link>
        )}
      </motion.div>
    </div>
  );
}
