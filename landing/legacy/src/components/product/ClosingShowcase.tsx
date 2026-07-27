import { useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AnimatePresence,
  motion,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from 'framer-motion';
import { ChevronDown } from 'lucide-react';
import { APP_SCREENS, HIMS_OUT, HIMS_EXPO, himsFade, himsMove } from '../../lib/hims';
import useIsWide from '../../lib/useIsWide';
import PhoneRig from './PhoneRig';

/*
 * ClosingShowcase, the Product page's closing act, a structural clone of the
 * end of app.forhims.com: the pale-gradient hand+phone farewell card, the
 * teal-gradient mega paragraph scrubbed word-by-word on scroll, and the
 * minimal right-aligned FAQ rows. Remapped onto the Solace brand; the rig,
 * curves and tokens come from ../../lib/hims, same as IntakeShowcase.
 */

// Shared reveal: opacity rides HIMS_OUT (0.2s), transform rides HIMS_EXPO (0.6s).
const REVEAL_TRANSITION = {
  opacity: { duration: 0.2, ease: HIMS_OUT },
  y: { duration: 0.6, ease: HIMS_EXPO },
} as const;

const MEGA_TEXT =
  'Calm, understandable emergency care has never been easier. And when everyone can see the line, the waiting room finally makes sense, to the people running it and the people sitting in it.';
const MEGA_WORDS = MEGA_TEXT.split(' ');

const FAQS = [
  {
    q: 'Where does Solace run?',
    a: 'Patients check in on their own phone from a QR code in your waiting room. There is nothing to install. Clinicians see the summary on their dashboard or inside the tools they already use.',
  },
  {
    q: 'Does Solace replace triage nurses?',
    a: 'No. Solace handles the paperwork side. It drafts a suggested urgency level and a clean history so your nurses start informed, and a clinician always makes the call.',
  },
  {
    q: 'What languages are supported?',
    a: '20 at launch, voice and text. The patient speaks in their own language, and the care team reads it in theirs.',
  },
  {
    q: 'How does it connect to our EHR?',
    a: 'Through the standard hospital interfaces, HL7 and FHIR. The summary lands in the patient chart as real fields, not a PDF.',
  },
  {
    q: 'Can patients check in by phone?',
    a: 'Yes. The phone agent takes the same story by voice, in the same 20 languages. If anything sounds like an emergency, the caller is told to dial 911 right away and your team is alerted.',
  },
] as const;

// One word of the mega paragraph, opacity-scrubbed over its slice of the
// shared scroll progress. Gradient ink comes from the .text-grad-solace class.
function ScrubWord({
  progress,
  index,
  total,
  reduce,
  word,
}: {
  progress: MotionValue<number>;
  index: number;
  total: number;
  reduce: boolean | null;
  word: string;
}) {
  const start = index / total;
  const opacity = useTransform(progress, [start, start + 1 / total], [0.16, 1]);
  return (
    <motion.span
      className="text-grad-solace"
      style={{ opacity: reduce ? 1 : opacity }}
    >
      {word}{' '}
    </motion.span>
  );
}

// One FAQ row: question button with rotating chevron, height-collapsed answer.
function FaqRow({
  question,
  answer,
  open,
  onToggle,
  reduce,
  buttonId,
  panelId,
}: {
  question: string;
  answer: string;
  open: boolean;
  onToggle: () => void;
  reduce: boolean | null;
  buttonId: string;
  panelId: string;
}) {
  return (
    <div>
      {/* Heading wrapper lets screen-reader users reach questions via
          heading navigation (APG accordion pattern). */}
      <h3 className="contents">
        <button
          type="button"
          id={buttonId}
          aria-expanded={open}
          // The panel unmounts while closed (AnimatePresence), so only point
          // at it while it exists.
          aria-controls={open ? panelId : undefined}
          onClick={onToggle}
          className="flex w-full items-center justify-between gap-6 border-b border-ink/10 py-6 text-left font-sofia text-lg font-medium text-ink"
        >
          {question}
          <ChevronDown
            aria-hidden="true"
            className={`h-5 w-5 shrink-0 text-ink transition-transform duration-[600ms] ease-hims-expo ${
              open ? 'rotate-180' : ''
            }`}
          />
        </button>
      </h3>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="answer"
            id={panelId}
            role="region"
            aria-labelledby={buttonId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={
              reduce
                ? { duration: 0 }
                : { height: himsMove, opacity: himsFade }
            }
            className="overflow-hidden"
          >
            <p className="border-b border-ink/10 py-6 leading-relaxed text-muted">
              {answer}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export default function ClosingShowcase() {
  const bandRef = useRef<HTMLElement>(null);
  const megaRef = useRef<HTMLParagraphElement>(null);
  const reduce = useReducedMotion();
  const faqUid = useId();
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  // The phone-rise choreography only runs ≥lg; below that the band simply
  // stacks.
  const isWide = useIsWide();

  // Phone rises 30vh→0 as the band scrolls into view, pinned to its bottom edge.
  const { scrollYProgress: bandP } = useScroll({
    target: bandRef,
    offset: ['start end', 'end end'],
  });
  const phoneY = useTransform(
    bandP,
    [0, 0.55],
    reduce || !isWide ? ['0vh', '0vh'] : ['30vh', '0vh'],
  );

  // Word-by-word scrub for the mega paragraph.
  const { scrollYProgress: megaP } = useScroll({
    target: megaRef,
    offset: ['start 0.85', 'end 0.5'],
  });

  return (
    <>
      {/* ===== 1 · Showcase band, a clean mint farewell card, inset with even
          margins on the page's white. ===== */}
      <section
        ref={bandRef}
        aria-labelledby="closing-heading"
        className="relative mx-2 min-h-[76vh] overflow-hidden rounded-hims md:mx-4 md:min-h-[90vh] lg:min-h-[120vh]"
        style={{
          backgroundImage:
            'linear-gradient(160deg, #DFF3EC 0%, #BFE5D6 50%, #A0D7C4 100%)',
        }}
      >
        {/* Below lg the phone is position:absolute at the band's bottom, so
            the copy block reserves the phone's visible height (width × the
            1728:2304 rig ratio, minus the 10% bottom tuck) plus a gap, so
            the CTA pills can never collide with the rising bezel. */}
        <div className="relative z-30 flex flex-col items-center px-6 pb-[calc(min(80vw,440px)*1.2+32px)] pt-[12vh] text-center lg:pb-0">
          <motion.h2
            id="closing-heading"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 28 }}
            whileInView={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={REVEAL_TRANSITION}
            className="max-w-[18ch] font-sofia text-[clamp(38px,4.8vw,76px)] font-medium leading-[1.06] tracking-hims text-ink"
          >
            Every patient knows where they stand.
          </motion.h2>
          <motion.p
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 24 }}
            whileInView={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={REVEAL_TRANSITION}
            className="mt-6 max-w-md text-base text-muted md:text-lg"
          >
            A clear priority, an honest wait time and what happens next.
            On their own phone, in their own language.
          </motion.p>
          <motion.div
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 24 }}
            whileInView={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={REVEAL_TRANSITION}
            className="mt-9 flex flex-wrap items-center justify-center gap-3"
          >
            <Link
              to="/demo"
              className="inline-flex items-center justify-center rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
            >
              Book a Demo
            </Link>
            <Link
              to="/demo"
              className="inline-flex items-center justify-center rounded-pill border border-ink/10 bg-white/70 px-7 py-3.5 text-sm font-medium text-ink backdrop-blur transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
            >
              Try the Patient Flow
            </Link>
          </motion.div>
        </div>

        {/* Hand + phone, pinned to the band's bottom edge. The outer div owns
            the static -translate-x-1/2 centering; the inner motion.div owns
            the scroll-linked rise so framer can't clobber the centering. */}
        <div className="absolute bottom-0 left-1/2 z-10 w-[min(80vw,440px)] -translate-x-[53%] translate-y-[10%] lg:w-[clamp(440px,36vw,540px)]">
          <motion.div style={{ y: phoneY, willChange: 'transform' }}>
            {/* Decorative, the band's heading and copy carry the message.
                Shows the explained plan, a different moment from the other
                rigs on the page. */}
            <PhoneRig
              alt=""
              screen={
                <img src={APP_SCREENS.plan} alt="" className="mt-[13.5cqw] h-auto w-full" />
              }
            />
          </motion.div>
        </div>

      </section>

      {/* ===== 2 · Teal-gradient mega paragraph, scrubbed word by word ===== */}
      <section className="bg-white py-[12vh] lg:py-[18vh]">
        <div className="mx-auto max-w-5xl px-6">
          <p
            ref={megaRef}
            className="font-sofia text-[clamp(34px,4.8vw,72px)] font-medium leading-[1.1] tracking-[-0.02em]"
          >
            <span className="sr-only">{MEGA_TEXT}</span>
            <span aria-hidden="true">
              {MEGA_WORDS.map((word, i) => (
                <ScrubWord
                  key={`${word}-${i}`}
                  progress={megaP}
                  index={i}
                  total={MEGA_WORDS.length}
                  reduce={reduce}
                  word={word}
                />
              ))}
            </span>
          </p>
        </div>
      </section>

      {/* ===== 3 · FAQ: left label, right-aligned accordion column ===== */}
      <section
        aria-labelledby="faq-heading"
        className="bg-white pb-[14vh] pt-[6vh]"
        style={{
          // Barely-there mint wash to close the page: starts white against
          // the mega paragraph above, ends on a faint tint by the footer.
          backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)',
        }}
      >
        <div className="mx-auto grid max-w-[1200px] gap-10 px-6 lg:grid-cols-2 lg:gap-6">
          <motion.h2
            id="faq-heading"
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 24 }}
            whileInView={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.5 }}
            transition={REVEAL_TRANSITION}
            className="font-sofia text-[clamp(28px,2.4vw,40px)] font-medium leading-[1.04] tracking-[-0.02em] text-ink"
          >
            Solace FAQs
          </motion.h2>
          <div className="w-full max-w-xl lg:ml-auto">
            {FAQS.map((faq, i) => (
              <FaqRow
                key={faq.q}
                question={faq.q}
                answer={faq.a}
                open={openFaq === i}
                onToggle={() => setOpenFaq((cur) => (cur === i ? null : i))}
                reduce={reduce}
                buttonId={`${faqUid}-faq-q-${i}`}
                panelId={`${faqUid}-faq-a-${i}`}
              />
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
