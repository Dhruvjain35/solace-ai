import { useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";

/**
 * Standalone QR-code page for the demo. Shows a large, high-contrast code
 * pointing at the patient-intake URL for the given hospital. Intended to be
 * displayed on a laptop / kiosk so judges can scan from their phones.
 *
 * Always targets the Vercel production URL, regardless of which host is
 * serving this page — that way the Amplify dashboard-view and the Vercel
 * public-facing deploy both hand patients the same canonical intake URL.
 */
const PATIENT_PUBLIC_ORIGIN = "https://solacedemoai.vercel.app";

export default function QRCard() {
  const { hospitalId = "demo" } = useParams();
  const intakeUrl = `${PATIENT_PUBLIC_ORIGIN}/${hospitalId}`;

  return (
    <div className="min-h-[100dvh] flex flex-col items-center justify-center bg-surface px-8 py-12 gap-10">
      <img
        src="/solace-logo.png"
        alt="Solace"
        className="h-24 w-auto select-none"
        draggable={false}
      />

      <div className="flex flex-col items-center gap-3 text-center max-w-lg">
        <h1 className="text-[44px] font-bold tracking-editorial-tight leading-[1.05] text-ink">
          Scan to check in.
        </h1>
        <p className="text-lg text-text-muted leading-snug">
          Point your phone camera at the code.
          <br />
          No install, no account.
        </p>
      </div>

      <div className="bg-surface-lowest rounded-[32px] p-10 shadow-card">
        {intakeUrl ? (
          <QRCodeSVG
            value={intakeUrl}
            size={420}
            level="H"
            includeMargin={false}
            bgColor="#FFFFFF"
            fgColor="#1A2023"
          />
        ) : (
          <div className="h-[420px] w-[420px]" />
        )}
      </div>

      <div className="flex flex-col items-center gap-1">
        <div className="text-[11px] uppercase tracking-[0.22em] text-text-muted font-semibold">
          Direct link
        </div>
        <div className="font-mono text-sm text-ink">{intakeUrl || "\u00a0"}</div>
      </div>

      <div className="text-[11px] uppercase tracking-[0.22em] text-text-muted font-semibold">
        AI-assisted ER triage · Hook&apos;em Hacks 2026
      </div>
    </div>
  );
}
