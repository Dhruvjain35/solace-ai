import { useEffect, useMemo, useState } from "react";
import {
  FileText,
  Sparkles,
  Loader2,
  AlertTriangle,
  BookOpen,
  Heart,
  ShieldAlert,
} from "lucide-react";
import { listLetterTemplates } from "../../../lib/api";
import {
  getLetterCategories,
  generateLetter,
  generateHandout,
  type LetterCategory,
  type LetterResult,
  type EducationHandout,
} from "../../../lib/api-letters";
import { usePatientWorkspace } from "../PatientWorkspaceContext";
import type { PatientDetail } from "../../../types";

/**
 * LettersTab — letter / form generation and patient-education handouts for the
 * workspace patient.
 *
 * The defining behaviour: chart_context is assembled automatically from the
 * loaded `patient` record (demographics, dx codes, last-visit summary). The
 * clinician never hand-types chart context — one-click generate pulls slots
 * from that derived context server-side. Trimmed from pages/ClinicianLetters.
 */

type Tpl = { key: string; name: string; audience: string; slots: string[]; category?: string };

const ALL_CATEGORIES = "__all__";

/**
 * Build the chart_context object for letter generation directly from the
 * patient record. Backend slot autofill keys off these well-known field names,
 * so the clinician gets a populated letter with zero typing.
 */
function buildChartContext(patient: PatientDetail): Record<string, unknown> {
  const med = patient.medical_info;
  const diff = patient.differential || [];
  const primaryDx = diff[0];

  const diagnoses = diff.map((d) => d.diagnosis).filter(Boolean);
  const icd10Codes = diff.map((d) => d.icd10).filter(Boolean);
  const conditions = med?.conditions || [];
  const medications = (patient.prescriptions || []).map((p) => p.drug).filter(Boolean);
  const lastVisitSummary =
    patient.clinical_scribe_note ||
    patient.clinician_prebrief ||
    patient.triage_recommendation ||
    "";

  const ctx: Record<string, unknown> = {
    patient_name: patient.name,
    patient_age: med?.age ?? null,
    patient_sex: med?.sex ?? null,
    chief_complaint: patient.triage_recommendation || "",
    diagnosis: primaryDx?.diagnosis || conditions[0] || "",
    icd10: primaryDx?.icd10 || "",
    diagnoses,
    icd10_codes: icd10Codes,
    conditions,
    medications: medications.length ? medications : med?.medications || [],
    allergies: med?.allergies || [],
    esi_level: patient.esi_level,
    esi_label: patient.esi_label,
    visit_date: patient.created_at,
    last_visit_summary: lastVisitSummary,
    disposition: patient.disposition?.disposition || "",
    return_precautions: patient.disposition?.return_precautions || [],
  };

  // Drop empty values so the backend autofill doesn't overwrite slots with blanks.
  return Object.fromEntries(
    Object.entries(ctx).filter(([, v]) => {
      if (v == null || v === "") return false;
      if (Array.isArray(v) && v.length === 0) return false;
      return true;
    }),
  );
}

/** A short, human-readable preview of what the auto-built context contains. */
function contextSummary(ctx: Record<string, unknown>): string[] {
  const lines: string[] = [];
  if (ctx.patient_name) lines.push(`Patient: ${String(ctx.patient_name)}`);
  if (ctx.patient_age != null || ctx.patient_sex) {
    lines.push(
      `Demographics: ${ctx.patient_age != null ? `${ctx.patient_age}y` : "age n/a"}` +
        `${ctx.patient_sex ? ` ${String(ctx.patient_sex)}` : ""}`,
    );
  }
  if (ctx.diagnosis) lines.push(`Primary dx: ${String(ctx.diagnosis)}`);
  if (Array.isArray(ctx.icd10_codes) && ctx.icd10_codes.length) {
    lines.push(`ICD-10: ${(ctx.icd10_codes as string[]).join(", ")}`);
  }
  if (ctx.last_visit_summary) lines.push("Last-visit summary attached");
  return lines;
}

