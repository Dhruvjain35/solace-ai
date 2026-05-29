import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  HeartPulse,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import {
  careGapsSidebar,
  sdohReferral,
  sdohScreen,
} from "../../../lib/api-ops";
import type {
  CareGap,
  CareGapSidebar,
  SdohScreenResult,
} from "../../../lib/api-ops";

/** Rank weight for a care-gap priority label. Higher sorts first. */
function priorityWeight(priority?: string): number {
  switch ((priority || "").toLowerCase()) {
    case "high":
    case "urgent":
    case "critical":
      return 3;
    case "medium":
    case "moderate":
      return 2;
    case "low":
      return 1;
    default:
      return 0;
  }
}

/** Tailwind token classes for a priority pill. */
function priorityTone(priority?: string): string {
  switch ((priority || "").toLowerCase()) {
    case "high":
    case "urgent":
    case "critical":
      return "bg-error-container text-error";
    case "medium":
    case "moderate":
      return "bg-warning-container text-warning";
    case "low":
      return "bg-success-container text-success";
    default:
      return "bg-surface-high text-text-muted";
  }
}

/** Tailwind token classes for an SDoH risk-level pill. */
function riskTone(level?: string): string {
  switch ((level || "").toLowerCase()) {
    case "high":
      return "bg-error-container text-error";
    case "moderate":
      return "bg-warning-container text-warning";
    case "low":
      return "bg-success-container text-success";
    default:
      return "bg-surface-high text-text-muted";
  }
}

/** A friendly per-gap action line. */
function gapAction(gap: CareGap): string {
  const measure = gap.measure || gap.title || "this measure";
  return `Order or schedule the service that closes ${measure}, then document it on the patient chart.`;
}

