// ESI palette aligned with the Clinical Sanctuary system.
// Avoid high-saturation emergency reds; use the `error` token only for ESI 1.
export const ESI_COLORS: Record<number, { bg: string; label: string; onDark: boolean }> = {
  1: { bg: "#BA1A1A", label: "Critical", onDark: true },
  2: { bg: "#B05436", label: "Emergent", onDark: true },
  3: { bg: "#B8924A", label: "Urgent", onDark: true },
  4: { bg: "#406372", label: "Less Urgent", onDark: true },
  5: { bg: "#557D6E", label: "Non-Urgent", onDark: true },
};

export const POLL_INTERVAL_MS = 10_000;
