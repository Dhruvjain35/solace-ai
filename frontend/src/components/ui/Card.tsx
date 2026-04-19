import { HTMLAttributes } from "react";

type Props = HTMLAttributes<HTMLDivElement> & {
  tone?: "lowest" | "low" | "high";
  dense?: boolean;
};

/** No borders — depth via surface tier + ambient shadow. */
export function Card({ tone = "lowest", dense, className = "", ...rest }: Props) {
  const bg =
    tone === "lowest" ? "bg-surface-lowest" : tone === "low" ? "bg-surface-low" : "bg-surface-high";
  return (
    <div
      className={`${bg} rounded-lg shadow-card ${dense ? "p-4" : "p-6"} ${className}`}
      {...rest}
    />
  );
}
