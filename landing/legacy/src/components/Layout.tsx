import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import Nav from './Nav';
import Footer from './Footer';
import { applyMeta } from '../lib/seo';

export default function Layout() {
  const { pathname, hash } = useLocation();

  // Update the page's title/description/social tags on every route change.
  useEffect(() => {
    applyMeta(pathname);
  }, [pathname]);

  // Scroll behavior: if the route carries a hash (e.g. a product link to
  // /clinicians#atlas-heading), scroll that section into view once it has
  // mounted; otherwise jump to the top. We retry briefly because the target
  // section can still be mounting after a cross-page navigation.
  useEffect(() => {
    if (hash) {
      const id = decodeURIComponent(hash.slice(1));
      let tries = 0;
      const find = () => {
        const el = document.getElementById(id);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          return;
        }
        if (tries++ < 8) setTimeout(find, 80);
      };
      find();
      return;
    }
    window.scrollTo(0, 0);
  }, [pathname, hash]);

  return (
    <>
      <Nav />
      {/*
       * The new page mounts immediately on navigation with a quick opacity-only
       * fade. We intentionally do NOT use AnimatePresence mode="wait" or a
       * y-translate exit here, that made every route change wait ~0.6s for the
       * old page to animate out before the new one appeared, which read as a
       * slow reload (the integrations "back" complaint). Instant + a soft fade.
       */}
      <motion.main
        key={pathname}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.18, ease: [0.215, 0.61, 0.355, 1] }}
      >
        <Outlet />
      </motion.main>
      <Footer />
    </>
  );
}
