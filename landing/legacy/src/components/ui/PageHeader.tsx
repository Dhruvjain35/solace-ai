import { motion } from 'framer-motion';
import SilkBackground from './SilkBackground';
import { transitions } from '../../lib/motion';

export default function PageHeader({
  eyebrow,
  title,
  blurb,
}: {
  eyebrow: string;
  title: React.ReactNode;
  blurb: string;
}) {
  return (
    <section className="relative isolate overflow-hidden bg-ink px-6 pt-40 pb-24 text-center md:pt-48 md:pb-32">
      <div className="absolute inset-0 -z-10">
        <SilkBackground />
        <div className="absolute inset-0 bg-gradient-to-b from-ink/40 via-transparent to-ink" />
      </div>
      <motion.p
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={transitions.base}
        className="text-xs font-medium uppercase tracking-[0.2em] text-solace-mint"
      >
        {eyebrow}
      </motion.p>
      <motion.h1
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...transitions.slow, delay: 0.1 }}
        className="font-display mx-auto mt-4 max-w-4xl text-5xl leading-[0.95] tracking-tight text-white md:text-7xl"
      >
        {title}
      </motion.h1>
      <motion.p
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...transitions.slow, delay: 0.2 }}
        className="mx-auto mt-6 max-w-2xl text-lg text-white/65"
      >
        {blurb}
      </motion.p>
    </section>
  );
}
