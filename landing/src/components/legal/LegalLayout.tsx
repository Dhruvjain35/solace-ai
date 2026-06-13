import { Children, isValidElement, cloneElement, useMemo } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import type { ReactElement, ReactNode } from 'react';
import { himsFade, himsMove } from '../../lib/hims';
import { ReadingProgress, ScrollSpyToc, MobileToc, BackToTop } from './Reading';

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
// heading carries scroll-margin so the floating nav never clips it. `number`
// is injected by LegalLayout from document order — a document-grade 01, 02 … .
export function Section({
  title,
  reduce,
  index = 0,
  number,
  children,
}: {
  title: string;
  reduce: boolean | null;
  index?: number;
  number?: number;
  children: ReactNode;
}) {
  const id = slugify(title);
  return (
    <Reveal index={index} reduce={reduce} className="scroll-mt-32">
      <section
        id={id}
        aria-labelledby={`${id}-h`}
        className="scroll-mt-32 py-12 first:pt-0"
      >
        <div className="flex items-baseline gap-4">
          {number ? (
            <span
              aria-hidden="true"
              className="select-none font-mono text-[13px] font-medium tabular-nums tracking-tight text-solace-green-500"
            >
              {String(number).padStart(2, '0')}
            </span>
          ) : null}
          <h2
            id={`${id}-h`}
            className="font-sofia text-[clamp(22px,2.4vw,32px)] font-medium leading-[1.14] tracking-[-0.02em] text-ink"
          >
            {title}
          </h2>
        </div>
        <div
          className={`prose-legal mt-5 space-y-4 text-[15px] leading-relaxed text-muted md:text-base ${
            number ? 'md:pl-[2.4rem]' : ''
          }`}
        >
          {children}
        </div>
      </section>
    </Reveal>
  );
}

// Reusable prose primitives so page files stay declarative and under budget.
// Measure is held to a comfortable ~68ch for calm, readable lines.
export function P({ children }: { children: ReactNode }) {
  return <p className="max-w-[68ch] text-ink/75">{children}</p>;
}

export function Strong({ children }: { children: ReactNode }) {
  return <strong className="font-semibold text-ink">{children}</strong>;
}

export function UL({ children }: { children: ReactNode }) {
  return (
    <ul className="max-w-[68ch] space-y-3 text-ink/75">{children}</ul>
  );
}

// Custom list marker: a small mint tick-rule instead of a bullet glyph, for a
// crisper, document-grade list.
export function LI({ children }: { children: ReactNode }) {
  return (
    <li className="relative pl-6">
      <span
        aria-hidden="true"
        className="absolute left-0 top-[0.6em] h-1.5 w-1.5 -translate-y-1/2 rounded-full bg-solace-green-500"
      />
      {children}
    </li>
  );
}

// A quiet callout for the counsel-review notices and similar asides — a mint
// rule on the left, a soft wash, calm type.
export function Callout({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-[68ch] rounded-tile border border-solace-green-500/15 border-l-[3px] border-l-solace-green-500 bg-solace-soft/50 px-5 py-4 text-[14px] leading-relaxed text-ink/80 md:text-[15px]">
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

  // Inject a sequential document number into each <Section> child from its
  // position in the body, so the page files stay declarative.
  const numbered = useMemo(() => {
    let n = 0;
    return Children.map(children, (child) => {
      if (!isValidElement(child) || child.type !== Section) return child;
      n += 1;
      return cloneElement(child as ReactElement<{ number?: number }>, {
        number: n,
      });
    });
  }, [children]);

  return (
    <div className="bg-white">
      <ReadingProgress />

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

      {/* ===== Body — prose column with optional scroll-spy table of contents ===== */}
      <section className="bg-white px-6 pb-[10vh] pt-[2vh] md:pb-[16vh]">
        <div
          className={`mx-auto grid max-w-[1100px] gap-12 lg:gap-16 ${
            hasToc ? 'lg:grid-cols-[minmax(0,1fr)_240px]' : 'max-w-[760px]'
          }`}
        >
          <div className="min-w-0">
            {hasToc ? <MobileToc sections={toc} /> : null}
            <div className="divide-y divide-black/[0.06]">{numbered}</div>
            <div className="pt-10">
              <BackToTop />
            </div>
          </div>

          {hasToc ? <ScrollSpyToc sections={toc} /> : null}
        </div>
      </section>
    </div>
  );
}
