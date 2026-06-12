import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { INTAKE_POSTER_SRC, INTAKE_VIDEO_SRC } from '../../lib/hims';
import CanvasIntake from './CanvasIntake';

/*
 * PhoneRig — Dhruv's AI-generated hand+iPhone mockup (transparent
 * background, front-facing, modern device), with the real Solace screens
 * corner-pinned onto the glass via a runtime homography (CSS matrix3d).
 * Unlike the earlier failed photo composites, this asset was made for the
 * job: alpha matte ships with it, the screen is near-planar, and the dark
 * bezel forgives ±2px — so the overlay reads as part of the image.
 *
 * The overlay's top edge sits just below the device's dynamic island; the
 * white glass beside/above the island stays from the source image and
 * blends seamlessly with the white app screens.
 *
 * SCREEN_QUAD: full-glass corners as fractions of the 1728×2304 image —
 * TL, TR, BR, BL. Measured from the photo's pixels (/tmp/pw/measure-glass.js
 * scans each edge for the bezel→glass luminance step), then tucked 4–5px
 * under the dark bezel so no edge ever undershoots into the photo's white
 * screen at any rendered scale. Don't recalibrate from screenshots — measure.
 */
// hand-b1: Dhruv's chosen mockup (Downloads/mockup.png), black studio bg
// removed via Vision segmentation, magenta calibration screen. The arm
// runs to the photo's bottom edge, so card-edge crops read natural, the
// forhims pattern. No CSS mask or drop-shadow, ever (Safari rendered
// that filter+mask stack as a visible rectangle seam).
const PHOTO = '/assets/hand-b3.webp';
const PHOTO_W = 1728;
const PHOTO_H = 2304;

// Measured from the mockup's magenta screen pixels (edge line fits),
// then pushed 4px outward under the bezel as bleed.
// 10px horizontal / 6px vertical bleed: the bezel edges bow slightly
// (lens distortion), so a straight-line fit needs generous overdraw onto
// the dark bezel to never undershoot mid-edge.
const SCREEN_QUAD: ReadonlyArray<readonly [number, number]> = [
  [0.422, 0.2166], // TL
  [0.8068, 0.2182], // TR
  [0.7991, 0.8296], // BR
  [0.4259, 0.8273], // BL
];

// Logical overlay size before transformation — proportional to the real
// glass area so content keeps its aspect.
const BASE_W = 400;
const BASE_H = 927;

// Solve the projective map sending rect (0,0)-(w,h) onto the pixel quad.
// Closed-form unit-square homography, prescaled by 1/w, 1/h.
function matrix3dFor(
  w: number,
  h: number,
  quad: ReadonlyArray<readonly [number, number]>,
): string {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = quad;
  const dx1 = x1 - x2;
  const dx2 = x3 - x2;
  const dy1 = y1 - y2;
  const dy2 = y3 - y2;
  const sx = x0 - x1 + x2 - x3;
  const sy = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (sx * dy2 - sy * dx2) / den;
  const hh = (dx1 * sy - dy1 * sx) / den;
  const a = x1 - x0 + g * x1;
  const b = x3 - x0 + hh * x3;
  const c = x0;
  const d = y1 - y0 + g * y1;
  const e = y3 - y0 + hh * y3;
  const f = y0;
  return `matrix3d(${a / w},${d / w},0,${g / w},${b / h},${e / h},0,${hh / h},0,0,1,0,${c},${f},0,1)`;
}

// Recompute the matrix whenever the rig resizes (matrix3d works in element
// pixels, so it is not scale-invariant). offsetWidth/Height are layout px,
// unaffected by ancestor scale transforms.
function useScreenMatrix(ref: RefObject<HTMLDivElement>): string {
  const [m, setM] = useState('');
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const W = el.offsetWidth;
      const H = el.offsetHeight;
      if (!W || !H) return;
      const pts = SCREEN_QUAD.map(([fx, fy]) => [fx * W, fy * H] as const);
      setM(matrix3dFor(BASE_W, BASE_H, pts));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return m;
}

