import { PointerEvent, useRef } from "react";
import { Link } from "react-router-dom";
import { motion, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "framer-motion";
import { ArrowUpRight, AudioLines, Activity, Sparkles } from "lucide-react";
import { SectionHeading } from "../SectionHeading";

const products = [
  {
    to: "/scribe",
    Icon: AudioLines,
    title: "AI Scribe",
    tag: "Documentation",
    desc: "Ambient notes in your format, coded and signable in seconds.",
    glow: "rgba(59,94,103,0.35)",
  },
  {
    to: "/triage",
    Icon: Activity,
    title: "Smart Triage",
    tag: "Front door",
    desc: "QR check-in to explainable ESI before the patient reaches the desk.",
    glow: "rgba(64,99,114,0.35)",
  },
  {
    to: "/copilot",
    Icon: Sparkles,
    title: "EHR Copilot",
    tag: "Agentic",
    desc: "Reads the chart, drafts the orders, waits for your confirm.",
    glow: "rgba(85,125,110,0.35)",
  },
];

// Pointer-tracked 3D tilt card with a moving glow hotspot.
function TiltCard({ p, i }: { p: (typeof products)[number]; i: number }) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLAnchorElement>(null);
  const rx = useMotionValue(0);
  const ry = useMotionValue(0);
  const gx = useMotionValue(50);
  const gy = useMotionValue(40);
  const srx = useSpring(rx, { stiffness: 180, damping: 18 });
  const sry = useSpring(ry, { stiffness: 180, damping: 18 });

  const onMove = (e: PointerEvent<HTMLAnchorElement>) => {
    if (reduced || e.pointerType === "touch" || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    ry.set((px - 0.5) * 10);
    rx.set((0.5 - py) * 8);
    gx.set(px * 100);
    gy.set(py * 100);
  };
  const onLeave = () => {
    rx.set(0);
    ry.set(0);
  };

  const glow = useTransform([gx, gy], ([x, y]) => `radial-gradient(360px circle at ${x}% ${y}%, ${p.glow}, transparent 65%)`);

  return (
    <motion.div
      initial={reduced ? false : { opacity: 0, y: 48 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.65, ease: [0.16, 1, 0.3, 1], delay: i * 0.1 }}
      style={{ perspective: 900 }}
    >
      <motion.div style={{ rotateX: srx, rotateY: sry, transformStyle: "preserve-3d" }}>
        <Link
          ref={ref}
          to={p.to}
          onPointerMove={onMove}
          onPointerLeave={onLeave}
          className="group relative block h-full overflow-hidden rounded-[28px] bg-surface-lowest p-8 shadow-card ring-1 ring-line transition-shadow duration-300 hover:shadow-lifted"
        >
          <motion.span aria-hidden="true" className="absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100" style={{ background: glow }} />
          <span className="relative z-10 flex items-start justify-between">
            <span className="inline-flex rounded-2xl bg-primary-dim/60 p-3 text-primary">
              <p.Icon size={22} aria-hidden="true" />
            </span>
            <span className="flex h-9 w-9 items-center justify-center rounded-full ring-1 ring-line transition-all duration-300 group-hover:bg-primary group-hover:text-white group-hover:ring-primary">
              <ArrowUpRight size={16} aria-hidden="true" />
            </span>
          </span>
          <span className="relative z-10 mt-16 block">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">{p.tag}</span>
            <span className="mt-1.5 block font-display text-3xl tracking-editorial text-ink">{p.title}</span>
            <span className="mt-2.5 block text-sm leading-relaxed text-text-muted">{p.desc}</span>
          </span>
        </Link>
      </motion.div>
    </motion.div>
  );
}

export function ProductShowcase() {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  // Gentle vertical parallax: middle card lags behind its neighbors.
  const y1 = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : -36]);
  const y2 = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : 28]);
  const ys = [y1, y2, y1];

  return (
    <section ref={ref} className="relative bg-surface">
      <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6 sm:py-32">
        <SectionHeading
          eyebrow="The platform"
          title={<>One platform. Three co-pilots.</>}
          sub="Each one earns its place in the workflow — together they give the day back."
        />
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {products.map((p, i) => (
            <motion.div key={p.to} style={{ y: ys[i] }}>
              <TiltCard p={p} i={i} />
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
