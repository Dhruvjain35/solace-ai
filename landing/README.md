# Solace marketing site (`landing/`)

Live: **https://solacehealth-eight.vercel.app** (alias: solace-ed.vercel.app)

A standalone Vite + React 18 + TypeScript + Tailwind v3 + framer-motion app.
It shares nothing with `frontend/` (the product) except the brand.

## Workflow

```bash
cd landing
npm install
npm run dev        # localhost:5173
npx tsc --noEmit   # must pass before pushing
npm run build      # must pass before pushing
```

**Deploys are automatic.** Push to `main` and Vercel builds this folder
(project `solacehealth`, root directory = `landing`, SPA rewrites in
`vercel.json`). Live in ~30s. No manual deploy step.

## Map

| Path | What it is |
|---|---|
| `src/pages/` | One file per route: Product (the landing), HowItWorks, Clinicians, Company, Pricing, Demo |
| `src/components/product/` | The landing page sections + shared device mockups |
| `src/components/product/PhoneRig.tsx` | Hand+iPhone mockup. Screens are corner-pinned onto the photo via a measured homography. **Do not edit the SCREEN_QUAD or swap the photo without re-measuring** (see comments in the file) |
| `src/components/product/CanvasIntake.tsx` | Hero video player. Plays the mp4 via WebCodecs when Safari blocks `<video>` autoplay. Don't simplify it; every line exists because of a real Safari behavior (comments explain) |
| `src/components/product/{Ehr,Queue,Letters}Screen.tsx` | The Atlas dashboard drawn as DOM (crisp at any size) for the laptop mockup |
| `src/lib/hims.ts` | The design system's shared constants: easing curves, app screen stills, video sources |
| `public/assets/` | The hand photo, app screen stills (captured from the live demo app), intake video + animated fallback |
| `_legacy-mockup.html` | The old single-file mockup this site replaced (kept for reference) |

## House rules (read before touching copy or styles)

- Display type is `font-sofia` with `tracking-hims`; body is the default sans.
- Animations use exactly two curves: `himsFade` (opacity, 0.2s) and
  `himsMove` (transforms, 0.6s) from `src/lib/hims.ts`. Reveals are
  `whileInView` once, `y: 28 -> 0`, staggered `index * 0.04`. Always respect
  `useReducedMotion`. No other easings, no infinite loops without an
  in-view gate.
- Tiles/cards use four palettes only: `bg-ink`, `bg-solace-green-700`,
  `bg-paper`/white, and the pale teal gradient (see TileGrid).
- Copy: **no em dashes, ever.** Plain language a patient would understand —
  never ESI / acuity / pre-brief / coded data in marketing copy. Lowercase
  -leaning tile sublines. Never claim the AI decides; clinicians always
  make the final call.
- No raw app screenshots outside a device mockup. No emoji, no icon-dot
  feature lists.

## Re-capturing app screens

Stills and the intake video come from the live patient app
(solaceaidemo.vercel.app) via Playwright scripts (393x852 viewport,
deviceScaleFactor 3 stills; video re-encoded with `+faststart`, plus an
animated-WebP fallback). If the app UI changes, re-capture, then rename
the video/animation files (cache busting) and update `src/lib/hims.ts`.
