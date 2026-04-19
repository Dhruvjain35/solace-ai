import { ButtonHTMLAttributes, forwardRef } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "tertiary" | "danger";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  fullWidth?: boolean;
  loading?: boolean;
};

// Rounded md (6px). Tonal layering, no borders on primary. Ghost border on secondary.
const base =
  "inline-flex items-center justify-center gap-2 h-12 px-6 rounded-md font-medium transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98] tracking-[-0.01em] select-none";

const variants: Record<Variant, string> = {
  primary:
    "text-white bg-primary bg-primary-gradient shadow-soft hover:brightness-110 hover:shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
  secondary:
    "bg-transparent text-primary hover:bg-surface-low focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
  tertiary:
    "bg-transparent text-primary hover:text-primary-hover px-2",
  danger:
    "text-white bg-error hover:brightness-110 shadow-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/40",
};

const secondaryRing = "ring-1 ring-line hover:ring-primary/40";

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "primary", fullWidth, loading = false, disabled, className = "", children, ...rest }, ref) => {
    const extra = variant === "secondary" ? secondaryRing : "";
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={`${base} ${variants[variant]} ${extra} ${fullWidth ? "w-full" : ""} ${className}`}
        {...rest}
      >
        {loading && <Loader2 size={16} className="animate-spin" aria-hidden />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";
