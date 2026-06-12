import AppHero from '../components/product/AppHero';
import BigStatement from '../components/product/BigStatement';
import FeatureIntro from '../components/product/FeatureIntro';
import TileGrid from '../components/product/TileGrid';
import SideBySide from '../components/product/SideBySide';
import DarkTriage from '../components/product/DarkTriage';
import ClosingShowcase from '../components/product/ClosingShowcase';

// The Product page is a structural clone of app.forhims.com (see
// design-extract-output/app-forhims-com-*), remapped onto the Solace brand.
// Scene order mirrors the reference: hero → statement → feature intro →
// tile wall → side-by-side phone → statement → dark act → closing.
export default function Product() {
  return (
    <div className="bg-white">
      <AppHero />
      <BigStatement
        className="text-solace-green-600"
        text={
          'Check in by voice in 20 languages. Your story reaches the care team before you reach a bed. Wait times that tell the truth. And an emergency room that finally breathes.\nAll in the app.'
        }
      />
      <FeatureIntro />
      <TileGrid />
      <SideBySide />
      <BigStatement
        className="text-grad-solace"
        text="Emergency care should feel calm, not scary. That's why we built Solace. Care starts the moment you speak, and your care team always knows why."
      />
      <DarkTriage />
      <ClosingShowcase />
    </div>
  );
}
