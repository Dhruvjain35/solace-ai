import type { Config } from "tailwindcss";

// Clinical Sanctuary tokens. The "line" token is the ghost-border only (20% opacity);
// do NOT use it for sectioning — use surface-container tiers for that.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#2A474E",
          container: "#3B5E67",
          hover: "#223B41",
          fixed: "#CBE3E9",
          dim: "#D8ECF0",
        },
        secondary: {
          DEFAULT: "#406372",
          container: "#CADCE7",
        },
        surface: {
          DEFAULT: "#F8F9F9",
          lowest: "#FFFFFF",
          low: "#F3F4F4",
          high: "#E7E8E8",
        },
        ink: "#1A2023",
        "text-muted": "#4A5557",
        // Ghost border (outline-variant @ 20%). Use sparingly; never for sections.
        line: "rgba(74, 85, 87, 0.2)",
        error: {
          DEFAULT: "#BA1A1A",
          container: "#FFDAD6",
        },
        warning: {
          DEFAULT: "#B05436",   // burnt amber — same family as the SHAP positive bar
          container: "#F8E0CF",
        },
        success: {
          DEFAULT: "#557D6E",   // muted clinical green — matches SHAP negative bar
          container: "#D8E7DF",
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        heading: ['"DM Sans"', "system-ui", "sans-serif"],
        body: ['"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      letterSpacing: {
        "editorial": "-0.03em",
        "editorial-tight": "-0.04em",
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "12px",
        xl: "20px",
      },
      boxShadow: {
        soft: "0 4px 16px rgba(42, 71, 78, 0.04)",
        card: "0 8px 24px rgba(42, 71, 78, 0.06)",
        lifted: "0 16px 48px rgba(42, 71, 78, 0.08)",
        glass: "0 1px 0 rgba(255,255,255,0.4) inset, 0 8px 32px rgba(42,71,78,0.06)",
      },
      backgroundImage: {
        "primary-gradient": "linear-gradient(180deg, #3B5E67 0%, #2A474E 100%)",
      },
      keyframes: {
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(42, 71, 78, 0.28)" },
          "70%": { boxShadow: "0 0 0 28px rgba(42, 71, 78, 0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(42, 71, 78, 0)" },
        },
      },
      animation: {
        "pulse-ring": "pulse-ring 1.6s ease-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
