import { useEffect, useState } from "react";
import { Check, AlertCircle } from "lucide-react";
import { postPainFlag } from "../../lib/api";

type Props = { hospitalId: string; patientId: string };

export function PainEscalateButton({ hospitalId, patientId }: Props) {
  const [sending, setSending] = useState(false);
  const [sentAt, setSentAt] = useState<number | null>(null);
  const [cooldownLeft, setCooldownLeft] = useState(0);

  useEffect(() => {
    if (!sentAt) return;
    const tick = () => {
      const left = Math.max(0, 30 - Math.floor((Date.now() - sentAt) / 1000));
      setCooldownLeft(left);
      if (left === 0) setSentAt(null);
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [sentAt]);

  const disabled = sending || cooldownLeft > 0;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={async () => {
        setSending(true);
        try {
          await postPainFlag(hospitalId, patientId);
          setSentAt(Date.now());
        } catch (e) {
          console.error("Pain flag failed", e);
        } finally {
          setSending(false);
        }
      }}
      className={`w-full h-14 rounded-md font-semibold text-white text-lg transition-all shadow-soft tracking-editorial ${
        sentAt ? "bg-secondary" : "bg-error hover:brightness-110"
      } disabled:opacity-75`}
    >
      {sentAt ? (
        <span className="inline-flex items-center gap-2">
          <Check size={22} /> Clinician notified — stay seated
        </span>
      ) : (
        <span className="inline-flex items-center gap-2">
          <AlertCircle size={22} /> My pain got worse
        </span>
      )}
    </button>
  );
}
