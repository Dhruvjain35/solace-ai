import { AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { motion } from "framer-motion";
import type { PatientSummary } from "../../types";
import { ESIBadge } from "../patient/ESIBadge";

type Props = {
  patient: PatientSummary;
  onClick: () => void;
  index?: number;
};

/** Human-readable wait: 100 → "1h 40m", 45 → "45m", 0 → "just now". */
function formatWait(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins <= 0) return "just now";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** Patient queue card. Refined ESI (post-vitals) takes visual priority over provisional. */
export function PatientCard({ patient, onClick, index = 0 }: Props) {
  const flagged = patient.pain_flagged;
  const acked =
    !!patient.pain_flag_acknowledged_at &&
    !!patient.pain_flagged_at &&
    patient.pain_flag_acknowledged_at >= patient.pain_flagged_at;
  const activeFlag = flagged && !acked;
  const refined = patient.refined_esi_level != null;
  const displayEsi = (refined ? patient.refined_esi_level : patient.esi_level) as 1 | 2 | 3 | 4 | 5;
  const displayConf = refined ? patient.refined_confidence ?? null : patient.esi_confidence;

  return (
    <motion.button
      type="button"
      onClick={onClick}
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1], delay: Math.min(index * 0.04, 0.24) }}
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.995 }}
      className={`text-left w-full rounded-2xl p-5 shadow-none hover:shadow-soft transition-shadow ${
        activeFlag
          ? "bg-error/[0.05] ring-2 ring-error/50 animate-pulse"
          : flagged
          ? "bg-error/[0.03] ring-1 ring-error/15"
          : "bg-surface-lowest ring-1 ring-line/45"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-2 min-w-0 flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="font-bold tracking-editorial text-lg truncate">{patient.name}</span>
            {activeFlag ? (
              <span className="inline-flex items-center gap-1 text-[11px] font-bold text-white bg-error uppercase tracking-[0.12em] px-1.5 py-0.5 rounded">
                <AlertCircle size={12} strokeWidth={2.5} />
                pain alarm
              </span>
            ) : flagged ? (
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-text-muted uppercase tracking-[0.12em]">
                <AlertCircle size={12} strokeWidth={2} />
                pain flagged · ack'd
              </span>
            ) : null}
            {refined ? (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-primary uppercase tracking-[0.12em]">
                <CheckCircle2 size={11} strokeWidth={2} />
                refined
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium text-text-muted uppercase tracking-[0.12em]">
                <Clock size={11} strokeWidth={1.5} />
                vitals pending
              </span>
            )}
          </div>
          <div className="text-[14px] text-ink/90 line-clamp-3 leading-relaxed">
            {patient.clinician_prebrief || <span className="text-text-muted">No pre-brief yet</span>}
          </div>
          <div className="text-[12px] text-text-muted flex items-center gap-2.5">
            <span>{formatWait(patient.waited_minutes)} wait</span>
            <span aria-hidden className="text-line">·</span>
            <span>{patient.language.toUpperCase()}</span>
            {displayConf != null && (
              <>
                <span aria-hidden className="text-line">·</span>
                <span title={refined ? "ML-ensemble confidence" : patient.confidence_band || ""}>
                  {Math.round(displayConf * 100)}% conf
                </span>
              </>
            )}
          </div>
        </div>
        <ESIBadge esiLevel={displayEsi} size="sm" showLabel={false} />
      </div>
    </motion.button>
  );
}
