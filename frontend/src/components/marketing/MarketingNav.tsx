import { useEffect, useRef, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Menu, X, AudioLines, Activity, Sparkles } from "lucide-react";
import { Button } from "../ui/Button";

const products = [
  { to: "/scribe", label: "AI Scribe", desc: "Notes that write themselves", Icon: AudioLines },
  { to: "/triage", label: "Smart Triage", desc: "ESI triage from the first hello", Icon: Activity },
  { to: "/copilot", label: "EHR Copilot", desc: "Drafts orders. You confirm.", Icon: Sparkles },
];

const links = [
  { to: "/integrations", label: "Integrations" },
  { to: "/security", label: "Security" },
  { to: "/about", label: "About" },
  { to: "/contact", label: "Contact" },
];

/** Sticky marketing nav with a Products dropdown and mobile sheet. */
export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [productsOpen, setProductsOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const openProducts = () => {
    window.clearTimeout(closeTimer.current);
    setProductsOpen(true);
  };
  const scheduleClose = () => {
    closeTimer.current = window.setTimeout(() => setProductsOpen(false), 120);
  };

  return (
    <header
      className={`sticky top-0 z-40 transition-all ${
        scrolled ? "bg-surface/85 shadow-soft backdrop-blur-md" : "bg-transparent"
      }`}
    >
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6" aria-label="Main">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Solace home">
          <img src="/solace-logo.png" alt="" className="h-8 w-8 rounded-md object-contain" />
          <span className="font-display text-xl tracking-editorial text-ink">Solace</span>
        </Link>

        {/* Desktop links */}
        <div className="hidden items-center gap-1 lg:flex">
          <div className="relative" onMouseEnter={openProducts} onMouseLeave={scheduleClose}>
            <button
              type="button"
              aria-expanded={productsOpen}
              onClick={() => setProductsOpen((v) => !v)}
              className="flex items-center gap-1 rounded-md px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low"
            >
              Products <ChevronDown size={14} aria-hidden="true" />
            </button>
            <AnimatePresence>
              {productsOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 6 }}
                  transition={{ duration: 0.15 }}
                  className="absolute left-0 top-full mt-2 w-72 rounded-xl bg-surface-lowest p-2 shadow-lifted ring-1 ring-line"
                >
                  {products.map(({ to, label, desc, Icon }) => (
                    <Link
                      key={to}
                      to={to}
                      onClick={() => setProductsOpen(false)}
                      className="flex items-start gap-3 rounded-lg px-3 py-2.5 hover:bg-surface-low"
                    >
                      <span className="mt-0.5 rounded-md bg-primary-dim/60 p-1.5 text-primary">
                        <Icon size={15} aria-hidden="true" />
                      </span>
                      <span>
                        <span className="block text-sm font-medium text-ink">{label}</span>
                        <span className="block text-xs text-text-muted">{desc}</span>
                      </span>
                    </Link>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          {links.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm font-medium hover:bg-surface-low ${
                  isActive ? "text-primary" : "text-ink"
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>

        <div className="hidden items-center gap-2 lg:flex">
          <Link to="/clinicians" className="rounded-md px-3 py-2 text-sm font-medium text-ink hover:bg-surface-low">
            Sign in
          </Link>
          <Link to="/get-started">
            <Button shape="pill" className="h-10 px-5 text-sm">
              Get started
            </Button>
          </Link>
        </div>

        {/* Mobile toggle */}
        <button
          type="button"
          className="rounded-md p-2 text-ink hover:bg-surface-low lg:hidden"
          aria-expanded={mobileOpen}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </nav>

      {/* Mobile sheet */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-line bg-surface-lowest lg:hidden"
          >
            <div className="space-y-1 px-4 py-4">
              <p className="px-3 pb-1 font-mono text-[11px] uppercase tracking-[0.12em] text-text-muted">Products</p>
              {products.map(({ to, label }) => (
                <Link
                  key={to}
                  to={to}
                  onClick={() => setMobileOpen(false)}
                  className="block rounded-md px-3 py-2.5 text-sm font-medium text-ink hover:bg-surface-low"
                >
                  {label}
                </Link>
              ))}
              <div className="my-2 border-t border-line" />
              {links.map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  onClick={() => setMobileOpen(false)}
                  className="block rounded-md px-3 py-2.5 text-sm font-medium text-ink hover:bg-surface-low"
                >
                  {l.label}
                </Link>
              ))}
              <div className="flex gap-2 pt-3">
                <Link to="/clinicians" className="flex-1" onClick={() => setMobileOpen(false)}>
                  <Button variant="secondary" shape="pill" fullWidth className="h-11 text-sm">
                    Sign in
                  </Button>
                </Link>
                <Link to="/get-started" className="flex-1" onClick={() => setMobileOpen(false)}>
                  <Button shape="pill" fullWidth className="h-11 text-sm">
                    Get started
                  </Button>
                </Link>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
