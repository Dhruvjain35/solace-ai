import { FileText, GripVertical, X, PenLine } from 'lucide-react';
import AtlasSidebar, { ATLAS_FONT } from './AtlasSidebar';

/*
 * LettersScreen — the Solace Atlas letters & forms workspace as live DOM
 * for the LaptopRig. The real product ships 24 chart-aware templates
 * (work/school notes, FMLA, return-to-play, travel, medical necessity);
 * the AI drafts from the visit and the clinician signs. Decorative only.
 */

const TEMPLATES = [
  { name: 'Work or school note', active: true },
  { name: 'FMLA certification', active: false },
  { name: 'Return to play (concussion)', active: false },
  { name: 'Fitness to travel', active: false },
  { name: 'Medical necessity', active: false },
  { name: 'Jury duty excuse', active: false },
] as const;

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

export default function LettersScreen() {
  return (
    <div
      className="flex h-full w-full bg-[#f8f9f9] text-left text-[#1a2023]"
      style={ATLAS_FONT}
    >
      <AtlasSidebar waiting={4} />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-[1.3cqw]">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[1.1cqw] border border-[rgba(74,85,87,0.2)] bg-white">
          {/* card chrome */}
          <div
            className="flex items-center gap-[0.7cqw] border-b border-[rgba(74,85,87,0.2)] bg-[#f3f4f4]/40 px-[1cqw] py-[0.7cqw]"
            style={{ fontSize: '0.95cqw' }}
          >
            <GripVertical size="1em" className="text-[#4a5557]/60" aria-hidden="true" />
            <FileText size="1em" strokeWidth={1.75} aria-hidden="true" />
            <span className="font-semibold">Letters &amp; forms</span>
            <span className="ml-[0.6cqw] text-[#4a5557]" style={{ fontSize: '0.8cqw' }}>
              Sriyan · drafted from today&rsquo;s visit
            </span>
            <X size="1em" className="ml-auto text-[#4a5557]" aria-hidden="true" />
          </div>

          <div className="grid min-h-0 flex-1 grid-cols-[36%_1fr] gap-[1.1cqw] overflow-hidden p-[1.1cqw]">
            {/* template library */}
            <div className="min-h-0 overflow-hidden">
              <Label>24 templates, chart-aware</Label>
              <div className="mt-[0.5cqw] space-y-[0.45cqw]">
                {TEMPLATES.map((t) => (
                  <div
                    key={t.name}
                    className={`rounded-[0.85cqw] px-[0.9cqw] py-[0.65cqw] font-medium ${
                      t.active
                        ? 'bg-[#cbe3e9]/50 text-[#1a2023] ring-1 ring-[#2a474e]/40'
                        : 'border border-[rgba(74,85,87,0.2)] text-[#4a5557]'
                    }`}
                    style={{ fontSize: '0.9cqw' }}
                  >
                    {t.name}
                  </div>
                ))}
              </div>
            </div>

            {/* drafted letter preview */}
            <div className="flex min-h-0 flex-col overflow-hidden">
              <div className="flex items-baseline justify-between">
                <Label>Draft preview</Label>
                <span className="italic text-[#4a5557]" style={{ fontSize: '0.75cqw' }}>
                  review before signing
                </span>
              </div>
              <div className="mt-[0.5cqw] flex min-h-0 flex-1 flex-col rounded-[0.85cqw] border border-[rgba(74,85,87,0.2)] bg-white p-[1.2cqw] shadow-sm">
                <p className="font-semibold text-[#2a474e]" style={{ fontSize: '0.95cqw' }}>
                  Work or school note
                </p>
                <div className="mt-[0.8cqw] space-y-[0.6cqw] leading-relaxed" style={{ fontSize: '0.88cqw' }}>
                  <p>To whom it may concern,</p>
                  <p>
                    Sriyan was evaluated in our emergency department today for
                    chest tightness and back pain after exercise. He was
                    assessed, observed and discharged in stable condition.
                  </p>
                  <p>
                    He may return to school on Monday. Please excuse his
                    absence today and tomorrow. No contact sports or strenuous
                    exercise for 48 hours.
                  </p>
                  <p className="text-[#4a5557]">
                    Drafted by Solace from the visit record. Valid only once
                    reviewed and signed by the treating clinician.
                  </p>
                </div>
                <div className="mt-auto flex items-center gap-[0.6cqw] pt-[0.9cqw]">
                  <span
                    className="rounded-[0.45cqw] border border-[rgba(74,85,87,0.2)] bg-[#f3f4f4] px-[0.9cqw] py-[0.5cqw] font-semibold"
                    style={{ fontSize: '0.85cqw' }}
                  >
                    Edit draft
                  </span>
                  <span
                    className="flex items-center gap-[0.45cqw] rounded-[0.45cqw] bg-[#2a474e] px-[1cqw] py-[0.55cqw] font-medium text-white"
                    style={{ fontSize: '0.9cqw' }}
                  >
                    <PenLine size="1em" aria-hidden="true" /> Sign and send
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
