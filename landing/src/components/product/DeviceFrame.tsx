import type { ReactNode } from 'react';
import { Signal, Wifi, BatteryFull } from 'lucide-react';

/*
 * DeviceFrame — a CSS-built iPhone, vector-crisp at any scale. The screen
 * content is part of the device, so registration problems are impossible:
 * no photo perspective, no masks, no bleed. Width is set by the parent;
 * everything inside scales via container-query units (cqw).
 *
 * Layers: titanium rail → black bezel → screen (content slot + status bar +
 * dynamic island) → side buttons.
 */
export default function DeviceFrame({
  screen,
  className = '',
}: {
  screen: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`relative aspect-[9/19.5] [container-type:inline-size] ${className}`}
    >
      {/* Side buttons (behind the rail, peeking out) */}
      <div aria-hidden className="absolute -left-[1.1%] top-[16%] h-[4.5%] w-[1.6%] rounded-l-[1cqw] bg-[#2e2e33]" />
      <div aria-hidden className="absolute -left-[1.1%] top-[23.5%] h-[7%] w-[1.6%] rounded-l-[1cqw] bg-[#2e2e33]" />
      <div aria-hidden className="absolute -left-[1.1%] top-[32%] h-[7%] w-[1.6%] rounded-l-[1cqw] bg-[#2e2e33]" />
      <div aria-hidden className="absolute -right-[1.1%] top-[25%] h-[10%] w-[1.6%] rounded-r-[1cqw] bg-[#2e2e33]" />

      {/* Titanium rail */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          borderRadius: '17.5% / 8.08%',
          background:
            'linear-gradient(145deg, #4a4a50 0%, #232327 28%, #101014 55%, #3a3a40 100%)',
          boxShadow:
            '0 40px 80px -16px rgba(0,0,0,0.40), 0 16px 32px -12px rgba(0,0,0,0.28), inset 0 0 0 1px rgba(255,255,255,0.10)',
        }}
      />
      {/* Black bezel */}
      <div
        aria-hidden
        className="absolute bg-black"
        style={{ inset: '0.55% 1.2%', borderRadius: '16.6% / 7.66%' }}
      />
      {/* Screen */}
      <div
        className="absolute overflow-hidden bg-[#fbfbfb]"
        style={{ inset: '1.5% 3.2%', borderRadius: '14.2% / 6.55%' }}
      >
        {/* App content */}
        <div className="absolute inset-0">{screen}</div>

        {/* iOS status bar */}
        <div
          aria-hidden
          className="absolute inset-x-0 top-0 z-20 flex items-center justify-between px-[9cqw] pt-[2.6cqw] text-ink"
        >
          <span
            className="font-sans font-semibold leading-none"
            style={{ fontSize: '4.6cqw', letterSpacing: '-0.01em' }}
          >
            9:41
          </span>
          <span className="flex items-center gap-[1.6cqw]">
            <Signal style={{ width: '4.4cqw', height: '4.4cqw' }} strokeWidth={2.6} />
            <Wifi style={{ width: '4.8cqw', height: '4.8cqw' }} strokeWidth={2.6} />
            <BatteryFull style={{ width: '6cqw', height: '6cqw' }} strokeWidth={2} />
          </span>
        </div>

        {/* Dynamic island */}
        <div
          aria-hidden
          className="absolute left-1/2 z-30 -translate-x-1/2 rounded-full bg-black"
          style={{ top: '2.2cqw', width: '29cqw', height: '8.6cqw' }}
        />

        {/* Soft top sheen so the screen reads as glass */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 z-10"
          style={{
            background:
              'linear-gradient(168deg, rgba(255,255,255,0.10) 0%, rgba(255,255,255,0) 22%)',
          }}
        />
      </div>
    </div>
  );
}
