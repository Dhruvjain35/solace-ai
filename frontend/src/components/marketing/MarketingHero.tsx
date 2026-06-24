import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import { LightRays } from "./LightRays";
import { Eyebrow } from "./Eyebrow";
import { Button } from "../ui/Button";

type Cta = { to: string; label: string };

type Props = {
  eyebrow: string;
  title: ReactNode;
  sub: ReactNode;
  primaryCta?: Cta;
  secondaryCta?: Cta;
  children?: ReactNode;
};

/** Standard marketing hero: light-ray field, eyebrow, giant serif headline, CTA pair. */
export function MarketingHero({ eyebrow, title, sub, primaryCta, secondaryCta, children }: Props) {
  const reduced = useReducedMotion();
  const appear = (delay: number) =>
    reduced
      ? {}
      : {
          initial: { opacity: 0, y: 18 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.55, ease: "easeOut" as const, delay },
        };
  return (
    <section className="hero-surface relative overflow-hidden">
      <LightRays />
      <div className="relative mx-auto flex max-w-4xl flex-col items-center gap-6 px-4 pb-20 pt-20 text-center sm:px-6 sm:pt-28">
        <motion.div {...appear(0)}>
          <Eyebrow>{eyebrow}</Eyebrow>
        </motion.div>
        <motion.h1
          {...appear(0.08)}
          className="font-display text-[40px] leading-[1.04] tracking-editorial-tight text-ink sm:text-6xl lg:text-[68px]"
        >
          {title}
        </motion.h1>
        <motion.p {...appear(0.16)} className="max-w-2xl text-base text-text-muted sm:text-lg">
          {sub}
        </motion.p>
        {(primaryCta || secondaryCta) && (
          <motion.div {...appear(0.24)} className="mt-2 flex flex-col gap-3 sm:flex-row">
            {primaryCta && (
              <Link to={primaryCta.to}>
                <Button shape="pill" className="h-12 px-7">
                  {primaryCta.label} <ArrowRight size={16} aria-hidden="true" />
                </Button>
              </Link>
            )}
            {secondaryCta && (
              <Link to={secondaryCta.to}>
                <Button variant="secondary" shape="pill" className="h-12 px-7">
                  {secondaryCta.label}
                </Button>
              </Link>
            )}
          </motion.div>
        )}
        {children && (
          <motion.div {...appear(0.34)} className="mt-6 w-full">
            {children}
          </motion.div>
        )}
      </div>
    </section>
  );
}
