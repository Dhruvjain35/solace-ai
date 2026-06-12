import {
  Activity,
  Bell,
  Clock,
  ShieldCheck,
  Search,
  Plus,
  X,
  GripVertical,
  Users,
  Mic,
} from 'lucide-react';
import AtlasSidebar, { ATLAS_FONT, ATLAS_MONO } from './AtlasSidebar';

/*
 * QueueScreen — the Solace Atlas clinician workspace (live queue + ambient
 * scribe + tagged-patient snapshot preview), rebuilt as live DOM for the
 * LaptopRig from the 2026-06-11 recon of solaceaidemo.vercel.app/demo/clinician.
 * All sizes in cqw so it scales vector-crisp; decorative inside the rig.
 */

const STATS = [
  { label: 'Patients waiting', value: '4', Icon: Activity, circle: '#cbe3e9' },
  { label: 'Active pain alarms', value: '1', Icon: Bell, circle: '#f3f4f4' },
  { label: 'Avg wait', value: '41m', Icon: Clock, circle: '#f3f4f4' },
  { label: 'ML-refined', value: '75%', Icon: ShieldCheck, circle: '#f3f4f4' },
] as const;

// ESI badge colors per Atlas: gold 3, burnt-amber 2 ("burnt-amber pushes
// acuity up"), muted slate 4–5.
const ESI_TONE: Record<number, string> = {
  2: '#b05436',
  3: '#b8924a',
  4: '#4a5557',
};

const QUEUE = [
  { name: 'Sriyan', sub: '4m wait · EN', esi: 3, active: true },
  { name: 'Elena', sub: '12m wait · ES', esi: 2, active: false },
  { name: 'Wei', sub: '9m wait · ZH', esi: 4, active: false },
  { name: 'Amira', sub: '16m wait · AR', esi: 3, active: false },
] as const;

// Shared workspace-card chrome: drag grip, icon, title, close.
function CardHeader({ Icon, title }: { Icon: typeof Users; title: string }) {
  return (
    <div
      className="flex items-center gap-[0.7cqw] border-b border-[rgba(74,85,87,0.2)] bg-[#f3f4f4]/40 px-[1cqw] py-[0.7cqw]"
      style={{ fontSize: '0.95cqw' }}
    >
      <GripVertical size="1em" className="text-[#4a5557]/60" aria-hidden="true" />
      <Icon size="1em" strokeWidth={1.75} aria-hidden="true" />
      <span className="font-semibold">{title}</span>
      <X size="1em" className="ml-auto text-[#4a5557]" aria-hidden="true" />
    </div>
  );
}

function Label({ children }: { children: string }) {
  return (
    <p
      className="font-semibold uppercase tracking-[0.16em] text-[#4a5557]"
      style={{ fontSize: '0.6cqw' }}
    >
      {children}
    </p>
  );
}

