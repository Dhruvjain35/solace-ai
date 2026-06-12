import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import SilkBackground from './ui/SilkBackground';
import { reveal } from '../lib/motion';
import { ArrowRight } from 'lucide-react';

export default function CTABand() {
  return (
    <section id="demo-cta" className="relative isolate overflow-hidden bg-ink px-6 py-28 text-center md:py-40">
      <div className="absolute inset-0 -z-10 opacity-80">
        <SilkBackground />
        <div className="absolute inset-0 bg-gradient-to-b from-ink via-transparent to-ink" />
      </div>
      <motion.h2
        {...reveal}
        className="font-display mx-auto max-w-3xl text-4xl leading-[1.05] tracking-tight text-white md:text-6xl"
      >
        Empowering emergency departments through AI
      </motion.h2>
      <motion.div {...reveal} className="mt-9 flex justify-center">
        <Link
          to="/demo"
          className="inline-flex items-center gap-2 rounded-pill bg-white px-8 py-4 text-sm font-semibold text-solace-green-900 transition duration-300 ease-standard hover:scale-[1.03]"
        >
          Book a Demo <ArrowRight className="h-4 w-4" />
        </Link>
      </motion.div>
    </section>
  );
}
