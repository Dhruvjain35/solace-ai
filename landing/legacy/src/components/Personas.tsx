import { motion } from 'framer-motion';
import { reveal, stagger, slideUp } from '../lib/motion';

const PEOPLE = [
  {
    role: 'Emergency physicians',
    line: 'Walk into the room already informed',
    img: 'https://images.unsplash.com/photo-1622253692010-333f2da6031d?auto=format&fit=crop&w=800&q=80',
  },
  {
    role: 'Triage nurses',
    line: 'Less re-asking, more nursing',
    img: 'https://images.unsplash.com/photo-1576091160550-2173dba999ef?auto=format&fit=crop&w=800&q=80',
  },
  {
    role: 'Patients with limited English',
    line: 'Heard in their own language',
    img: 'https://images.unsplash.com/photo-1505751172876-fa1923c5c528?auto=format&fit=crop&w=800&q=80',
  },
];

export default function Personas() {
  return (
    <section className="bg-white px-6 py-24 md:py-32">
      <div className="mx-auto max-w-[1200px]">
        <motion.div {...reveal} className="mx-auto max-w-2xl text-center">
          <span className="text-sm font-medium text-solace-green-600">Who it’s for</span>
          <h2 className="font-display mt-3 text-4xl leading-[1.05] tracking-tight text-ink md:text-6xl">
            Built for everyone at the front door
          </h2>
        </motion.div>

        <motion.div variants={stagger} {...reveal} className="mt-14 grid gap-6 md:grid-cols-3">
          {PEOPLE.map((p) => (
            <motion.div key={p.role} variants={slideUp} className="group">
              <div className="relative aspect-[4/3] overflow-hidden rounded-3xl bg-gradient-to-br from-solace-green-700 to-solace-mint">
                <img
                  src={p.img}
                  alt={p.role}
                  className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                  loading="lazy"
                  onError={(e) => (e.currentTarget.style.display = 'none')}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-ink/60 to-transparent" />
              </div>
              <h3 className="mt-5 text-xl font-semibold text-ink">{p.role}</h3>
              <p className="mt-1 text-muted">{p.line}</p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
