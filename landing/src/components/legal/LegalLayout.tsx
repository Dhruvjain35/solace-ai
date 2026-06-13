import { useMemo } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import type { ReactNode } from 'react';
import { himsFade, himsMove } from '../../lib/hims';

/*
 * LegalLayout — the shared shell for Solace's long-form legal pages
 * (Privacy, Terms, and the prose half of HIPAA). It mirrors the Product /
 * Company design system: the same two-curve reveal, font-sofia display type,
 * tracking-hims, and the mint wash band rhythm. A centered hero carries an
 * eyebrow, a mega title, a sub-line and a "Last updated" stamp; the body is a
 * single max-w prose column with an optional sticky table-of-contents on the
 * right at ≥lg. Section / prose primitives live here so every legal page reads
 * the same. No backend, no external state — content is passed as children.
 */

// Barely-there mint wash, matched to the hims band rhythm used across the site.
const WASH_MINT_TO_WHITE = 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)';

// House reveal: opacity rides HIMS_OUT (0.2s), y rides HIMS_EXPO (0.6s),
// siblings stagger 0.04s by index; y is zeroed under reduced motion.
export function Reveal({
  index = 0,
  reduce,
  className,
  children,
}: {
  index?: number;
  reduce: boolean | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: reduce ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{
        opacity: { ...himsFade, delay: index * 0.04 },
        y: { ...himsMove, delay: index * 0.04 },
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

// Convert a heading to a stable anchor id for the table of contents.
function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

export type LegalSection = { id: string; title: string };

// One titled prose block. The id lets the table of contents link to it; the
// heading carries scroll-margin so the floating nav never clips it.
export function Section({
  title,
  reduce,
  index = 0,
  children,
}: {
  title: string;
  reduce: boolean | null;
  index?: number;
  children: ReactNode;
}) {
  const id = slugify(title);
  return (
    <Reveal index={index} reduce={reduce} className="scroll-mt-32">
      <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-32 pt-12 first:pt-0">
        <h2
          id={`${id}-h`}
          className="font-sofia text-[clamp(22px,2.4vw,32px)] font-medium leading-[1.14] tracking-[-0.02em] text-ink"
        >
          {title}
        </h2>
        <div className="prose-legal mt-5 space-y-4 text-[15px] leading-relaxed text-muted md:text-base">
          {children}
        </div>
      </section>
    </Reveal>
  );
}

// Reusable prose primitives so page files stay declarative and under budget.
export function P({ children }: { children: ReactNode }) {
  return <p className="max-w-[68ch]">{children}</p>;
}

export function Strong({ children }: { children: ReactNode }) {
  return <strong className="font-semibold text-ink">{children}</strong>;
}

export function UL({ children }: { children: ReactNode }) {
  return (
    <ul className="max-w-[68ch] list-disc space-y-2 pl-5 marker:text-solace-green-500">
      {children}
    </ul>
  );
}

export function LI({ children }: { children: ReactNode }) {
  return <li className="pl-1">{children}</li>;
}

// A quiet callout for the counsel-review notices and similar asides.
export function Callout({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-[68ch] rounded-tile border border-solace-green-500/20 bg-solace-soft/60 p-5 text-[14px] leading-relaxed text-ink md:text-[15px]">
      {children}
    </div>
  );
}

export default function LegalLayout({
  eyebrow,
  title,
  sub,
  lastUpdated,
  sections,
  children,
}: {
  eyebrow: string;
  title: string;
  sub: string;
  lastUpdated: string;
  // When provided, renders a sticky table of contents at ≥lg.
  sections?: LegalSection[];
  children: ReactNode;
}) {
  const reduce = useReducedMotion();
  const toc = useMemo(() => sections ?? [], [sections]);
  const hasToc = toc.length > 0;

  return (
    <div className="bg-white">
      {/* ===== Hero — centered, mint wash, mega Sofia title ===== */}
      <section
        aria-labelledby="legal-heading"
        className="bg-white px-6 pb-[8vh] pt-[16vh] text-center md:pt-[24vh]"
        style={{ backgroundImage: WASH_MINT_TO_WHITE }}
      >
        <Reveal index={0} reduce={reduce}>
          <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-muted">
            {eyebrow}
          </p>
        </Reveal>
        <Reveal index={1} reduce={reduce}>
          <h1
            id="legal-heading"
            className="mx-auto mt-5 max-w-[16ch] font-sofia text-[clamp(40px,6vw,88px)] font-medium leading-[1.03] tracking-hims text-ink"
          >
            {title}
          </h1>
        </Reveal>
        <Reveal index={2} reduce={reduce}>
          <p className="mx-auto mt-6 max-w-xl text-base text-muted md:text-lg">
            {sub}
          </p>
        </Reveal>
        <Reveal index={3} reduce={reduce}>
          <p className="mt-7 text-[13px] font-medium uppercase tracking-[0.12em] text-muted/80">
            Last updated {lastUpdated}
          </p>
        </Reveal>
      </section>

      {/* ===== Body — prose column with optional sticky table of contents ===== */}
      <section className="bg-white px-6 pb-[10vh] pt-[2vh] md:pb-[16vh]">
        <div
          className={`mx-auto grid max-w-[1100px] gap-12 ${
            hasToc ? 'lg:grid-cols-[minmax(0,1fr)_240px]' : 'max-w-[760px]'
          }`}
        >
          <div className="min-w-0 divide-y divide-black/5">{children}</div>

          {hasToc ? (
            <aside className="hidden lg:block">
              <div className="sticky top-32">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
                  On this page
                </p>
                <nav aria-label="On this page" className="mt-4">
                  <ul className="space-y-2.5 border-l border-black/8 pl-4">
                    {toc.map((s) => (
                      <li key={s.id}>
                        <a
                          href={`#${s.id}`}
                          className="block text-[13.5px] leading-snug text-muted transition-colors hover:text-solace-green-700"
                        >
                          {s.title}
                        </a>
                      </li>
                    ))}
                  </ul>
                </nav>
              </div>
            </aside>
          ) : null}
        </div>
      </section>
    </div>
  );
}
