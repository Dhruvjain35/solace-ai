import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Hash,
  Info,
  Loader2,
  Sparkles,
} from "lucide-react";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import { codingSuggest } from "../../../lib/api";

// ---------------------------------------------------------------------------
// Response types — mirror backend/services/em_coding.py suggest() output.
// ---------------------------------------------------------------------------
type Mdm = {
  problems_addressed?: string;
  problems_detail?: string;
  data_reviewed?: string;
  data_detail?: string;
  risk_of_complications?: string;
  risk_detail?: string;
  summary_supporting_evidence?: string;
};

type EmRanked = {
  code: string;
  level: number;
  mdm: string;
  time_min: number[];
  confidence: number;
  supporting_documentation: string;
  rank: number;
  agrees_with_time: boolean;
};

type EmLeveling = {
  element_scores?: { problems: number; data: number; risk: number };
  mdm_tier?: string;
  driving_score?: number;
  rule?: string;
};

type TimeCrosscheck = {
  documented: boolean;
  total_minutes?: number;
  time_based_code?: string;
  time_based_range?: string;
  note?: string;
  evidence?: string;
};

type Icd10 = { code: string; name?: string; support?: string; specificity?: string };

type CptRanked = {
  code: string;
  name?: string;
  support?: string;
  add_on?: boolean;
  confidence: number;
  ncci_clean: boolean;
};

type NcciFlag = {
  type: string;
  codes: string[];
  severity: "error" | "warning";
  message: string;
};

type NcciValidation = {
  flags: NcciFlag[];
  passed: boolean;
  error_count: number;
  warning_count: number;
  checked_codes: string[];
};

type Modifier = {
  modifier: string;
  attach_to: string;
  reason: string;
  confidence: number;
  requires: string;
};

type CodingResult = {
  available: boolean;
  error?: string;
  mdm?: Mdm;
  em_ranked?: EmRanked[];
  em_leveling?: EmLeveling;
  time_crosscheck?: TimeCrosscheck;
  icd10?: Icd10[];
  cpt_ranked?: CptRanked[];
  ncci_validation?: NcciValidation;
  modifiers?: Modifier[];
  setting?: string;
  patient_type?: string;
  auto_submit?: boolean;
};

// ---------------------------------------------------------------------------
// Small presentational helpers
// ---------------------------------------------------------------------------
function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-surface-lowest rounded-xl shadow-card p-5">
      <h3 className="flex items-center gap-2 text-sm font-bold tracking-tight text-ink mb-3">
        <span className="text-text-muted" aria-hidden="true">
          {icon}
        </span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const tone =
    pct >= 70 ? "bg-success" : pct >= 40 ? "bg-warning" : "bg-error";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 rounded-full bg-surface-high overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-text-muted">{pct}%</span>
    </div>
  );
}

function tierLabel(score: number): string {
  return (
    { 1: "Straightforward", 2: "Low", 3: "Moderate", 4: "High" }[score] ||
    "Straightforward"
  );
}

