import { Mic, Inbox, FileText, Workflow } from 'lucide-react';

/*
 * AtlasSidebar — the left rail of the Solace Atlas clinician terminal
 * (solaceaidemo.vercel.app/demo/clinician, recon 2026-06-11), shared by the
 * QueueScreen and EhrScreen laptop recreations. All sizes in cqw so it
 * scales vector-crisp inside the LaptopRig; decorative only.
 *
 * Atlas palette: page #f8f9f9 · rail #f3f4f4 · ink #1a2023 · muted #4a5557
 * · primary teal #2a474e · active blue #cbe3e9 · hairlines rgba(74,85,87,.2).
 */

export const ATLAS_FONT = {
  fontFamily: '"DM Sans", "Figtree", system-ui, sans-serif',
} as const;
export const ATLAS_MONO = {
  fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, monospace',
} as const;

const ADMIN_ITEMS = [
  ['Ambient scribe', Mic],
  ['Inbox + admin', Inbox],
  ['Letters & forms', FileText],
  ['Workflows', Workflow],
] as const;

// A deterministic QR-looking module grid for the "patients scan to check in"
// card — three finder squares plus a fixed scatter, drawn once as SVG.
const QR_MODULES = [
  [4, 0], [5, 0], [8, 0], [4, 2], [6, 2], [5, 3], [7, 3], [8, 4], [4, 4],
  [0, 4], [2, 4], [1, 5], [3, 5], [9, 5], [10, 4], [5, 5], [7, 5], [4, 6],
  [6, 6], [8, 6], [10, 6], [0, 8], [2, 8], [4, 8], [7, 8], [9, 8], [5, 9],
  [8, 9], [10, 9], [4, 10], [6, 10], [9, 10],
] as const;

function QrGlyph() {
  return (
    <svg viewBox="0 0 11 11" className="h-auto w-[55%]" aria-hidden="true">
      {/* finder squares */}
      {[[0, 0], [8, 0], [0, 8]].map(([x, y]) => (
        <g key={`${x}-${y}`} fill="none">
          <rect x={x} y={y} width={3} height={3} fill="#1a2023" />
          <rect x={x + 1} y={y + 1} width={1} height={1} fill="#ffffff" />
        </g>
      ))}
      {QR_MODULES.map(([x, y]) => (
        <rect key={`${x}.${y}`} x={x} y={y} width={1} height={1} fill="#1a2023" />
      ))}
    </svg>
  );
}

export default function AtlasSidebar({ waiting }: { waiting: number }) {
  return (
    <div className="flex h-full w-[19%] shrink-0 flex-col border-r border-[rgba(74,85,87,0.2)] bg-[#f3f4f4] p-[1.2cqw]">
      {/* Logo lockup */}
      <div className="flex items-center gap-[0.6cqw]">
        <span
          className="flex items-center justify-center rounded-[0.55cqw] border-[0.16cqw] border-[#2a474e] font-bold text-[#2a474e]"
          style={{ width: '2.2cqw', height: '2.2cqw', fontSize: '1.3cqw' }}
        >
          S
        </span>
        <span className="font-semibold text-[#2a474e]" style={{ fontSize: '1.7cqw' }}>
          solace
        </span>
      </div>
      <p
        className="mt-[0.3cqw] font-semibold uppercase tracking-[0.22em] text-[#4a5557]"
        style={{ fontSize: '0.62cqw' }}
      >
        Atlas
      </p>

      {/* Clinician card */}
      <div className="mt-[1cqw] flex items-center gap-[0.7cqw] rounded-[0.85cqw] bg-white p-[0.7cqw]">
        <span
          className="flex shrink-0 items-center justify-center rounded-full bg-[#2a474e] font-semibold text-white"
          style={{ width: '2.4cqw', height: '2.4cqw', fontSize: '1cqw' }}
        >
          C
        </span>
        <span className="min-w-0 flex-1">
          <p className="truncate font-semibold leading-tight" style={{ fontSize: '1cqw' }}>
            Dr. Chen
          </p>
          <p
            className="font-semibold uppercase tracking-[0.14em] text-[#4a5557]"
            style={{ fontSize: '0.6cqw' }}
          >
            Chief
          </p>
        </span>
        <span
          className="shrink-0 font-semibold uppercase tracking-[0.1em] text-[#4a5557]"
          style={{ fontSize: '0.55cqw' }}
        >
          Sign out
        </span>
      </div>

      {/* Queue nav */}
      <p
        className="mt-[1.2cqw] font-semibold uppercase tracking-[0.18em] text-[#4a5557]"
        style={{ fontSize: '0.62cqw' }}
      >
        Queue
      </p>
      <div
        className="mt-[0.5cqw] flex items-center justify-between rounded-[0.85cqw] bg-[#cbe3e9] px-[0.9cqw] py-[0.65cqw] font-medium text-[#2a474e]"
        style={{ fontSize: '0.95cqw' }}
      >
        Waiting <span className="opacity-70">{waiting}</span>
      </div>
      <div
        className="flex items-center justify-between px-[0.9cqw] py-[0.65cqw] font-medium text-[#4a5557]"
        style={{ fontSize: '0.95cqw' }}
      >
        All <span className="opacity-70">{waiting + 2}</span>
      </div>

      {/* Admin nav */}
      <p
        className="mt-[1cqw] font-semibold uppercase tracking-[0.18em] text-[#4a5557]"
        style={{ fontSize: '0.62cqw' }}
      >
        Admin
      </p>
      <div className="mt-[0.4cqw] space-y-[0.15cqw]">
        {ADMIN_ITEMS.map(([label, Icon]) => (
          <div
            key={label}
            className="flex items-center gap-[0.7cqw] px-[0.9cqw] py-[0.55cqw] font-medium text-[#4a5557]"
            style={{ fontSize: '0.92cqw' }}
          >
            <Icon size="1.1em" strokeWidth={1.75} aria-hidden="true" />
            {label}
          </div>
        ))}
      </div>

      {/* Check-in QR */}
      <div className="mt-auto flex flex-col items-center rounded-[0.85cqw] bg-white p-[1cqw]">
        <QrGlyph />
        <p className="mt-[0.7cqw] text-center text-[#4a5557]" style={{ fontSize: '0.72cqw' }}>
          Patients scan to check in
        </p>
      </div>
    </div>
  );
}
