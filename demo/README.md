# Solace demo video (Remotion)

75-second composition that stitches **real screen recordings** with motion zoom,
captions, and a "time-shift" card showing the same patient data flowing from
phone → clinician dashboard in ~7 seconds.

## 1. Record your clips (on your own device)

Drop three MP4s into `public/clips/`:

### `patient-flow.mp4` (phone screen recording, portrait)
iPhone: Control Center → Screen Recording button (add it in Settings → Control Center if missing). On a fresh Solace demo:
1. Scan the QR from the clinician dashboard.
2. Walk through: welcome → medical → insurance (skip OK) → record (say something like "chest pain for two hours, 40 year old, no allergies") → follow-ups → result screen.
3. Stop recording when you see the ESI + comfort protocol.
Trim to ~24 s. Name it `patient-flow.mp4` (or `.mov` — rename or convert).

### `clinician-flow.mp4` (desktop, landscape)
QuickTime → File → New Screen Recording → record the clinician dashboard:
1. Show the new-arrival pulse banner hitting
2. Click the new patient card, show the detail pane (pre-brief, scribe note, ESI, SHAP)
Trim to ~24 s.

### `clinician-vitals.mp4` (desktop, focused on the VitalsPanel)
Record the nurse filling vitals (HR, BP, SpO2, etc.) then hitting "Refine triage". Trim to ~10 s.

## 2. Install + preview

```bash
cd demo
npm install
npm run dev
```

Opens Remotion Studio at `localhost:3000`. Scrub through the composition.

## 3. Render MP4

```bash
npm run render
```

Output: `out/solace-demo.mp4` at 1920x1080 / 30 fps.

## 4. Tuning

Open `src/Solace.tsx`:
- **Zoom rectangles** — each scene has `start` and `end` `{x, y, scale}`. Change `x, y` (0–1 of source width/height) to focus on different UI regions. `scale > 1` zooms in.
- **Caption timings** — `<Caption from={X} duration={Y}>` is in frames (30 fps).
- **Scene durations** — adjust the `Sequence durationInFrames` on each scene in the top-level `Solace` component, then bump `SOLACE_DURATION` to match.
