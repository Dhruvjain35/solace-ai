import { useSyncExternalStore } from 'react';

// Tailwind's lg breakpoint — the line between the full scroll choreography
// and the simplified stacked layouts across the Product page sections.
const QUERY = '(min-width: 1024px)';

function subscribe(onChange: () => void) {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener('change', onChange);
  return () => mq.removeEventListener('change', onChange);
}

export default function useIsWide(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => true,
  );
}
