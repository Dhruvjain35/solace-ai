import {
  Activity,
  X,
  GripVertical,
  CircleSlash,
  FlaskConical,
  ImageIcon,
  MonitorDot,
  Printer,
  MessageSquare,
} from 'lucide-react';
import AtlasSidebar, { ATLAS_FONT, ATLAS_MONO } from './AtlasSidebar';

/*
 * EhrScreen — the Solace Atlas patient snapshot opened full-width: acuity,
 * AI pre-brief, differential with must-not-miss flags, workup order set and
 * the SHAP attribution bars ("what drove this ESI"). Rebuilt as live DOM
 * for the LaptopRig from the 2026-06-11 recon of the live dashboard.
 * All sizes in cqw; decorative inside the rig.
 */

const DDX = [
  { name: 'Spontaneous pneumothorax', mustNotMiss: true, likely: 'MODERATE', icd: 'J93.9' },
  { name: 'ACS / Myocarditis', mustNotMiss: true, likely: 'MODERATE', icd: 'I24.1' },
  { name: 'Chest wall pain (MSK)', mustNotMiss: false, likely: 'MODERATE', icd: 'M94.0' },
  { name: 'Pulmonary embolism', mustNotMiss: true, likely: 'LOW', icd: 'I26.99' },
  { name: 'Aortic dissection', mustNotMiss: true, likely: 'LOW', icd: 'I71.00' },
] as const;

// 11 draft orders, matching the live app's "Accept all (11)".
const LABS = ['Troponin (serial)', 'BNP', 'D-dimer', 'CBC', 'BMP'] as const;
const IMAGING = ['ECG', 'CXR PA/lateral', 'CT chest PE protocol'] as const;
const MONITORING = ['Cardiac monitor', 'SpO₂', 'Vitals q15min'] as const;

// SHAP attribution rows — burnt-amber bars push acuity up, green pull down.
const DRIVERS = [
  { name: 'dyspnea_flag', value: '+1.12', width: '92%', up: true },
  { name: 'pain_score', value: '+0.86', width: '70%', up: true },
  { name: 'age', value: '−0.42', width: '34%', up: false },
  { name: 'news2_score', value: '−0.08', width: '8%', up: false },
  { name: 'temperature_c', value: '−0.02', width: '4%', up: false },
] as const;

function Label({ children, tone = '#4a5557' }: { children: string; tone?: string }) {
  return (
    <p
      className="font-semibold uppercase tracking-[0.16em]"
      style={{ fontSize: '0.6cqw', color: tone }}
    >
      {children}
    </p>
  );
}

function OrderChip({ children }: { children: string }) {
  return (
    <span
      className="rounded-[0.45cqw] bg-[#f3f4f4] px-[0.7cqw] py-[0.35cqw] font-medium"
      style={{ fontSize: '0.78cqw' }}
    >
      {children}
    </span>
  );
}

