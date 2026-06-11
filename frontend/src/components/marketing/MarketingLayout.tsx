import { ReactNode, useEffect } from "react";
import { useLocation } from "react-router-dom";
import { MarketingNav } from "./MarketingNav";
import { MarketingFooter } from "./MarketingFooter";

/** Shared shell for every marketing page: nav + content + CTA/footer. */
export function MarketingLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  // Marketing pages are long; always start at the top on navigation.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="min-h-[100dvh] bg-surface font-sans text-ink">
      <MarketingNav />
      <main>{children}</main>
      <MarketingFooter />
    </div>
  );
}