export default function LettersTab() {
  const { hospitalId, patient, loading, error } = usePatientWorkspace();

  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [categories, setCategories] = useState<LetterCategory[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string>(ALL_CATEGORIES);
  const [active, setActive] = useState<Tpl | null>(null);
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState("");
  const [missingRequired, setMissingRequired] = useState<string[]>([]);
  const [missingOptional, setMissingOptional] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Patient-education handout state.
  const [handoutCondition, setHandoutCondition] = useState("");
  const [handout, setHandout] = useState<EducationHandout | null>(null);
  const [handoutBusy, setHandoutBusy] = useState(false);
  const [handoutError, setHandoutError] = useState<string | null>(null);
  const [handoutPrefilled, setHandoutPrefilled] = useState(false);

  useEffect(() => {
    listLetterTemplates(hospitalId).then(setTemplates).catch(() => {});
    getLetterCategories(hospitalId).then(setCategories).catch(() => {});
  }, [hospitalId]);

  // Chart context auto-built from the workspace patient — recomputed only when
  // the patient record changes. This is the whole point of the workspace: the
  // clinician never hand-types this.
  const chartContext = useMemo(
    () => (patient ? buildChartContext(patient) : null),
    [patient],
  );

  // Pre-fill the handout condition from the patient's complaint / diagnosis.
  useEffect(() => {
    if (!patient || handoutPrefilled) return;
    const med = patient.medical_info;
    const guess =
      patient.differential?.[0]?.diagnosis ||
      med?.conditions?.[0] ||
      patient.triage_recommendation ||
      "";
    if (guess) {
      setHandoutCondition(guess);
      setHandoutPrefilled(true);
    }
  }, [patient, handoutPrefilled]);

  const visibleTemplates = useMemo(() => {
    if (categoryFilter === ALL_CATEGORIES) return templates;
    return templates.filter((t) => t.category === categoryFilter);
  }, [templates, categoryFilter]);

  const choose = (t: Tpl) => {
    setActive(t);
    const empty: Record<string, string> = {};
    t.slots.forEach((s) => {
      empty[s] = "";
    });
    setSlots(empty);
    setRendered("");
    setMissingRequired([]);
    setMissingOptional([]);
    setErrorMsg(null);
  };

  // One-click generate — sends the auto-built chart context so the backend
  // fills slots server-side, then surfaces any missing required slots.
  const generate = async () => {
    if (!active || !chartContext) return;
    setGenerating(true);
    setErrorMsg(null);
    try {
      const r: LetterResult = await generateLetter(hospitalId, {
        template_key: active.key,
        chart_context: chartContext,
      });
      setSlots(r.slots);
      setRendered(r.rendered);
      setMissingRequired(r.missing_required || []);
      setMissingOptional(r.missing_optional || []);
      if (r.error) {
        setErrorMsg("Generation reported an issue: " + r.error);
      }
    } catch (e: any) {
      setErrorMsg(
        "Couldn't generate the letter: " +
          (e?.response?.data?.detail || e?.message || "please try again."),
      );
    } finally {
      setGenerating(false);
    }
  };

  const buildHandout = async () => {
    const condition = handoutCondition.trim();
    if (!condition) {
      setHandoutError("Enter a condition to generate a handout.");
      return;
    }
    setHandoutBusy(true);
    setHandoutError(null);
    try {
      const h = await generateHandout(hospitalId, {
        condition,
        reading_level: "standard",
        patient_language: patient?.language || undefined,
        patient_context: chartContext || undefined,
      });
      setHandout(h);
    } catch (e: any) {
      setHandoutError(
        "Couldn't build the handout: " +
          (e?.response?.data?.detail || e?.message || "please try again."),
      );
    } finally {
      setHandoutBusy(false);
    }
  };

  // --- Guards (loading / error / no patient) before any patient access. ---
  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-text-muted text-sm">
        <Loader2 size={18} className="animate-spin mr-2" aria-hidden="true" />
        Loading patient record…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
    );
  }

  if (!patient || !chartContext) {
    return (
      <div className="text-text-muted text-sm py-8">No patient record available.</div>
    );
  }

  const summary = contextSummary(chartContext);

  return (
    <div className="space-y-4">
      {errorMsg && (
        <div
          role="alert"
          className="flex items-start gap-2 p-3 rounded-lg bg-error-container text-sm text-error"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            aria-label="Dismiss error"
            className="text-xs font-semibold uppercase tracking-wide rounded text-error/70 hover:text-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error/40"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Template picker */}
        <div className="bg-surface-lowest rounded-xl shadow-card p-3">
          <h2 className="text-xs uppercase tracking-wide text-text-muted mb-2">
            Templates
          </h2>

          {categories.length > 0 && (
            <div className="mb-3">
              <label
                htmlFor="letter-category"
                className="block text-xs text-text-muted mb-1"
              >
                Category
              </label>
              <select
                id="letter-category"
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="w-full px-2 py-1.5 rounded-md text-sm bg-surface-lowest border border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary"
              >
                <option value={ALL_CATEGORIES}>All categories</option>
                {categories.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="space-y-1">
            {visibleTemplates.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => choose(t)}
                aria-pressed={active?.key === t.key}
                className={`w-full text-left px-3 py-2 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 transition-colors ${
                  active?.key === t.key
                    ? "bg-primary-dim text-primary"
                    : "hover:bg-surface-low"
                }`}
              >
                <div className="font-medium">{t.name}</div>
                <div className="text-xs text-text-muted">{t.audience}</div>
              </button>
            ))}
            {visibleTemplates.length === 0 && (
              <div className="px-3 py-4 text-xs text-text-muted">
                No templates in this category.
              </div>
            )}
          </div>
        </div>

        {/* Working area */}
        <div className="lg:col-span-3 space-y-3">
          {/* Auto-built chart context — clinician never types this. */}
          <div className="bg-surface-lowest rounded-xl shadow-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <Sparkles size={16} className="text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Chart context (auto-built)</h2>
            </div>
            <p className="text-xs text-text-muted mb-2">
              Pulled straight from {patient.name}&apos;s record — demographics,
              diagnoses, and last-visit summary. No typing required.
            </p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-text-muted">
              {summary.map((line) => (
                <li key={line} className="flex items-start gap-1.5">
                  <span aria-hidden="true" className="text-primary">
                    •
                  </span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </div>

          {!active && (
            <div className="bg-surface-lowest rounded-xl shadow-card p-12 text-center text-text-muted">
              <FileText
                size={40}
                className="mx-auto mb-3 opacity-40"
                aria-hidden="true"
              />
              Pick a letter template on the left to generate it for this patient.
            </div>
          )}

          {active && (
            <>
              <div className="bg-surface-lowest rounded-xl shadow-card p-4">
                <div className="flex items-center justify-between gap-3 mb-1">
                  <div>
                    <h2 className="text-sm font-semibold">{active.name}</h2>
                    <div className="text-xs text-text-muted">{active.audience}</div>
                  </div>
                  <button
                    type="button"
                    onClick={generate}
                    disabled={generating}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-md text-sm bg-primary text-surface-lowest hover:bg-primary-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 transition-colors"
                  >
                    {generating ? (
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                    ) : (
                      <Sparkles size={14} aria-hidden="true" />
                    )}
                    One-click generate
                  </button>
                </div>
                <p className="text-xs text-text-muted">
                  Generation fills slots from the auto-built chart context above.
                </p>
              </div>

              {missingRequired.length > 0 && (
                <div
                  role="alert"
                  className="flex items-start gap-2 p-3 rounded-lg bg-warning-container text-sm text-warning"
                >
                  <AlertTriangle
                    size={16}
                    className="mt-0.5 shrink-0"
                    aria-hidden="true"
                  />
                  <div>
                    <div className="font-semibold">
                      Required information still missing
                    </div>
                    <div className="mt-0.5">
                      The chart didn&apos;t supply: {missingRequired.join(", ")}.
                      Fill these slots below before sending.
                    </div>
                  </div>
                </div>
              )}
              {missingRequired.length === 0 && missingOptional.length > 0 && (
                <div className="p-3 rounded-lg bg-surface-low text-xs text-text-muted">
                  Optional slots left blank: {missingOptional.join(", ")}
                </div>
              )}

              <div className="bg-surface-lowest rounded-xl shadow-card p-4">
                <div className="text-xs uppercase tracking-wide text-text-muted mb-2">
                  Slots
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {active.slots.map((s) => {
                    const isMissing = missingRequired.includes(s);
                    return (
                      <div key={s}>
                        <label
                          htmlFor={`letter-slot-${s}`}
                          className="block text-xs text-text-muted"
                        >
                          {s}
                          {isMissing && (
                            <span className="text-warning font-semibold">
                              {" "}
                              (required)
                            </span>
                          )}
                        </label>
                        <input
                          id={`letter-slot-${s}`}
                          value={slots[s] || ""}
                          onChange={(e) =>
                            setSlots({ ...slots, [s]: e.target.value })
                          }
                          className={`w-full px-2 py-1.5 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary ${
                            isMissing
                              ? "border border-warning bg-warning-container"
                              : "border border-line"
                          }`}
                        />
                      </div>
                    );
                  })}
                  {active.slots.length === 0 && (
                    <div className="text-xs text-text-muted">
                      This template has no editable slots.
                    </div>
                  )}
                </div>
              </div>

              {rendered && (
                <div className="bg-surface-lowest rounded-xl shadow-card p-4">
                  <div className="text-xs uppercase tracking-wide text-text-muted mb-2">
                    Letter preview
                  </div>
                  <pre className="whitespace-pre-wrap font-body text-sm leading-relaxed text-ink">
                    {rendered}
                  </pre>
                </div>
              )}
            </>
          )}

          {/* Patient-education handout */}
          <div className="bg-surface-lowest rounded-xl shadow-card p-4">
            <div className="flex items-center gap-2 mb-1">
              <BookOpen size={16} className="text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Patient education handout</h2>
            </div>
            <p className="text-xs text-text-muted mb-3">
              A plain-language handout the patient can take home. Pre-filled from
              this patient&apos;s complaint and diagnosis — adjust if needed.
            </p>
            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex-1">
                <label htmlFor="handout-condition" className="sr-only">
                  Condition
                </label>
                <input
                  id="handout-condition"
                  value={handoutCondition}
                  onChange={(e) => setHandoutCondition(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") buildHandout();
                  }}
                  placeholder="e.g. Type 2 diabetes, Hypertension, Asthma"
                  className="w-full px-3 py-1.5 rounded-md text-sm border border-line focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary"
                />
              </div>
              <button
                type="button"
                onClick={buildHandout}
                disabled={handoutBusy}
                className="flex items-center justify-center gap-1.5 px-4 py-1.5 rounded-md text-sm bg-primary text-surface-lowest hover:bg-primary-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 transition-colors"
              >
                {handoutBusy ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={14} aria-hidden="true" />
                )}
                Generate handout
              </button>
            </div>

            {handoutError && (
              <div
                role="alert"
                className="mt-3 flex items-start gap-2 p-2 rounded-md bg-error-container text-sm text-error"
              >
                <AlertTriangle
                  size={16}
                  className="mt-0.5 shrink-0"
                  aria-hidden="true"
                />
                <span>{handoutError}</span>
              </div>
            )}

            {handout && (
              <article className="mt-4 border-t border-line pt-4 space-y-4">
                <header>
                  <h3 className="text-base font-semibold text-ink">
                    {handout.title}
                  </h3>
                  <div className="text-xs text-text-muted">{handout.condition}</div>
                </header>

                {handout.overview && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      Overview
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.overview}
                    </p>
                  </section>
                )}

                {handout.why_it_happens && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      Why it happens
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.why_it_happens}
                    </p>
                  </section>
                )}

                {handout.what_to_expect && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      What to expect
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.what_to_expect}
                    </p>
                  </section>
                )}

                {handout.self_care.length > 0 && (
                  <section>
                    <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-text-muted mb-1">
                      <Heart
                        size={14}
                        className="text-success"
                        aria-hidden="true"
                      />
                      Self-care
                    </h4>
                    <ul className="list-disc pl-5 space-y-1 text-sm text-ink">
                      {handout.self_care.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  </section>
                )}

                {handout.medication_notes && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      Medication notes
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.medication_notes}
                    </p>
                  </section>
                )}

                {handout.red_flags.length > 0 && (
                  <section className="p-3 rounded-lg bg-error-container">
                    <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-error mb-1">
                      <ShieldAlert size={14} aria-hidden="true" />
                      Warning signs
                    </h4>
                    <ul className="list-disc pl-5 space-y-1 text-sm text-error">
                      {handout.red_flags.map((item, i) => (
                        <li key={i}>{item}</li>
                      ))}
                    </ul>
                  </section>
                )}

                {handout.when_to_seek_care && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      When to seek care
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.when_to_seek_care}
                    </p>
                  </section>
                )}

                {handout.follow_up && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-text-muted mb-1">
                      Follow-up
                    </h4>
                    <p className="text-sm leading-relaxed text-ink">
                      {handout.follow_up}
                    </p>
                  </section>
                )}

                {handout.closing && (
                  <p className="text-sm italic text-text-muted">
                    {handout.closing}
                  </p>
                )}
              </article>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
