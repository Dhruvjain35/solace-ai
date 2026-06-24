import { ReactNode } from "react";

/** Small mono badge pill that labels a marketing section (Cruise-style eyebrow). */
export function Eyebrow({ children, tone = "teal" }: { children: ReactNode; tone?: "teal" | "inverse" }) {
  const colors =
    tone === "inverse"
      ? "bg-white/10 text-primary-fixed ring-white/15"
      : "bg-primary-dim/60 text-primary ring-primary/10";
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 font-mono text-[11px] uppercase tracking-[0.12em] ring-1 ${colors}`}
    >
      {children}
    </span>
  );
}
