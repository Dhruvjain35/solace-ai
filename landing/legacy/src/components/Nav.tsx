import { useEffect, useRef, useState, type MouseEvent } from 'react';
import {
  AnimatePresence,
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from 'framer-motion';
import { Link, useLocation } from 'react-router-dom';
import ExpandingLogo from './ui/ExpandingLogo';
import { transitions } from '../lib/motion';

// The four shipping products. The first three carry a trademark; Atlas, the
// clinician copilot, is the workspace they all live inside. Each points at the
// section of the site where that product is actually shown.
const PRODUCTS = [
  {
    name: 'Solace Smart Patient Intake',
    tm: true,
    to: '/how-it-works#patient-side-heading',
    desc: 'Multilingual voice intake from a QR code',
  },
  {
    name: 'Solace Triage',
    tm: true,
    to: '/#triage-heading',
    desc: 'Explainable ESI acuity pre-brief',
  },
  {
    name: 'Solace Ambient Scribe',
    tm: true,
    to: '/clinicians#queue-heading',
    desc: 'Ambient SOAP notes, drafted as you work',
  },
  {
    name: 'Solace Atlas',
    tm: false,
    to: '/clinicians#atlas-heading',
    desc: 'The EHR copilot at the bedside',
  },
];

const LINKS = [
  { label: 'How it Works', to: '/how-it-works' },
  { label: 'For Clinicians', to: '/clinicians' },
  { label: 'Integrations', to: '/integrations' },
  { label: 'Pricing', to: '/pricing' },
];

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [open, setOpen] = useState(false);
  const [productsOpen, setProductsOpen] = useState(false);
  const [mobileProductsOpen, setMobileProductsOpen] = useState(false);
  const [logoHover, setLogoHover] = useState(false);
  const [logoIntro, setLogoIntro] = useState(true);
  const lastY = useRef(0);
  const closeTimer = useRef<ReturnType<typeof setTimeout>>();
  const reduce = useReducedMotion();
  useLocation(); // keep router context subscription for active states below

  // First-load intro: the wordmark unfurls once, holds, then settles back to
  // the standalone "S". After that it's hover-driven.
  useEffect(() => {
    const t = setTimeout(() => setLogoIntro(false), 2000);
    return () => clearTimeout(t);
  }, []);

  // Pointer-tracked glow on the logo: a soft mint light that follows the cursor
  // (spring-smoothed) and fades in/out, interactive, not a static blob.
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

  // Hover intent on the products menu: open instantly, close on a short delay
  // so a quick diagonal move into the panel doesn't dismiss it.
  const openProducts = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setProductsOpen(true);
  };
  const closeProducts = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setProductsOpen(false), 120);
  };

  const closeAllMobile = () => {
    setOpen(false);
    setMobileProductsOpen(false);
  };

  const linkTone = light ? 'text-white/80 hover:text-white' : 'text-muted hover:text-ink';

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
          {/* Cursor-tracked mint glow, interactive, spring-smoothed, logo only. */}
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
          {/* Our Products: hover-revealed dropdown of the four named products. */}
          <div className="relative" onMouseEnter={openProducts} onMouseLeave={closeProducts}>
            <button
              type="button"
              aria-haspopup="true"
              aria-expanded={productsOpen}
              onClick={() => setProductsOpen((v) => !v)}
              className={`flex items-center gap-1 rounded-pill px-4 py-2 text-sm transition-colors ${linkTone}`}
            >
              Our Products
              <motion.svg
                width="11"
                height="11"
                viewBox="0 0 12 12"
                fill="none"
                aria-hidden="true"
                animate={{ rotate: productsOpen ? 180 : 0 }}
                transition={{ duration: 0.25, ease: [0.215, 0.61, 0.355, 1] }}
                className="mt-px opacity-70"
              >
                <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </motion.svg>
            </button>

            <AnimatePresence>
              {productsOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 8, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 6, scale: 0.98 }}
                  transition={{ duration: 0.2, ease: [0.215, 0.61, 0.355, 1] }}
                  className="absolute left-0 top-full z-50 w-[332px] pt-3"
                >
                  <div className="overflow-hidden rounded-tile border border-solace-soft bg-white p-2 shadow-lift">
                    {PRODUCTS.map((p) => (
                      <Link
                        key={p.name}
                        to={p.to}
                        onClick={() => setProductsOpen(false)}
                        className="group block rounded-2xl px-3.5 py-3 transition-colors hover:bg-solace-soft/60"
                      >
                        <span className="block font-sofia text-[15px] font-semibold tracking-hims text-ink">
                          {p.name}
                          {p.tm && <sup className="ml-0.5 text-[9px] font-medium text-muted">TM</sup>}
                        </span>
                        <span className="mt-0.5 block text-[12.5px] leading-snug text-muted">
                          {p.desc}
                        </span>
                      </Link>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {LINKS.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className={`rounded-pill px-4 py-2 text-sm transition-colors ${linkTone}`}
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
          className="flex h-12 w-12 items-center justify-center md:hidden"
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
          {/* Mobile: Our Products is a collapsible group at the top. */}
          <button
            type="button"
            aria-expanded={mobileProductsOpen}
            onClick={() => setMobileProductsOpen((v) => !v)}
            className="flex w-full items-center justify-between py-3 text-sm font-medium text-ink"
          >
            Our Products
            <motion.svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
              animate={{ rotate: mobileProductsOpen ? 180 : 0 }}
              transition={{ duration: 0.25, ease: [0.215, 0.61, 0.355, 1] }}
              className="opacity-60"
            >
              <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </motion.svg>
          </button>
          <AnimatePresence initial={false}>
            {mobileProductsOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.28, ease: [0.215, 0.61, 0.355, 1] }}
                className="overflow-hidden"
              >
                <div className="ml-1 border-l border-solace-soft pl-3 pb-1">
                  {PRODUCTS.map((p) => (
                    <Link
                      key={p.name}
                      to={p.to}
                      onClick={closeAllMobile}
                      className="block py-2.5 text-sm text-muted"
                    >
                      {p.name}
                      {p.tm && <sup className="ml-0.5 text-[8px] text-muted/70">TM</sup>}
                    </Link>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="my-1 h-px bg-solace-soft" />

          {LINKS.map((l) => (
            <Link key={l.to} to={l.to} onClick={closeAllMobile} className="block py-3 text-sm text-muted">
              {l.label}
            </Link>
          ))}
          <Link to="/demo" onClick={closeAllMobile} className="btn-primary mt-2 w-full">
            Book a Demo
          </Link>
        </div>
      )}
    </motion.header>
  );
}
