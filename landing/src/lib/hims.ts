// Shared constants for the Product page — an exact structural clone of
// app.forhims.com (extracted 2026-06-04 via designlang), remapped onto the
// Solace brand. Every section component imports from here so the whole page
// moves on the same two curves and composites the same hand+phone rig.
import type { Transition } from 'framer-motion';

// forhims' two curves: opacity moves on easeOutCubic at 200ms, transforms on
// easeOutExpo at 600ms. These are the only easings the Product page uses.
export const HIMS_OUT = [0.215, 0.61, 0.355, 1] as const;
export const HIMS_EXPO = [0.19, 1, 0.22, 1] as const;

export const himsFade: Transition = { duration: 0.2, ease: HIMS_OUT };
export const himsMove: Transition = { duration: 0.6, ease: HIMS_EXPO };

// App screens captured from the live intake flow (deviceScaleFactor-3
// Playwright stills) — only the moments the phone mockups actually show.
// More stills live in public/assets/screens/ if scenes are ever added.
export const APP_SCREENS = {
  lang: '/assets/screens/lang.png',
  insurance: '/assets/screens/insurance.png',
  welcome: '/assets/screens/welcome.png',
  symptoms: '/assets/screens/symptoms.png',
  medical: '/assets/screens/medical.png',
  meds: '/assets/screens/meds.png',
  questions: '/assets/screens/questions.png',
  plan: '/assets/screens/plan.png',
} as const;
// faststart remux (moov atom up front): required for the WebCodecs canvas
// player's streaming demux, and faster first-frame for the <video> path.
export const INTAKE_VIDEO_SRC = '/assets/solace-intake-fs.mp4';
export const INTAKE_POSTER_SRC = '/assets/solace-intake-poster.jpg';
// Animated-WebP twin of the recording (2x speed baked in, infinite loop;
// full 786px, 24fps, q78 via ffmpeg frames → img2webp). Safari configs that
// hard-block <video> autoplay (Low Power Mode, per-site "Never Auto-Play")
// cannot block an animated image — it always plays. If this is ever
// re-rendered, RENAME the file: Safari serves the old one from cache and
// the upgrade silently never reaches the user.
export const INTAKE_ANIM_SRC = '/assets/solace-intake-loop.webp';