export function IntakeVideo() {
  const hostRef = useRef<HTMLDivElement>(null);
  // Some Safari configs (Low Power Mode, a per-site "Never Auto-Play"
  // setting) hard-block <video> autoplay and paint a system play glyph
  // that page CSS cannot hide in modern Safari. When that happens we swap
  // to an animated-WebP twin of the recording — animated images have no
  // autoplay policy, so the screen always plays.
  const [blocked, setBlocked] = useState(false);

  // No pause/visibility staging here, ever: WebKit starts the native
  // autoplay almost immediately, and any pause() that races it cancels
  // the autoplay grant — that exact race is what froze the hero video in
  // Safari while Chrome shrugged it off.
  useEffect(() => {
    if (blocked) return;
    const v = hostRef.current?.querySelector('video');
    if (!v) return;
    const pin = () => {
      if (v.playbackRate !== 2) v.playbackRate = 2; // intake in half the time
    };
    // Rate is pinned ONLY once playback is rolling. Setting playbackRate
    // before the load finishes counts as an un-gestured rate change in
    // WebKit and disqualifies the video from native autoplay. Same reason
    // there is NO eager v.play() here: invoking play() clears the
    // element's can-autoplay flag (HTML spec) and cancels the native
    // attribute-driven autoplay.
    // Reveal only once frames are genuinely advancing — NOT on 'playing'.
    // Low Power Mode Safari fires 'playing', suspends a beat later, and
    // its system play glyph would flash on the just-revealed video.
    const reveal = () => {
      if (v.currentTime > 0.05) {
        pin();
        v.style.opacity = '1';
        v.removeEventListener('timeupdate', reveal);
      }
    };
    v.addEventListener('timeupdate', reveal);
    v.addEventListener('playing', pin);
    // Safari suspending a barely-started video = hard block. Hide it and
    // swap to the animation immediately, before any glyph can show.
    const onPause = () => {
      if (v.currentTime < 0.3) {
        v.style.opacity = '0';
        setBlocked(true);
      }
    };
    v.addEventListener('pause', onPause);
    // First real interaction also starts a politely-blocked video.
    const gestures = ['pointerdown', 'touchend', 'wheel', 'keydown'] as const;
    const onGesture = () => {
      if (v.paused) {
        pin();
        void v.play().catch(() => {});
      }
    };
    gestures.forEach((t) =>
      window.addEventListener(t, onGesture, { passive: true }),
    );
    // Backstop: fully loaded, never advanced a frame, no pause event →
    // this browser will never start it on its own. Swap to the animation.
    let timer: number | undefined;
    const probe = () => {
      timer = window.setTimeout(() => {
        if (v.paused && v.played.length === 0) setBlocked(true);
      }, 900);
    };
    if (v.readyState >= 3) probe();
    else v.addEventListener('canplaythrough', probe, { once: true });
    return () => {
      window.clearTimeout(timer);
      v.removeEventListener('timeupdate', reveal);
      v.removeEventListener('playing', pin);
      v.removeEventListener('pause', onPause);
      v.removeEventListener('canplaythrough', probe);
      gestures.forEach((t) => window.removeEventListener(t, onGesture));
    };
  }, [blocked]);

  if (blocked) {
    // WebCodecs canvas player: same mp4, same hardware decoder a <video>
    // would use, but no autoplay policy — full quality and smooth even on
    // the Low Power Mode machines that blocked the <video> in the first
    // place. (The software-decoded WebP fallback stuttered exactly there.)
    return <CanvasIntake />;
  }

  return (
    <div
      ref={hostRef}
      aria-hidden="true"
      // Starts below the CSS dynamic island, like a real app render.
      className="pointer-events-none relative mt-[13.5cqw] w-full"
    >
      {/* Clean still underneath: the video is transparent until frames
          roll, so Safari's paused state (and its un-hideable system play
          glyph) can never be seen. */}
      <img
        src={INTAKE_POSTER_SRC}
        alt=""
        className="absolute inset-0 h-full w-full"
      />
      {/* React never serializes `muted` into markup (facebook/react#10389),
          and Safari's autoplay gate reads the markup attributes — so the
          tag is injected verbatim with autoplay+muted+playsinline present
          at parse time. */}
      <div
        dangerouslySetInnerHTML={{
          __html: `<video src="${INTAKE_VIDEO_SRC}" poster="${INTAKE_POSTER_SRC}" autoplay muted loop playsinline webkit-playsinline preload="auto" tabindex="-1" style="display:block;position:relative;width:100%;height:auto;opacity:0;transition:opacity .25s"></video>`,
        }}
      />
    </div>
  );
}

export default function PhoneRig({
  className = '',
  alt = 'A hand holding a phone running the Solace patient check-in',
  screen,
}: {
  className?: string;
  alt?: string;
  screen?: ReactNode;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const matrix = useScreenMatrix(boxRef);

  return (
    <div
      ref={boxRef}
      className={`relative ${className}`}
      style={{ aspectRatio: `${PHOTO_W} / ${PHOTO_H}` }}
    >
      {/* The hand+device mockup — its own alpha, no matting needed. */}
      <img
        src={PHOTO}
        alt={alt}
        width={PHOTO_W}
        height={PHOTO_H}
        className="absolute inset-0 h-full w-full"
      />
      {/* Screen content, corner-pinned onto the glass below the island. */}
      {matrix ? (
        <div
          aria-hidden="true"
          className="absolute left-0 top-0 overflow-hidden bg-[#fafafa] [container-type:inline-size]"
          style={{
            width: BASE_W,
            height: BASE_H,
            transform: matrix,
            transformOrigin: '0 0',
            borderRadius: '40px',
          }}
        >
          {screen ?? <IntakeVideo />}
          {/* Dynamic island, redrawn crisp over the covered photo notch. */}
          <div
            aria-hidden="true"
            className="absolute left-1/2 top-[2.4cqw] z-30 h-[10.6cqw] w-[34cqw] -translate-x-1/2 rounded-full bg-black"
          />
        </div>
      ) : null}
    </div>
  );
}
