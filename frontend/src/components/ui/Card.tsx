import { HTMLAttributes } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  tone?: "lowest" | "low" | "high";
  dense?: boolean;
  // "xl" → softer 20px corners for the cleaner marketing treatment. Defaults to
  // "lg" so existing in-app cards are unchanged.
  radius?: "lg" | "xl";
};

/** No borders — depth via surface tier + ambient shadow. */
export function Card({ tone = "lowest", dense, radius = "lg", className = "", ...rest }: Props) {
  const bg =
    tone === "lowest" ? "bg-surface-lowest" : tone === "low" ? "bg-surface-low" : "bg-surface-high";
  const corner = radius === "xl" ? "rounded-xl" : "rounded-lg";
  return (
    <div
      className={`${bg} ${corner} shadow-card ${dense ? "p-4" : "p-6"} ${className}`}
      {...rest}
    />
  );
}