export default function QueueScreen() {
  return (
    <div
      className="flex h-full w-full bg-[#f8f9f9] text-left text-[#1a2023]"
      style={ATLAS_FONT}
    >
      <AtlasSidebar waiting={4} />

      <div className="flex min-w-0 flex-1 flex-col gap-[1cqw] overflow-hidden p-[1.3cqw]">
        {/* Stats band */}
        <div className="flex gap-[0.9cqw]">
          {STATS.map(({ label, value, Icon, circle }) => (
            <div
              key={label}
              className="flex flex-1 items-center gap-[0.8cqw] rounded-[1.3cqw] border border-[rgba(74,85,87,0.2)] bg-white px-[1cqw] py-[0.8cqw]"
            >
              <span
                className="flex shrink-0 items-center justify-center rounded-full text-[#2a474e]"
                style={{ width: '2.5cqw', height: '2.5cqw', background: circle, fontSize: '1.1cqw' }}
              >
                <Icon size="1em" strokeWidth={1.75} aria-hidden="true" />
              </span>
              <span>
                <Label>{label}</Label>
                <p className="font-bold leading-tight" style={{ fontSize: '1.5cqw' }}>
                  {value}
                </p>
              </span>
            </div>
          ))}
        </div>

        {/* Search / tag bar */}
        <div className="rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white p-[0.7cqw]">
          <div
            className="flex items-center gap-[0.7cqw] rounded-full bg-[#f3f4f4] px-[1cqw] text-[#4a5557]"
            style={{ height: '2.6cqw', fontSize: '0.95cqw' }}
          >
            <Search size="1em" aria-hidden="true" />
            Search patients to tag…
          </div>
          <span
            className="mt-[0.6cqw] inline-flex items-center gap-[0.5cqw] rounded-full bg-[#2a474e] px-[0.9cqw] py-[0.35cqw] font-semibold text-white"
            style={{ fontSize: '0.8cqw' }}
          >
            Sriyan <X size="1em" aria-hidden="true" />
          </span>
        </div>

        {/* Workspace header */}
        <div className="flex items-end justify-between">
          <div>
            <p className="font-semibold" style={{ fontSize: '1.25cqw' }}>
              My workspace
            </p>
            <p className="text-[#4a5557]" style={{ fontSize: '0.9cqw' }}>
              Active patient · Sriyan
            </p>
          </div>
          <span
            className="flex items-center gap-[0.45cqw] rounded-full bg-[#2a474e] px-[1.1cqw] py-[0.6cqw] font-semibold text-white"
            style={{ fontSize: '0.9cqw' }}
          >
            <Plus size="1em" aria-hidden="true" /> Add feature
          </span>
        </div>

        {/* Workspace grid */}
        <div className="grid min-h-0 flex-1 grid-cols-2 gap-[1cqw]">
          <div className="flex min-h-0 flex-col gap-[1cqw]">
            {/* Live queue */}
            <div className="overflow-hidden rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white">
              <CardHeader Icon={Users} title="Live queue" />
              <div className="space-y-[0.45cqw] p-[0.7cqw]">
                {QUEUE.map((p) => (
                  <div
                    key={p.name}
                    className={`flex items-center gap-[0.8cqw] rounded-[1.3cqw] px-[0.8cqw] py-[0.55cqw] ${
                      p.active
                        ? 'bg-[#cbe3e9]/50 ring-1 ring-[#2a474e]/40'
                        : ''
                    }`}
                  >
                    <span
                      className="flex shrink-0 items-center justify-center rounded-full font-bold text-white"
                      style={{
                        width: '2.4cqw',
                        height: '2.4cqw',
                        fontSize: '1.05cqw',
                        background: ESI_TONE[p.esi],
                      }}
                    >
                      {p.esi}
                    </span>
                    <span>
                      <p className="font-semibold leading-tight" style={{ fontSize: '1cqw' }}>
                        {p.name}
                      </p>
                      <p className="text-[#4a5557]" style={{ fontSize: '0.78cqw' }}>
                        {p.sub}
                      </p>
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Ambient scribe */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white">
              <CardHeader Icon={Mic} title="Ambient scribe" />
              <div className="min-h-0 flex-1 p-[1cqw]">
                <p className="font-semibold" style={{ fontSize: '1.05cqw' }}>
                  Encounter for Sriyan
                </p>
                <p className="mt-[0.3cqw] text-[#4a5557]" style={{ fontSize: '0.82cqw' }}>
                  Captures the bedside conversation in chunks, then finalizes
                  an evidence-linked SOAP note.
                </p>
                <div className="mt-[0.9cqw] flex items-center justify-between border-t border-[rgba(74,85,87,0.2)] pt-[0.8cqw]">
                  <Label>Recording session</Label>
                  <span className="flex items-center gap-[0.5cqw] text-[#4a5557]" style={{ fontSize: '0.8cqw' }}>
                    Chunks
                    <span
                      className="rounded-[0.4cqw] bg-[#f3f4f4] px-[0.6cqw] py-[0.2cqw] font-semibold text-[#1a2023]"
                      style={{ ...ATLAS_MONO, fontSize: '0.85cqw' }}
                    >
                      0
                    </span>
                  </span>
                </div>
                <span
                  className="mt-[0.7cqw] inline-flex items-center gap-[0.5cqw] rounded-[0.45cqw] bg-[#ba1a1a] px-[1cqw] py-[0.55cqw] font-medium text-white"
                  style={{ fontSize: '0.9cqw' }}
                >
                  <span className="h-[0.55cqw] w-[0.55cqw] rounded-full bg-white" />
                  Start session
                </span>
                <p className="mt-[0.6cqw] text-[#4a5557]" style={{ fontSize: '0.78cqw' }}>
                  No active session. Start one to capture the encounter
                  hands-free.
                </p>
              </div>
            </div>
          </div>

          {/* Patient snapshot (preview) */}
          <div className="flex min-h-0 flex-col overflow-hidden rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white">
            <CardHeader Icon={Activity} title="Patient snapshot" />
            <div className="min-h-0 flex-1 space-y-[0.8cqw] overflow-hidden p-[1cqw]">
              <p className="text-[#4a5557]" style={{ fontSize: '0.8cqw' }}>
                4m wait · EN
              </p>

              {/* Triage acuity */}
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

              {/* Pre-brief */}
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
                  (anaphylaxis). Photo: none.
                </p>
              </div>

              {/* Scribe note */}
              <div>
                <Label>Scribe note (AI draft)</Label>
                <div
                  className="mt-[0.4cqw] space-y-[0.35cqw] rounded-[0.85cqw] bg-[#f3f4f4] p-[0.9cqw] leading-relaxed"
                  style={{ fontSize: '0.85cqw' }}
                >
                  <p>CC: Chest tightness and sharp back pain post-basketball.</p>
                  <p>
                    HPI: 19yo M c/o tight chest and sharp back pain onset ~1hr
                    ago after basketball practice, progressive worsening.
                    Denies trauma/fall. Reports SOB at present.
                  </p>
                  <p>ROS: SOB pos. HA, N/V, abd pain neg.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
