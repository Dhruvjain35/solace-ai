import { MarketingLayout } from "../../components/marketing/MarketingLayout";
import { HeroCinematic } from "../../components/marketing/landing/HeroCinematic";
import { Marquee } from "../../components/marketing/landing/Marquee";
import { ScribeScene } from "../../components/marketing/landing/ScribeScene";
import { ProductShowcase } from "../../components/marketing/landing/ProductShowcase";
import { Manifesto } from "../../components/marketing/landing/Manifesto";
import { Reveal } from "../../components/marketing/Reveal";
import { StatCounter } from "../../components/marketing/StatCounter";

export default function Landing() {
  return (
    <MarketingLayout>
      <HeroCinematic />
      <Marquee />
      <ScribeScene />
      <ProductShowcase />
      <Manifesto />

      {/* Stats — inset dark slab, webflow-style rounded layer */}
      <section className="bg-surface px-3 pb-24 sm:px-6">
        <Reveal>
          <div className="mx-auto max-w-6xl rounded-[36px] bg-ink px-6 py-16 sm:px-12">
            <div className="grid gap-12 sm:grid-cols-3">
              <StatCounter value={749} label="Automated checks passing on every release" inverse />
              <StatCounter value={4} label="EHR vendors through SMART on FHIR" inverse />
              <StatCounter value={10} prefix="<" suffix="s" label="From conversation to coded draft note" inverse />
            </div>
          </div>
        </Reveal>
      </section>
    </MarketingLayout>
  );
}