export default function CodingTab() {
  const { hospitalId, patient, loading, error } = usePatientWorkspace();

  // Auto-source the note from the patient's scribe note, falling back to the
  // raw transcript. Kept editable so the clinician can refine before coding.
  const sourcedNote = useMemo(() => {
    if (!patient) return "";
    return (patient.clinical_scribe_note || patient.transcript || "").trim();
  }, [patient]);

  const [noteText, setNoteText] = useState<string>(sourcedNote);
  const [noteTouched, setNoteTouched] = useState<boolean>(false);
  const [establishedPatient, setEstablishedPatient] = useState<boolean>(true);
  const [busy, setBusy] = useState<boolean>(false);
  const [result, setResult] = useState<CodingResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  // Keep the textarea synced with the patient until the clinician edits it.
  const effectiveNote = noteTouched ? noteText : sourcedNote;

  // ----- guard rendering: loading / error / patient == null first ----------
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2
          size={22}
          className="animate-spin text-text-muted"
          aria-hidden="true"
        />
        <span className="ml-2 text-sm text-text-muted">Loading patient…</span>
      </div>
    );
  }

  if (error || !patient) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="bg-surface-lowest rounded-xl shadow-card p-8 max-w-md text-center">
          <AlertTriangle
            size={28}
            className="mx-auto mb-3 text-error"
            aria-hidden="true"
          />
          <h2 className="text-lg font-bold tracking-tight">Coding</h2>
          <p className="text-text-muted text-sm mt-1">
            {error || "No patient is loaded for this workspace."}
          </p>
        </div>
      </div>
    );
  }

  async function runCoding() {
    const text = effectiveNote.trim();
    if (!text) {
      setRunError("Add note text before requesting coding suggestions.");
      return;
    }
    setBusy(true);
    setRunError(null);
    setResult(null);
    try {
      const data = (await codingSuggest(
        hospitalId,
        text,
        establishedPatient,
      )) as CodingResult;
      if (!data || data.available === false) {
        setRunError(
          data?.error
            ? "Coding service could not complete this note."
            : "Coding suggestions are unavailable right now.",
        );
        return;
      }
      setResult(data);
    } catch {
      setRunError("Could not reach the coding service. Try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  const leveling = result?.em_leveling;
  const elementScores = leveling?.element_scores;
  const timeCheck = result?.time_crosscheck;
  const ncci = result?.ncci_validation;

  return (
    <div className="space-y-5 pb-8">
      {/* Heading + not-submitted notice */}
      <div className="bg-surface-lowest rounded-xl shadow-card p-5">
        <div className="flex items-start gap-3">
          <Hash
            size={22}
            className="mt-0.5 text-text-muted shrink-0"
            aria-hidden="true"
          />
          <div className="min-w-0">
            <h2 className="text-lg font-bold tracking-tight text-ink">
              E&amp;M, ICD-10 &amp; CPT Coding
            </h2>
            <p className="text-text-muted text-sm mt-0.5">
              Suggestions for {patient.name}. The note below is auto-sourced
              from the clinical scribe note and is editable.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-2 mt-4 rounded-lg bg-primary-dim p-3">
          <Info
            size={16}
            className="mt-0.5 text-primary shrink-0"
            aria-hidden="true"
          />
          <p className="text-xs text-primary">
            Decision-support only. Nothing here is submitted to a payer or the
            EHR — review every code and apply it yourself in your billing
            system.
          </p>
        </div>
      </div>

      {/* Note input */}
      <Section title="Encounter note" icon={<Sparkles size={16} />}>
        <label
          htmlFor="coding-note"
          className="block text-xs font-medium text-text-muted mb-1.5"
        >
          Note text used for coding
          {!noteTouched && sourcedNote
            ? " (auto-sourced from scribe note)"
            : ""}
        </label>
        <textarea
          id="coding-note"
          value={effectiveNote}
          onChange={(e) => {
            setNoteTouched(true);
            setNoteText(e.target.value);
          }}
          rows={8}
          placeholder="Paste or edit the clinical encounter note to be coded…"
          className="w-full rounded-lg border border-line bg-surface p-3 text-sm text-ink font-mono leading-relaxed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        />
        {!sourcedNote && (
          <p className="text-xs text-warning mt-1.5">
            No scribe note or transcript on this patient — paste the encounter
            note above.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-4 mt-3">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={establishedPatient}
              onChange={(e) => setEstablishedPatient(e.target.checked)}
              className="h-4 w-4 rounded border-line text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            />
            Established patient
          </label>
          <button
            type="button"
            onClick={runCoding}
            disabled={busy || !effectiveNote.trim()}
            className="flex items-center gap-2 h-11 px-4 rounded-lg bg-primary text-sm font-semibold text-surface-lowest hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
          >
            {busy ? (
              <Loader2 size={16} className="animate-spin" aria-hidden="true" />
            ) : (
              <Sparkles size={16} aria-hidden="true" />
            )}
            {busy ? "Analyzing note…" : "Suggest codes"}
          </button>
        </div>
        {runError && (
          <p className="flex items-center gap-1.5 text-sm text-error mt-3">
            <AlertTriangle size={14} aria-hidden="true" />
            {runError}
          </p>
        )}
      </Section>

      {result && (
        <>
          {/* Setting summary */}
          <div className="flex flex-wrap gap-2 text-xs">
            {result.setting && (
              <span className="rounded-full bg-surface-high px-3 py-1 text-text-muted">
                Setting: {result.setting}
              </span>
            )}
            {result.patient_type && (
              <span className="rounded-full bg-surface-high px-3 py-1 text-text-muted">
                Patient type: {result.patient_type}
              </span>
            )}
            <span className="rounded-full bg-success-container px-3 py-1 text-success font-medium">
              Not submitted — review required
            </span>
          </div>

          {/* E&M ranked levels + MDM rubric */}
          <Section title="E&M level — top 3 candidates" icon={<Hash size={16} />}>
            {result.em_ranked && result.em_ranked.length > 0 ? (
              <ul className="space-y-2.5">
                {result.em_ranked.map((em) => (
                  <li
                    key={em.code}
                    className={`rounded-lg border p-3 ${
                      em.rank === 1
                        ? "border-primary bg-primary-dim"
                        : "border-line bg-surface"
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-ink">
                          {em.code}
                        </span>
                        <span className="text-xs text-text-muted">
                          Level {em.level} · {em.mdm} MDM
                        </span>
                        {em.rank === 1 && (
                          <span className="rounded bg-primary px-1.5 py-0.5 text-[10px] font-semibold text-surface-lowest uppercase tracking-wide">
                            Recommended
                          </span>
                        )}
                      </div>
                      <ConfidenceBar value={em.confidence} />
                    </div>
                    <p className="text-xs text-text-muted mt-1.5">
                      Time range: {em.time_min[0]}–{em.time_min[1]} min
                    </p>
                    {em.supporting_documentation && (
                      <p className="text-xs text-ink mt-1.5">
                        <span className="font-medium">Supporting: </span>
                        {em.supporting_documentation}
                      </p>
                    )}
                    {!em.agrees_with_time && (
                      <p className="flex items-center gap-1.5 text-xs text-warning mt-1.5">
                        <AlertTriangle size={12} aria-hidden="true" />
                        Documented time points to a different level — see the
                        time cross-check below.
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-text-muted">
                No E&M candidates were derived from this note.
              </p>
            )}

            {/* MDM rubric breakdown */}
            {(elementScores || result.mdm) && (
              <div className="mt-4 rounded-lg bg-surface p-3">
                <p className="text-xs font-semibold text-ink mb-2">
                  MDM rubric (2021/2023 AMA)
                  {leveling?.mdm_tier && (
                    <span className="font-normal text-text-muted">
                      {" "}
                      — overall: {leveling.mdm_tier}
                    </span>
                  )}
                </p>
                {leveling?.rule && (
                  <p className="text-[11px] text-text-muted mb-2">
                    {leveling.rule}
                  </p>
                )}
                <dl className="space-y-2">
                  {[
                    {
                      label: "Problems addressed",
                      score: elementScores?.problems,
                      detail: result.mdm?.problems_detail,
                    },
                    {
                      label: "Data reviewed",
                      score: elementScores?.data,
                      detail: result.mdm?.data_detail,
                    },
                    {
                      label: "Risk of complications",
                      score: elementScores?.risk,
                      detail: result.mdm?.risk_detail,
                    },
                  ].map((row) => (
                    <div key={row.label} className="text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-ink">
                          {row.label}
                        </span>
                        {typeof row.score === "number" && (
                          <span className="font-mono text-text-muted">
                            {tierLabel(row.score)} ({row.score}/4)
                          </span>
                        )}
                      </div>
                      {row.detail && (
                        <p className="text-text-muted mt-0.5">{row.detail}</p>
                      )}
                    </div>
                  ))}
                </dl>
                {result.mdm?.summary_supporting_evidence && (
                  <p className="text-xs text-text-muted mt-2 border-t border-line pt-2">
                    <span className="font-medium text-ink">Evidence: </span>
                    {result.mdm.summary_supporting_evidence}
                  </p>
                )}
              </div>
            )}
          </Section>

          {/* Time cross-check */}
          <Section title="Time cross-check" icon={<Clock size={16} />}>
            {timeCheck?.documented ? (
              <div className="space-y-1.5 text-sm">
                <p className="text-ink">
                  Documented total time:{" "}
                  <span className="font-mono font-semibold">
                    {timeCheck.total_minutes} min
                  </span>
                </p>
                <p className="text-ink">
                  Time-based code:{" "}
                  <span className="font-mono font-semibold">
                    {timeCheck.time_based_code}
                  </span>{" "}
                  <span className="text-text-muted text-xs">
                    ({timeCheck.time_based_range})
                  </span>
                </p>
                {timeCheck.evidence && (
                  <p className="text-xs text-text-muted">
                    Cited: “{timeCheck.evidence}”
                  </p>
                )}
                {result.em_ranked &&
                  result.em_ranked[0] &&
                  timeCheck.time_based_code !== result.em_ranked[0].code && (
                    <p className="flex items-center gap-1.5 text-xs text-warning">
                      <AlertTriangle size={12} aria-hidden="true" />
                      Time-based code disagrees with the MDM-recommended{" "}
                      {result.em_ranked[0].code}. Bill on whichever the note
                      best supports.
                    </p>
                  )}
                {timeCheck.note && (
                  <p className="text-xs text-text-muted">{timeCheck.note}</p>
                )}
              </div>
            ) : (
              <p className="text-sm text-text-muted">
                {timeCheck?.note ||
                  "No total encounter time documented — leveling is MDM-based only."}
              </p>
            )}
          </Section>

          {/* NCCI validation summary */}
          <Section
            title="NCCI validation"
            icon={
              ncci?.passed ? (
                <CheckCircle2 size={16} />
              ) : (
                <AlertTriangle size={16} />
              )
            }
          >
            {ncci ? (
              <>
                <p
                  className={`flex items-center gap-1.5 text-sm font-medium ${
                    ncci.passed ? "text-success" : "text-error"
                  }`}
                >
                  {ncci.passed ? (
                    <CheckCircle2 size={14} aria-hidden="true" />
                  ) : (
                    <AlertTriangle size={14} aria-hidden="true" />
                  )}
                  {ncci.passed
                    ? "No blocking NCCI edits detected."
                    : `${ncci.error_count} blocking edit${
                        ncci.error_count === 1 ? "" : "s"
                      } detected.`}
                  {ncci.warning_count > 0 &&
                    ` ${ncci.warning_count} warning${
                      ncci.warning_count === 1 ? "" : "s"
                    }.`}
                </p>
                {ncci.flags.length > 0 && (
                  <ul className="space-y-2 mt-3">
                    {ncci.flags.map((flag, i) => (
                      <li
                        key={`${flag.type}-${i}`}
                        className={`rounded-lg border p-3 text-xs ${
                          flag.severity === "error"
                            ? "border-error bg-error-container"
                            : "border-warning bg-warning-container"
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                              flag.severity === "error"
                                ? "bg-error text-surface-lowest"
                                : "bg-warning text-surface-lowest"
                            }`}
                          >
                            {flag.severity}
                          </span>
                          <span className="font-mono font-semibold text-ink">
                            {flag.codes.join(" + ")}
                          </span>
                        </div>
                        <p className="text-ink mt-1">{flag.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
                {ncci.checked_codes.length > 0 && (
                  <p className="text-[11px] text-text-muted mt-2">
                    Checked: {ncci.checked_codes.join(", ")}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-text-muted">
                No CPT codes to validate.
              </p>
            )}
          </Section>

          {/* ICD-10 + CPT side by side */}
          <div className="grid gap-5 md:grid-cols-2">
            <Section title="ICD-10-CM diagnoses" icon={<Hash size={16} />}>
              {result.icd10 && result.icd10.length > 0 ? (
                <ul className="space-y-2">
                  {result.icd10.map((dx) => (
                    <li
                      key={dx.code}
                      className="rounded-lg border border-line bg-surface p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono font-bold text-ink">
                          {dx.code}
                        </span>
                        {dx.specificity && (
                          <span className="text-[10px] uppercase tracking-wide text-text-muted">
                            {dx.specificity} specificity
                          </span>
                        )}
                      </div>
                      {dx.name && (
                        <p className="text-sm text-ink mt-0.5">{dx.name}</p>
                      )}
                      {dx.support && (
                        <p className="text-xs text-text-muted mt-1">
                          Support: {dx.support}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-text-muted">
                  No ICD-10 candidates suggested.
                </p>
              )}
            </Section>

            <Section title="CPT procedures — top 3" icon={<Hash size={16} />}>
              {result.cpt_ranked && result.cpt_ranked.length > 0 ? (
                <ul className="space-y-2">
                  {result.cpt_ranked.map((cpt) => (
                    <li
                      key={cpt.code}
                      className="rounded-lg border border-line bg-surface p-3"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-ink">
                            {cpt.code}
                          </span>
                          {cpt.add_on && (
                            <span className="rounded bg-surface-high px-1.5 py-0.5 text-[10px] text-text-muted uppercase tracking-wide">
                              Add-on
                            </span>
                          )}
                          {cpt.ncci_clean ? (
                            <span className="flex items-center gap-1 text-[10px] text-success uppercase tracking-wide">
                              <CheckCircle2 size={11} aria-hidden="true" />
                              NCCI clean
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[10px] text-error uppercase tracking-wide">
                              <AlertTriangle size={11} aria-hidden="true" />
                              NCCI flag
                            </span>
                          )}
                        </div>
                        <ConfidenceBar value={cpt.confidence} />
                      </div>
                      {cpt.name && (
                        <p className="text-sm text-ink mt-0.5">{cpt.name}</p>
                      )}
                      {cpt.support && (
                        <p className="text-xs text-text-muted mt-1">
                          Support: {cpt.support}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-text-muted">
                  No separately billable CPT procedures suggested.
                </p>
              )}
            </Section>
          </div>

          {/* Modifier suggestions */}
          <Section title="Modifier suggestions (25 / 59 / 95)" icon={<Hash size={16} />}>
            {result.modifiers && result.modifiers.length > 0 ? (
              <ul className="space-y-2">
                {result.modifiers.map((mod, i) => (
                  <li
                    key={`${mod.modifier}-${i}`}
                    className="rounded-lg border border-line bg-surface p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-secondary px-2 py-0.5 text-xs font-bold text-surface-lowest">
                          Mod {mod.modifier}
                        </span>
                        <span className="text-xs text-text-muted">
                          attach to{" "}
                          <span className="font-mono text-ink">
                            {mod.attach_to}
                          </span>
                        </span>
                      </div>
                      <ConfidenceBar value={mod.confidence} />
                    </div>
                    <p className="text-xs text-ink mt-1.5">{mod.reason}</p>
                    {mod.requires && (
                      <p className="text-xs text-warning mt-1">
                        Requires: {mod.requires}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-text-muted">
                No modifiers suggested for this code set.
              </p>
            )}
          </Section>

          {/* Final not-submitted reminder */}
          <p className="flex items-center gap-1.5 text-xs text-text-muted">
            <Info size={13} aria-hidden="true" />
            These suggestions are not auto-submitted. Confirm documentation
            supports each code before billing.
          </p>
        </>
      )}
    </div>
  );
}
