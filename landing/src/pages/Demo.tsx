import { useId, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Check } from 'lucide-react';
import { himsFade, himsMove } from '../lib/hims';

/*
 * Demo — the booking page, rebuilt in the light house style of the Product
 * page (app.forhims.com clone). White stage under the floating pill nav,
 * ink Sofia display type, paper form card with pill inputs. Everything
 * animates on mount with the two-curve reveal (opacity on HIMS_OUT,
 * transform on HIMS_EXPO) since the whole page sits above the fold.
 */

const REASSURANCES = [
  'Nothing to install, nothing to integrate for the demo',
  'HIPAA-grade from the first call',
  'See the live queue and the patient snapshot working',
] as const;

const FIELDS = [
  { label: 'Full name', type: 'text', placeholder: 'Dr. Jordan Lee', autoComplete: 'name' },
  { label: 'Work email', type: 'email', placeholder: 'you@hospital.org', autoComplete: 'email' },
  { label: 'Organization', type: 'text', placeholder: 'North Texas ED', autoComplete: 'organization' },
] as const;

const INPUT_CLASS =
  'mt-2 w-full rounded-pill border border-black/10 bg-white px-5 py-3.5 text-base text-ink placeholder:text-muted/60 outline-none transition-colors duration-200 focus:border-solace-green-500';

// House mount reveal: opacity rides HIMS_OUT (0.2s), y rides HIMS_EXPO
// (0.6s), siblings stagger 0.04s apart on both curves.
function reveal(reduce: boolean | null, i: number) {
  return {
    initial: { opacity: 0, y: reduce ? 0 : 28 },
    animate: { opacity: 1, y: 0 },
    transition: {
      opacity: { ...himsFade, delay: i * 0.04 },
      y: { ...himsMove, delay: i * 0.04 },
    },
  } as const;
}

export default function Demo() {
  const [sent, setSent] = useState(false);
  const reduce = useReducedMotion();
  const uid = useId();

  return (
    <section
      aria-labelledby="demo-heading"
      className="min-h-[100svh] bg-white px-6 pb-24 pt-36 md:pt-40"
      style={{
        // Barely-there mint wash, the hims band look: white at the top under
        // the nav, a faint tint under the form card by the fold.
        backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)',
      }}
    >
      <div className="mx-auto grid max-w-[1100px] items-center gap-12 lg:grid-cols-2 lg:gap-16">
        {/* ===== Left — headline, sub, reassurance rows ===== */}
        <div>
          <motion.h1
            id="demo-heading"
            {...reveal(reduce, 0)}
            className="max-w-[12ch] font-sofia text-[clamp(44px,6.2vw,84px)] font-medium leading-[1.02] tracking-hims text-ink"
          >
            See Solace on your floor.
          </motion.h1>
          <motion.p
            {...reveal(reduce, 1)}
            className="mt-6 max-w-md text-base text-muted md:text-lg"
          >
            A live walkthrough on a workflow that looks like yours,
            in about 20 minutes.
          </motion.p>
          <ul className="mt-9 space-y-3.5">
            {REASSURANCES.map((line, i) => (
              <motion.li
                key={line}
                {...reveal(reduce, 2 + i)}
                className="flex items-start gap-3 text-[15px] text-ink"
              >
                <Check
                  size={18}
                  strokeWidth={1.75}
                  aria-hidden="true"
                  className="mt-0.5 shrink-0 text-ink"
                />
                {line}
              </motion.li>
            ))}
          </ul>
        </div>

        {/* ===== Right — paper form card ===== */}
        <motion.div
          {...reveal(reduce, 3)}
          className="rounded-hims bg-paper p-8 ring-1 ring-black/5 md:p-10"
        >
          {sent ? (
            <div className="flex min-h-[340px] flex-col items-center justify-center text-center">
              <Check
                size={32}
                strokeWidth={1.75}
                aria-hidden="true"
                className="text-ink"
              />
              <p className="mt-5 font-sofia text-2xl font-medium tracking-[-0.02em] text-ink">
                Thanks.
              </p>
              <p className="mt-2 max-w-xs text-[15px] text-muted">
                We will reach out within one business day.
              </p>
            </div>
          ) : (
            <form
              className="space-y-5"
              onSubmit={(e) => {
                e.preventDefault();
                setSent(true);
              }}
            >
              {FIELDS.map((f) => (
                <div key={f.label}>
                  <label
                    htmlFor={`${uid}-${f.autoComplete}`}
                    className="text-sm font-medium text-ink"
                  >
                    {f.label}
                  </label>
                  <input
                    id={`${uid}-${f.autoComplete}`}
                    required
                    type={f.type}
                    placeholder={f.placeholder}
                    autoComplete={f.autoComplete}
                    className={INPUT_CLASS}
                  />
                </div>
              ))}
              <button
                type="submit"
                className="w-full rounded-pill bg-ink px-7 py-3.5 text-sm font-medium text-white transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
              >
                Book a Demo
              </button>
            </form>
          )}
        </motion.div>
      </div>

      {/* ===== Quiet hand-off to the live patient flow ===== */}
      <motion.p
        {...reveal(reduce, 4)}
        className="mt-14 text-center text-sm text-muted"
      >
        or{' '}
        <a
          href="https://solaceaidemo.vercel.app"
          target="_blank"
          rel="noreferrer"
          className="font-medium text-ink underline underline-offset-4 decoration-ink/30 transition-colors duration-200 hover:decoration-ink"
        >
          try the patient flow yourself
        </a>
      </motion.p>
    </section>
  );
}
