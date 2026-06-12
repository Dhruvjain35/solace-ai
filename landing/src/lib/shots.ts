// Real Solace product screenshots, extracted from the product demo.
// Phones are transparent cutouts (no background); terminal/ehr are rounded windows.
export const SHOTS = {
  voice: '/assets/shots/voice.png',
  insurance: '/assets/shots/insurance.png',
  working: '/assets/shots/working.png',
  plan: '/assets/shots/plan.png',
  medical: '/assets/shots/medical.png',
  terminal: '/assets/shots/terminal.png',
  ehr: '/assets/shots/ehr.png',
  // Frame-free crops for the device mockups (the originals carry baked-in
  // window chrome and, in terminal's case, mid-animation ghosting).
  ehrClean: '/assets/shots/ehr-clean.png',
  queue: '/assets/shots/queue.png',
} as const;
