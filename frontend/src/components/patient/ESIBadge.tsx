import { motion } from "framer-motion";
import { ESI_COLORS } from "../../lib/constants";

type Props = {
  esiLevel: number;
  size?: "sm" | "lg";
  showLabel?: boolean;
};

export function ESIBadge({ esiLevel, size = "sm", showLabel = true }: Props) {
  const cfg = ESI_COLORS[esiLevel] || { bg: "#4A5557", label: "Unknown", onDark: true };
  const dim = size === "lg" ? "w-24 h-24 text-4xl" : "w-10 h-10 text-base";
  return (
    <div className="flex items-center gap-4">
      <motion.div
        key={esiLevel}
        initial={{ scale: 0.7, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 320, damping: 22 }}
        className={`${dim} rounded-full font-bold tracking-editorial-tight flex items-center justify-center shadow-card ${
          cfg.onDark ? "text-white" : "text-ink"
        }`}
        style={{ background: cfg.bg }}
        aria-label={`Priority ${esiLevel}, ${cfg.label}`}
      >
        {esiLevel}
      </motion.div>
      {showLabel && (
        <div className="flex flex-col leading-tight">
          <span className="text-[11px] uppercase tracking-[0.14em] text-text-muted">Priority</span>
          <span className={`font-bold tracking-editorial ${size === "lg" ? "text-2xl" : "text-sm"}`}>
            {cfg.label}
          </span>
        </div>
      )}
    </div>
  );
}