export default function EhrScreen() {
  return (
    <div
      className="flex h-full w-full bg-[#f8f9f9] text-left text-[#1a2023]"
      style={ATLAS_FONT}
    >
      <AtlasSidebar waiting={4} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-[1.3cqw]">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white">
          {/* Card chrome */}
          <div
            className="flex items-center gap-[0.7cqw] border-b border-[rgba(74,85,87,0.2)] bg-[#f3f4f4]/40 px-[1cqw] py-[0.7cqw]"
            style={{ fontSize: '0.95cqw' }}
          >
            <GripVertical size="1em" className="text-[#4a5557]/60" aria-hidden="true" />
            <Activity size="1em" strokeWidth={1.75} aria-hidden="true" />
            <span className="font-semibold">Patient snapshot</span>
            <span className="ml-[0.6cqw] text-[#4a5557]" style={{ fontSize: '0.8cqw' }}>
              Sriyan · 4m wait · EN
            </span>
            <X size="1em" className="ml-auto text-[#4a5557]" aria-hidden="true" />
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-2 gap-[1.1cqw] overflow-hidden p-[1.1cqw]">
            {/* ---- Left column: acuity → pre-brief → workup → dispo ---- */}
            <div className="min-h-0 space-y-[0.9cqw] overflow-hidden">
              <div className="rounded-[1.3cqw] border border-[rgba(74,85,87,0.2)] p-[0.9cqw]">
                <Label>Triage acuity</Label>
                <div className="mt-[0.5cqw] flex items-center gap-[1cqw]">
                  <span>
                    <p
                      className="font-semibold uppercase tracking-[0.1em] text-[#4a5557]"
                      style={{ fontSize: '0.55cqw' }}
                    >
                      Provisional · on intake
                    </p>
                    <p className="font-bold leading-tight" style={{ fontSize: '1.7cqw' }}>
                      ESI 3{' '}
                      <span className="font-normal text-[#4a5557]" style={{ fontSize: '0.8cqw' }}>
                        98%
                      </span>
                    </p>
                  </span>
                  <span className="text-[#4a5557]" style={{ fontSize: '1cqw' }}>
                    →
                  </span>
                  <span>
                    <p
                      className="font-semibold uppercase tracking-[0.1em] text-[#4a5557]"
                      style={{ fontSize: '0.55cqw' }}
                    >
                      Refined · vitals pending
                    </p>
                    <p className="italic text-[#4a5557]" style={{ fontSize: '0.9cqw' }}>
                      take vitals to refine
                    </p>
                  </span>
                </div>
              </div>

              <div>
                <Label>Pre-brief</Label>
                <p
                  className="mt-[0.4cqw] rounded-[0.85cqw] bg-[#cbe3e9]/40 p-[0.9cqw] leading-relaxed"
                  style={{ fontSize: '0.88cqw' }}
                >
                  19yo M c/o acute-onset chest tightness and sharp back pain
                  following basketball practice 1 hour ago, now worsening, with
                  associated dyspnea; denies trauma; reports pain 7–10/10. Hx
                  asthma on steroids; allergies: peanuts (moderate), sulfa
                  (anaphylaxis).
                </p>
              </div>

              <div>
                <div className="flex items-baseline justify-between">
                  <Label>Workup order set (AI draft)</Label>
                  <span className="font-semibold text-[#2a474e]" style={{ fontSize: '0.78cqw' }}>
                    Accept all (11)
                  </span>
                </div>
                <div className="mt-[0.5cqw] space-y-[0.6cqw] rounded-[0.85cqw] border border-[rgba(74,85,87,0.2)] p-[0.9cqw]">
                  <div className="flex items-center gap-[0.6cqw]">
                    <span className="shrink-0 text-[#4a5557]" style={{ fontSize: '0.95cqw' }}>
                      <FlaskConical size="1em" aria-hidden="true" />
                    </span>
                    <div className="flex flex-wrap gap-[0.4cqw]">
                      {LABS.map((l) => (
                        <OrderChip key={l}>{l}</OrderChip>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-[0.6cqw]">
                    <span className="shrink-0 text-[#4a5557]" style={{ fontSize: '0.95cqw' }}>
                      <ImageIcon size="1em" aria-hidden="true" />
                    </span>
                    <div className="flex flex-wrap gap-[0.4cqw]">
                      {IMAGING.map((l) => (
                        <OrderChip key={l}>{l}</OrderChip>
                      ))}
                    </div>
                  </div>
                  <div className="flex items-center gap-[0.6cqw]">
                    <span className="shrink-0 text-[#4a5557]" style={{ fontSize: '0.95cqw' }}>
                      <MonitorDot size="1em" aria-hidden="true" />
                    </span>
                    <div className="flex flex-wrap gap-[0.4cqw]">
                      {MONITORING.map((l) => (
                        <OrderChip key={l}>{l}</OrderChip>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-[0.7cqw]">
                <span
                  className="flex items-center gap-[0.4cqw] rounded-[0.45cqw] px-[0.8cqw] py-[0.4cqw] font-bold"
                  style={{ fontSize: '0.85cqw', color: '#b05436', background: 'rgba(176,84,54,0.15)' }}
                >
                  ◉ OBSERVE
                </span>
                <span className="text-[#4a5557]" style={{ fontSize: '0.85cqw' }}>
                  · obs unit · ~6h LOS
                </span>
              </div>

              <div>
                <Label>Patient&rsquo;s words</Label>
                <p
                  className="mt-[0.4cqw] italic leading-relaxed text-[#4a5557]"
                  style={{ fontSize: '0.88cqw' }}
                >
                  &ldquo;I have a tight feeling in my chest and sharp back
                  pain. It started after basketball practice an hour ago and
                  is getting worse.&rdquo;
                </p>
              </div>

              <div>
                <Label>Risk scores</Label>
                <p
                  className="mt-[0.4cqw] rounded-[0.85cqw] border border-[rgba(74,85,87,0.2)] p-[0.9cqw] italic leading-relaxed text-[#4a5557]"
                  style={{ fontSize: '0.85cqw' }}
                >
                  Awaiting bedside vitals. Enter HR, BP, RR and SpO₂ and the
                  system refines the triage score automatically.
                </p>
              </div>
            </div>

            {/* ---- Right column: differential → attribution → actions ---- */}
            <div className="flex min-h-0 flex-col justify-between gap-[0.9cqw] overflow-hidden">
              <div>
                <div className="flex items-baseline justify-between">
                  <Label>Differential diagnosis (AI draft)</Label>
                  <span className="text-[#4a5557]" style={{ fontSize: '0.75cqw' }}>
                    9 entries
                  </span>
                </div>
                <div className="mt-[0.5cqw] space-y-[0.45cqw]">
                  {DDX.map((d) => (
                    <div
                      key={d.name}
                      className="flex items-center gap-[0.6cqw] rounded-[0.85cqw] border border-[rgba(74,85,87,0.2)] px-[0.8cqw] py-[0.55cqw]"
                    >
                      <p className="min-w-0 flex-1 truncate font-semibold" style={{ fontSize: '0.88cqw' }}>
                        {d.name}
                      </p>
                      {d.mustNotMiss && (
                        <span
                          className="flex shrink-0 items-center gap-[0.3cqw] rounded-[0.3cqw] bg-[#ba1a1a] px-[0.5cqw] py-[0.25cqw] font-bold uppercase text-white"
                          style={{ fontSize: '0.58cqw' }}
                        >
                          <CircleSlash size="1em" aria-hidden="true" /> Must not miss
                        </span>
                      )}
                      <span
                        className="shrink-0 rounded-full px-[0.6cqw] py-[0.25cqw] font-semibold uppercase"
                        style={
                          d.likely === 'MODERATE'
                            ? { fontSize: '0.58cqw', color: '#b05436', background: 'rgba(176,84,54,0.15)' }
                            : { fontSize: '0.58cqw', color: '#4a5557', background: '#f3f4f4' }
                        }
                      >
                        {d.likely}
                      </span>
                      <span
                        className="shrink-0 text-[#4a5557]"
                        style={{ ...ATLAS_MONO, fontSize: '0.72cqw' }}
                      >
                        {d.icd}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <Label>What drove this ESI</Label>
                <div className="mt-[0.5cqw] space-y-[0.45cqw]">
                  {DRIVERS.map((f) => (
                    <div key={f.name} className="flex items-center gap-[0.7cqw]" style={ATLAS_MONO}>
                      <span className="w-[32%] truncate" style={{ fontSize: '0.75cqw' }}>
                        {f.name}
                      </span>
                      <span className="h-[0.9cqw] flex-1 overflow-hidden rounded-[0.25cqw] bg-[#f3f4f4]">
                        <span
                          className="block h-full rounded-[0.25cqw]"
                          style={{ width: f.width, background: f.up ? '#b05436' : '#557d6e' }}
                        />
                      </span>
                      <span className="w-[3.4cqw] text-right" style={{ fontSize: '0.75cqw' }}>
                        {f.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-auto flex items-center gap-[0.6cqw]">
                <span
                  className="flex items-center gap-[0.45cqw] rounded-[0.45cqw] border border-[rgba(74,85,87,0.2)] bg-[#f3f4f4] px-[0.9cqw] py-[0.55cqw] font-semibold"
                  style={{ fontSize: '0.85cqw' }}
                >
                  <Printer size="1em" aria-hidden="true" /> Print notes
                </span>
                <span
                  className="flex items-center gap-[0.45cqw] rounded-[0.45cqw] border border-[rgba(74,85,87,0.2)] bg-[#f3f4f4] px-[0.9cqw] py-[0.55cqw] font-semibold"
                  style={{ fontSize: '0.85cqw' }}
                >
                  <MessageSquare size="1em" aria-hidden="true" /> Text discharge
                </span>
                <span
                  className="flex-1 rounded-[0.45cqw] bg-[#2a474e] py-[0.6cqw] text-center font-medium text-white"
                  style={{ fontSize: '0.95cqw' }}
                >
                  Mark seen
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
