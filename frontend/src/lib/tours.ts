/**
 * Tour registry. Each entry is a self-contained tour definition; pages reference
 * a tour by its id when mounting <TourLauncher tourId="..." />.
 *
 * Anchor strings here MUST match `data-tour="<anchor>"` attributes added to the
 * corresponding page. Steps whose anchor is missing at runtime are skipped
 * gracefully (see useTour), so a tour never breaks if a panel is conditionally
 * rendered (e.g. the patient detail drawer is closed).
 */

import type { TourDefinition } from "./tour-types";

export const CLINICIAN_DASHBOARD_TOUR: TourDefinition = {
  id: "clinician-dashboard-v1",
  label: "Dashboard tour",
  steps: [
    {
      id: "intro",
      title: "Welcome to the Clinician Terminal",
      body: "A two-minute walkthrough of the triage queue, the ESI acuity model, and the clinical tools. You can dismiss any time and restart from the help button.",
    },
    {
      id: "stats",
      title: "At-a-glance load",
      body: "Live counts of waiting patients, active pain alarms, average wait, and the share of cases already refined by the bedside model. Refreshes every few seconds.",
      anchor: "stat-strip",
      placement: "bottom",
    },
    {
      id: "queue",
      title: "The patient queue",
      body: "Every patient who has checked in, ordered by acuity. Each card shows the provisional ESI badge from the self-serve intake. Select a card to open the full chart.",
      anchor: "patient-queue",
      placement: "top",
    },
    {
      id: "esi",
      title: "ESI triage badge and SHAP",
      body: "Open any patient to see the ESI acuity level, model confidence, and a SHAP breakdown of exactly which findings drove the score. Burnt-amber bars push acuity up, green bars pull it down.",
      anchor: "queue-sidebar",
      placement: "right",
    },
    {
      id: "refine",
      title: "Two-stage refine triage",
      body: "The intake score is provisional. Once you take bedside vitals (HR, BP, respiratory rate, SpO2) the ML ensemble refines the ESI and unlocks the qSOFA, SIRS, shock-index, and CV-risk composites.",
      anchor: "queue-sidebar",
      placement: "right",
    },
    {
      id: "nav",
      title: "Scribe, inbox, letters, and tools",
      body: "From the sidebar reach the ambient scribe, the inbox and admin tasks, letters and forms, the evidence and early-warning tools, and the wider operations suite.",
      anchor: "admin-nav",
      placement: "right",
    },
    {
      id: "qr",
      title: "Patient check-in QR",
      body: "Display this QR for patients to scan and start their own voice or text intake. New arrivals appear in the queue automatically.",
      anchor: "checkin-qr",
      placement: "right",
    },
    {
      id: "help",
      title: "Restart any time",
      body: "Tap the help button in the top-right corner whenever you want to replay this tour.",
      anchor: "tour-launcher",
      placement: "left",
    },
  ],
};

/**
 * Patient-side first-run help. Intentionally short and modal-only (no anchors):
 * the intake is a focused, full-screen flow on a phone, so a centred card is the
 * least disruptive way to set expectations and the clinician-disclaimer.
 */
export const PATIENT_INTAKE_TOUR: TourDefinition = {
  id: "patient-intake-v1",
  label: "How check-in works",
  steps: [
    {
      id: "voice-or-text",
      title: "Tell us what brings you in",
      body: "You can describe your symptoms by voice or by typing. Take your time and say it in your own words, in your own language.",
    },
    {
      id: "not-a-clinician",
      title: "This does not replace a clinician",
      body: "Solace helps the care team prepare for your visit. It is not medical advice and does not replace seeing a clinician. If this is an emergency, call your local emergency number.",
    },
  ],
};

export const TOUR_REGISTRY: Record<string, TourDefinition> = {
  [CLINICIAN_DASHBOARD_TOUR.id]: CLINICIAN_DASHBOARD_TOUR,
  [PATIENT_INTAKE_TOUR.id]: PATIENT_INTAKE_TOUR,
};
