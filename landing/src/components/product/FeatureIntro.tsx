import { motion, useReducedMotion } from 'framer-motion';
import { himsFade, himsMove } from '../../lib/hims';
import ProductWord from './ProductWord';

/*
 * FeatureIntro — the "Everything you need to run a calmer ED." statement that
 * hands off to the tile grid below. The giant centered statement rises in on
 * the house two-curve rule; the "Intake" product word then SLIDES in from the
 * right (ProductWord) to open the intake act. The old floating app-icon card
 * that sat between them was cut — it read as filler, not product.
 */

// The two-curve rule: opacity on HIMS_OUT (~0.2s), transform on HIMS_EXPO (~0.6s).
const rise = { ...himsMove, opacity: himsFade };

export default function FeatureIntro() {
  const reduce = useReducedMotion();

  return (
    <section
      aria-labelledby="feature-intro-heading"
      className="overflow-hidden bg-white"
      style={{
        // Barely-there mint wash (the hims band rhythm): starts white against
        // the statement above, ends on the faint mint TileGrid opens with.
        backgroundImage: 'linear-gradient(180deg, #ffffff 0%, #f2f9f6 100%)',
      }}
    >
      {/* --- Centered statement --- */}
      <motion.h2
        id="feature-intro-heading"
        initial={{ opacity: 0, y: reduce ? 0 : 56 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.5 }}
        transition={rise}
        className="mx-auto max-w-[14ch] px-4 pt-[14vh] text-center font-sofia text-[clamp(48px,7.2vw,110px)] font-medium leading-[1.02] tracking-hims text-ink lg:pt-[20vh]"
      >
        Everything you need to run a calmer ED.
      </motion.h2>

      {/* --- Product word, sliding in to open the intake act --- */}
      <div className="pb-[10vh] pt-[12vh] lg:pb-[16vh] lg:pt-[18vh]">
        <ProductWord
          word="Intake"
          from="right"
          className="text-center text-[clamp(140px,28vw,430px)] text-ink"
        />
      </div>
    </section>
  );
}
