import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import SilkBackground from './ui/SilkBackground';
import Typewriter from './ui/Typewriter';
import { transitions } from '../lib/motion';
import { Arrow } from './ui/Icons';

export default function Hero() {
  return (
    <section className="relative isolate flex min-h-[100svh] flex-col items-center justify-center overflow-hidden bg-ink px-6 text-center">
      {/* Animated green silk backdrop */}
      <div className="absolute inset-0 -z-10">
        <SilkBackground />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/30 via-transparent to-ink" />
      </div>

      <motion.p
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...transitions.slow, delay: 0.1 }}
        className="font-display text-2xl italic text-white/85 md:text-3xl"
      >
        AI-native intake &amp; triage for the emergency department
      </motion.p>

      <motion.h1
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...transitions.slow, delay: 0.2 }}
        className="font-display mt-4 text-[clamp(4rem,16vw,12rem)] leading-[0.86] tracking-tight text-white"
      >
        <Typewriter words={['Intake.', 'Triage.', 'Pre-briefs.', 'Discharge.']} />
      </motion.h1>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...transitions.slow, delay: 0.45 }}
        className="mt-10 flex flex-col items-center gap-3 sm:flex-row"
      >
        <Link
          to="/demo"
          className="inline-flex items-center gap-2 rounded-pill bg-white px-7 py-3.5 text-sm font-medium text-solace-green-900 transition duration-300 ease-standard hover:scale-[1.03]"
        >
          Book a Demo <Arrow className="h-4 w-4" />
        </Link>
        <a
          href="#journey"
          className="inline-flex items-center gap-2 rounded-pill border border-white/25 px-7 py-3.5 text-sm font-medium text-white transition duration-300 ease-standard hover:bg-white/10"
        >
          See how it works
        </a>
      </motion.div>

    </section>
  );
}
