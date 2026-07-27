import { motion } from 'framer-motion';
import SilkBackground from './ui/SilkBackground';
import { reveal } from '../lib/motion';

export default function DigitalWorkers() {
  return (
    <section className="relative isolate overflow-hidden bg-ink px-6 py-28 md:py-40">
      <div className="absolute inset-0 -z-10 opacity-70">
        <SilkBackground />
        <div className="absolute inset-0 bg-gradient-to-b from-ink via-transparent to-ink" />
      </div>
      <motion.h2
        {...reveal}
        className="font-display mx-auto max-w-4xl text-center text-4xl leading-[1.05] tracking-tight text-white md:text-6xl"
      >
        Digital workers for the front of your
        <br className="hidden md:block" /> emergency department.
      </motion.h2>
    </section>
  );
}