export default function CareGapsTab() {
  const { hospitalId, patientId, patient, loading, error } =
    usePatientWorkspace();

  const [gapData, setGapData] = useState<CareGapSidebar | null>(null);
  const [gapsLoading, setGapsLoading] = useState<boolean>(false);
  const [gapsError, setGapsError] = useState<string | null>(null);

  const [screening, setScreening] = useState<boolean>(false);
  const [sdoh, setSdoh] = useState<SdohScreenResult | null>(null);
  const [sdohError, setSdohError] = useState<string | null>(null);

  const [consent, setConsent] = useState<boolean>(false);
  const [referringDomain, setReferringDomain] = useState<string | null>(null);
  const [referredDomains, setReferredDomains] = useState<string[]>([]);
  const [referralError, setReferralError] = useState<string | null>(null);

  const loadGaps = useCallback(() => {
    if (!patientId) return;
    let cancelled = false;
    setGapsLoading(true);
    setGapsError(null);
    careGapsSidebar(hospitalId, patientId, 12)
      .then((d) => {
        if (!cancelled) setGapData(d);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const err = e as {
          response?: { data?: { detail?: string } };
          message?: string;
        };
        setGapsError(
          err?.response?.data?.detail ||
            err?.message ||
            "Could not load care gaps for this patient.",
        );
      })
      .finally(() => {
        if (!cancelled) setGapsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hospitalId, patientId]);

  useEffect(() => {
    const cleanup = loadGaps();
    return cleanup;
  }, [loadGaps]);

  // --- Guards (loading / error / null patient) --------------------------------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2
          size={24}
          className="animate-spin text-text-muted"
          aria-label="Loading patient"
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <AlertTriangle
            size={28}
            className="mx-auto mb-3 text-error"
            aria-hidden="true"
          />
          <h2 className="text-lg font-bold tracking-tight">Care Gaps</h2>
          <p className="text-text-muted text-sm mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!patient) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <ClipboardList
            size={28}
            className="mx-auto mb-3 text-text-muted"
            aria-hidden="true"
          />
          <h2 className="text-lg font-bold tracking-tight">Care Gaps</h2>
          <p className="text-text-muted text-sm mt-1">
            No patient record is loaded.
          </p>
        </div>
      </div>
    );
  }

  // --- SDoH screener handlers -------------------------------------------------
  const runScreen = () => {
    setScreening(true);
    setSdohError(null);
    setReferralError(null);
    // The PRAPARE screener answers come from the chart-of-record; an empty
    // payload asks the backend to score from the patient's known context.
    sdohScreen(hospitalId, {}, "prapare")
      .then((d) => setSdoh(d))
      .catch((e: unknown) => {
        const err = e as {
          response?: { data?: { detail?: string } };
          message?: string;
        };
        setSdohError(
          err?.response?.data?.detail ||
            err?.message ||
            "Could not run the social-needs screener.",
        );
      })
      .finally(() => setScreening(false));
  };

  const makeReferral = (domain: string) => {
    if (!consent) return;
    setReferringDomain(domain);
    setReferralError(null);
    sdohReferral(hospitalId, {
      domain,
      patient_ref: patientId,
      consent: true,
    })
      .then(() => {
        setReferredDomains((prev) =>
          prev.includes(domain) ? prev : [...prev, domain],
        );
      })
      .catch((e: unknown) => {
        const err = e as {
          response?: { data?: { detail?: string } };
          message?: string;
        };
        setReferralError(
          err?.response?.data?.detail ||
            err?.message ||
            "Could not create the referral.",
        );
      })
      .finally(() => setReferringDomain(null));
  };

  const rankedGaps = gapData
    ? [...gapData.gaps].sort(
        (a, b) => priorityWeight(b.priority) - priorityWeight(a.priority),
      )
    : [];

  const patientAge = gapData?.patient_age ?? null;

  return (
    <div className="max-w-3xl mx-auto py-6 px-4 space-y-6">
      {/* Care-gap panel */}
      <section className="bg-surface-lowest rounded-xl shadow-card p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <ClipboardList
              size={22}
              className="text-primary mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <div>
              <h2 className="text-lg font-bold tracking-tight">Care Gaps</h2>
              <p className="text-text-muted text-sm mt-0.5">
                Open HEDIS measures for {patient.name}
                {patientAge != null ? `, age ${patientAge}` : ""}.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={loadGaps}
            disabled={gapsLoading}
            aria-label="Refresh care gaps"
            className="flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium text-text-muted bg-surface-low hover:bg-surface-high focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
          >
            {gapsLoading ? (
              <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw size={15} aria-hidden="true" />
            )}
            Refresh
          </button>
        </div>

        {gapData?.headline && (
          <p className="mt-4 text-sm font-medium text-ink bg-surface-low rounded-lg px-3 py-2">
            {gapData.headline}
          </p>
        )}

        <div className="mt-4">
          {gapsLoading && !gapData && (
            <div className="flex items-center justify-center py-10">
              <Loader2
                size={20}
                className="animate-spin text-text-muted"
                aria-label="Loading care gaps"
              />
            </div>
          )}

          {gapsError && (
            <div className="flex items-start gap-2 rounded-lg bg-error-container px-3 py-2.5">
              <AlertTriangle
                size={16}
                className="text-error mt-0.5 shrink-0"
                aria-hidden="true"
              />
              <p className="text-sm text-error">{gapsError}</p>
            </div>
          )}

          {!gapsLoading &&
            !gapsError &&
            gapData &&
            rankedGaps.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <CheckCircle2
                  size={26}
                  className="text-success mb-2"
                  aria-hidden="true"
                />
                <p className="text-sm font-medium text-ink">
                  No open care gaps.
                </p>
                <p className="text-text-muted text-xs mt-0.5">
                  This patient is current on all tracked HEDIS measures.
                </p>
              </div>
            )}

          {!gapsError && rankedGaps.length > 0 && (
            <ul className="space-y-3">
              {rankedGaps.map((gap, i) => {
                const label =
                  gap.title || gap.measure || `Care gap ${i + 1}`;
                return (
                  <li
                    key={`${gap.measure ?? gap.title ?? "gap"}-${i}`}
                    className="rounded-lg border border-line p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-sm font-semibold text-ink">
                        {label}
                      </h3>
                      {gap.priority && (
                        <span
                          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${priorityTone(
                            gap.priority,
                          )}`}
                        >
                          {gap.priority}
                        </span>
                      )}
                    </div>
                    {gap.description && (
                      <p className="mt-1.5 text-sm text-text-muted">
                        {gap.description}
                      </p>
                    )}
                    <p className="mt-2 text-xs font-medium text-primary">
                      Action: {gapAction(gap)}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}

          {gapData && gapData.more_gaps > 0 && (
            <p className="mt-3 text-xs text-text-muted">
              {gapData.more_gaps} additional gap
              {gapData.more_gaps === 1 ? "" : "s"} not shown.
            </p>
          )}
        </div>
      </section>

      {/* SDoH social-needs screener */}
      <section className="bg-surface-lowest rounded-xl shadow-card p-6">
        <div className="flex items-start gap-3">
          <HeartPulse
            size={22}
            className="text-primary mt-0.5 shrink-0"
            aria-hidden="true"
          />
          <div className="flex-1">
            <h2 className="text-lg font-bold tracking-tight">
              Social Needs Screener
            </h2>
            <p className="text-text-muted text-sm mt-0.5">
              Run the PRAPARE social-determinants screen for this patient.
              Referrals require explicit patient consent.
            </p>
          </div>
        </div>

        {!sdoh && (
          <button
            type="button"
            onClick={runScreen}
            disabled={screening}
            className="mt-4 flex items-center gap-1.5 h-10 px-4 rounded-md text-sm font-semibold text-surface-lowest bg-primary hover:bg-primary-hover focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
          >
            {screening && (
              <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            )}
            {screening ? "Screening" : "Run PRAPARE screen"}
          </button>
        )}

        {sdohError && (
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-error-container px-3 py-2.5">
            <AlertTriangle
              size={16}
              className="text-error mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <p className="text-sm text-error">{sdohError}</p>
          </div>
        )}

        {sdoh && (
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${riskTone(
                  sdoh.risk_level,
                )}`}
              >
                {sdoh.risk_level} risk
              </span>
              <span className="text-xs text-text-muted">
                {sdoh.risk_count} need{sdoh.risk_count === 1 ? "" : "s"}{" "}
                identified
              </span>
              {sdoh.urgent && (
                <span className="rounded-full bg-error-container px-2.5 py-0.5 text-xs font-semibold text-error">
                  Urgent
                </span>
              )}
            </div>

            {sdoh.positive_domains.length === 0 ? (
              <p className="text-sm text-text-muted">
                No positive social-determinant domains detected.
              </p>
            ) : (
              <>
                {/* Consent gate */}
                <label className="flex items-start gap-2.5 rounded-lg bg-surface-low px-3 py-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => setConsent(e.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-primary focus-visible:ring-2 focus-visible:ring-primary"
                  />
                  <span className="text-sm text-ink">
                    Patient has given verbal consent to share their information
                    with community referral organizations.
                  </span>
                </label>

                {referralError && (
                  <div className="flex items-start gap-2 rounded-lg bg-error-container px-3 py-2.5">
                    <AlertTriangle
                      size={16}
                      className="text-error mt-0.5 shrink-0"
                      aria-hidden="true"
                    />
                    <p className="text-sm text-error">{referralError}</p>
                  </div>
                )}

                <ul className="space-y-2">
                  {sdoh.positive_domains.map((domain) => {
                    const referred = referredDomains.includes(domain);
                    const busy = referringDomain === domain;
                    return (
                      <li
                        key={domain}
                        className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2.5"
                      >
                        <span className="text-sm font-medium text-ink capitalize">
                          {domain.replace(/_/g, " ")}
                        </span>
                        {referred ? (
                          <span className="flex items-center gap-1 text-xs font-semibold text-success">
                            <CheckCircle2 size={14} aria-hidden="true" />
                            Referral sent
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() => makeReferral(domain)}
                            disabled={!consent || busy}
                            className="flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium text-primary bg-primary-dim hover:bg-primary-fixed focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {busy && (
                              <Loader2
                                size={14}
                                className="animate-spin"
                                aria-hidden="true"
                              />
                            )}
                            Refer
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {!consent && (
                  <p className="text-xs text-text-muted">
                    Confirm patient consent above to enable referrals.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
