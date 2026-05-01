import { AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { motion } from "framer-motion";
import type { PatientSummary } from "../../types";
import { ESIBadge } from "../patient/ESIBadge";

type Props = {
  patient: PatientSummary;
  onClick: () => void;
  index?: number;
};

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
      className={`text-left w-full rounded-lg p-5 shadow-soft hover:shadow-card transition-shadow ${
        activeFlag
          ? "bg-error/[0.06] ring-2 ring-error/60 animate-pulse"
          : flagged
          ? "bg-error/[0.04]"
          : "bg-surface-lowest"
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
          <div className="text-[14px] text-ink line-clamp-3 font-mono leading-relaxed">
            {patient.clinician_prebrief || <span className="text-text-muted">No pre-brief yet</span>}
          </div>
          <div className="text-[11px] text-text-muted font-mono tracking-wide flex items-center gap-3">
            <span>waited {patient.waited_minutes}m</span>
            <span aria-hidden>·</span>
            <span>{patient.language.toUpperCase()}</span>
            {displayConf != null && (
              <>
                <span aria-hidden>·</span>
                <span title={refined ? "ML-ensemble confidence" : patient.confidence_band || ""}>
                  conf {displayConf.toFixed(2)}
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
