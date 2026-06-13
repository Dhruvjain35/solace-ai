import { useEffect, useRef, useState, type MouseEvent } from 'react';
import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from 'framer-motion';
import { Link, useLocation } from 'react-router-dom';
import ExpandingLogo from './ui/ExpandingLogo';
import { transitions } from '../lib/motion';

const LINKS = [
  { label: 'How it Works', to: '/how-it-works' },
  { label: 'For Clinicians', to: '/clinicians' },
  { label: 'Company', to: '/company' },
  { label: 'Pricing', to: '/pricing' },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [open, setOpen] = useState(false);
  const [logoHover, setLogoHover] = useState(false);
  const [logoIntro, setLogoIntro] = useState(true);
  const lastY = useRef(0);
  const reduce = useReducedMotion();
  useLocation(); // keep router context subscription for active states below

  // First-load intro: the wordmark unfurls once, holds, then settles back to
  // the standalone "S". After that it's hover-driven.
  useEffect(() => {
    const t = setTimeout(() => setLogoIntro(false), 2000);
    return () => clearTimeout(t);
  }, []);

  // Pointer-tracked glow on the logo: a soft mint light that follows the cursor
  // (spring-smoothed) and fades in/out — interactive, not a static blob.
  const gx = useMotionValue(50);
  const gy = useMotionValue(50);
  const sgx = useSpring(gx, { stiffness: 140, damping: 18, mass: 0.4 });
  const sgy = useSpring(gy, { stiffness: 140, damping: 18, mass: 0.4 });
  const glowOpacity = useSpring(0, { stiffness: 180, damping: 26 });
  const glowBg = useMotionTemplate`radial-gradient(60% 130% at ${sgx}% ${sgy}%, rgba(31,191,143,0.22), rgba(31,191,143,0.06) 52%, rgba(31,191,143,0) 78%)`;

  const onLogoEnter = () => {
    setLogoHover(true);
    glowOpacity.set(1);
  };
  const onLogoLeave = () => {
    setLogoHover(false);
    glowOpacity.set(0);
  };
  const onLogoMove = (e: MouseEvent<HTMLAnchorElement>) => {
    if (reduce) return;
    const r = e.currentTarget.getBoundingClientRect();
    gx.set(((e.clientX - r.left) / r.width) * 100);
    gy.set(((e.clientY - r.top) / r.height) * 100);
  };
  // Every page now opens on a light stage (the old dark home hero is gone),
  // so the glass-light nav variant is never needed.
  const onDarkHero = false;

  // Hide the pill while scrolling down (so mega type passes under a clear
  // stage, like the reference's corner-only chrome) and bring it back the
  // moment the user scrolls up.
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      setScrolled(y > 40);
      setHidden(y > lastY.current && y > 240);
      lastY.current = y;
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Over the dark hero (home, not scrolled) -> light text on a glass pill.
  const light = onDarkHero && !scrolled;

  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={hidden && !open ? { y: -90, opacity: 0 } : { y: 0, opacity: 1 }}
      transition={transitions.slow}
      className="fixed inset-x-0 top-4 z-50 flex justify-center px-4"
    >
      <nav
        className={`flex items-center gap-2 rounded-pill border px-2.5 py-2 backdrop-blur-xl transition-colors duration-300 ease-standard ${
          light
            ? 'border-white/15 bg-white/10 text-white'
            : 'border-solace-soft bg-white/85 text-ink shadow-card'
        }`}
      >
        <Link
          to="/"
          aria-label="Solace home"
          onMouseEnter={onLogoEnter}
          onMouseLeave={onLogoLeave}
          onMouseMove={onLogoMove}
          className="relative flex items-center rounded-pill px-3.5 py-2 transition-transform duration-[600ms] ease-hims-expo hover:scale-[1.03]"
        >
          {/* Cursor-tracked mint glow — interactive, spring-smoothed, logo only. */}
          <motion.span
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 rounded-pill"
            style={{ background: glowBg, opacity: glowOpacity }}
          />
          <span className="relative">
            <ExpandingLogo expanded={logoHover || logoIntro} reduce={reduce} light={light} />
          </span>
        </Link>

        <div className="hidden items-center md:flex">
          {LINKS.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className={`rounded-pill px-4 py-2 text-sm transition-colors ${
                light ? 'text-white/80 hover:text-white' : 'text-muted hover:text-ink'
              }`}
            >
              {l.label}
            </Link>
          ))}
        </div>

        <span className={`mx-1 hidden h-5 w-px md:block ${light ? 'bg-white/20' : 'bg-solace-soft'}`} />

        <Link
          to="/demo"
          className={`hidden rounded-pill px-5 py-2 text-sm font-medium transition md:inline-flex ${
            light
              ? 'bg-white text-solace-green-900 hover:bg-white/90'
              : 'bg-gradient-to-br from-solace-green-700 to-solace-mint text-white'
          }`}
        >
          Book a Demo
        </Link>

        <button
          className="flex h-11 w-11 items-center justify-center md:hidden"
          aria-label="Menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <div className="space-y-1.5">
            <span className={`block h-0.5 w-5 ${light ? 'bg-white' : 'bg-ink'}`} />
            <span className={`block h-0.5 w-5 ${light ? 'bg-white' : 'bg-ink'}`} />
          </div>
        </button>
      </nav>

      {open && (
        <div className="absolute left-4 right-4 top-full mt-2 rounded-3xl border border-solace-soft bg-white p-4 shadow-lift md:hidden">
          {LINKS.map((l) => (
            <Link key={l.to} to={l.to} onClick={() => setOpen(false)} className="block py-3 text-sm text-muted">
              {l.label}
            </Link>
          ))}
          <Link to="/demo" onClick={() => setOpen(false)} className="btn-primary mt-2 w-full">
            Book a Demo
          </Link>
        </div>
      )}
    </motion.header>
  );
}
