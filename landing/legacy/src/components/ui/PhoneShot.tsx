import { useRef } from 'react';
import { motion, useScroll, useTransform, useReducedMotion } from 'framer-motion';

// A large transparent iPhone cutout over a living radial glow. Combines a 3D
// entrance, a continuous float, a pulsing glow, and a scroll-linked parallax so
// the device drifts as the section moves through the viewport.
export default function PhoneShot({
  src,
  alt,
  className = '',
  flip = false,
}: {
  src: string;
  alt: string;
  className?: string;
  flip?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end start'] });
  const y = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [70, -70]);
  const rotate = useTransform(scrollYProgress, [0, 1], reduce ? [0, 0] : [flip ? 4 : -4, flip ? -3 : 3]);

  return (
    <div ref={ref} className={`relative flex items-center justify-center ${className}`}>
      {/* pulsing radial glow */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 h-[85%] w-[90%] -translate-x-1/2 -translate-y-1/2 rounded-blob blur-3xl"
        style={{
          background:
            'radial-gradient(circle at 50% 45%, rgba(31,191,143,0.55), rgba(11,107,83,0.28) 45%, rgba(11,107,83,0) 72%)',
        }}
        animate={reduce ? undefined : { scale: [1, 1.08, 1], opacity: [0.75, 1, 0.75] }}
        transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        style={{ y, rotate, perspective: 1200 }}
        initial={{ opacity: 0, y: 80, rotateX: 18, scale: 0.92 }}
        whileInView={{ opacity: 1, y: 0, rotateX: 0, scale: 1 }}
        viewport={{ once: true, amount: 0.3 }}
        transition={{ duration: 0.9, ease: [0.25, 1, 0.5, 1] }}
        className="relative"
      >
        <motion.img
          src={src}
          alt={alt}
          loading="lazy"
          className="relative w-[300px] drop-shadow-[0_40px_80px_rgba(6,59,46,0.45)] md:w-[380px]"
          animate={reduce ? undefined : { y: [0, -14, 0] }}
          transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
        />
      </motion.div>
    </div>
  );
}
