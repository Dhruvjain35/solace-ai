/**
 * Tour persistence. A tour is shown once per clinician, dismissible, and
 * resumable. State is stored in localStorage keyed by a stable id of the form
 * `solace.tour.<tourId>.<subjectId>`.
 *
 * `subjectId` is the clinician_id for clinician tours, or a fixed bucket like
 * "patient" / "anon" for unauthenticated surfaces (patient intake). This keeps
 * the key stable across reloads while still being per-clinician where a session
 * exists.
 */

export type TourProgress = {
  /** Index of the step the clinician last reached. Enables resume. */
  step: number;
  /** "done" when finished or dismissed; "active" while mid-tour. */
  status: "active" | "done";
  /** Unix ms of last update — useful for future "re-show after N days" logic. */
  updatedAt: number;
};

const PREFIX = "solace.tour";

function key(tourId: string, subjectId: string): string {
  return `${PREFIX}.${tourId}.${subjectId}`;
}

export function readProgress(tourId: string, subjectId: string): TourProgress | null {
  try {
    const raw = localStorage.getItem(key(tourId, subjectId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as TourProgress;
    if (typeof parsed.step !== "number" || !parsed.status) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeProgress(
  tourId: string,
  subjectId: string,
  progress: Omit<TourProgress, "updatedAt">,
): void {
  try {
    localStorage.setItem(
      key(tourId, subjectId),
      JSON.stringify({ ...progress, updatedAt: Date.now() }),
    );
  } catch {
    /* storage full / disabled — tour just won't persist, no crash */
  }
}

/** True when the tour has never been seen (no record) — i.e. should auto-run. */
export function isFirstRun(tourId: string, subjectId: string): boolean {
  return readProgress(tourId, subjectId) === null;
}

/** Clear a single tour's record so it auto-runs again (used by "Restart tour"). */
export function clearProgress(tourId: string, subjectId: string): void {
  try {
    localStorage.removeItem(key(tourId, subjectId));
  } catch {
    /* no-op */
  }
}
