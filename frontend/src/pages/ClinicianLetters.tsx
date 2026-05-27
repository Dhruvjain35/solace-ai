import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  FileText,
  Sparkles,
  Printer,
  Loader2,
  AlertTriangle,
  BookOpen,
  Heart,
  ShieldAlert,
} from "lucide-react";
import { listLetterTemplates, autofillLetter, renderLetter, letterPdfUrl } from "../lib/api";
import {
  getLetterCategories,
  generateLetter,
  generateHandout,
  type LetterCategory,
  type LetterResult,
  type EducationHandout,
} from "../lib/api-letters";

type Tpl = { key: string; name: string; audience: string; slots: string[]; category?: string };

const ALL_CATEGORIES = "__all__";

export default function ClinicianLetters() {
  const { hospitalId = "demo" } = useParams();
  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [categories, setCategories] = useState<LetterCategory[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string>(ALL_CATEGORIES);
  const [active, setActive] = useState<Tpl | null>(null);
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState("");
  const [missingRequired, setMissingRequired] = useState<string[]>([]);
  const [missingOptional, setMissingOptional] = useState<string[]>([]);
  const [contextJson, setContextJson] = useState('{\n  "patient_name": "Jane Doe",\n  "patient_dob": "1985-03-21",\n  "diagnosis": "Major depressive disorder",\n  "icd10": "F32.9"\n}');
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  // Inline error banner — replaces native alert() so failures are dismissable
  // and don't break the clinician's flow (CONSTITUTION USAB-001).
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Patient education handout state
  const [handoutCondition, setHandoutCondition] = useState("");
  const [handout, setHandout] = useState<EducationHandout | null>(null);
  const [handoutBusy, setHandoutBusy] = useState(false);
  const [handoutError, setHandoutError] = useState<string | null>(null);

  useEffect(() => {
    listLetterTemplates(hospitalId).then(setTemplates).catch(() => {});
    getLetterCategories(hospitalId).then(setCategories).catch(() => {});
  }, [hospitalId]);

  const visibleTemplates = useMemo(() => {
    if (categoryFilter === ALL_CATEGORIES) return templates;
    return templates.filter((t) => t.category === categoryFilter);
  }, [templates, categoryFilter]);

  const choose = (t: Tpl) => {
    setActive(t);
    const empty: Record<string, string> = {};
    t.slots.forEach((s) => { empty[s] = ""; });
    setSlots(empty);
    setRendered("");
    setMissingRequired([]);
    setMissingOptional([]);
  };

  const parseContext = (): Record<string, unknown> | null => {
    try {
      return JSON.parse(contextJson || "{}") as Record<string, unknown>;
    } catch {
      setErrorMsg("Chart context isn't valid JSON. Check for a missing comma or quote.");
      return null;
    }
  };

  const autofill = async () => {
    if (!active) return;
    setBusy(true);
    setErrorMsg(null);
    const ctx = parseContext();
    if (ctx === null) { setBusy(false); return; }
    try {
      const r = await autofillLetter(hospitalId, active.key, ctx);
      setSlots(r.slots);
      setRendered(r.rendered);
    } catch (e: any) {
      setErrorMsg("Autofill failed: " + (e?.response?.data?.detail || e?.message || "please try again."));
    } finally { setBusy(false); }
  };

  // One-click generate — pulls slots from chart context server-side, renders the
  // letter, and surfaces missing-required slots so the clinician can fill the gaps.
  const generate = async () => {
    if (!active) return;
    setGenerating(true);
    setErrorMsg(null);
    const ctx = parseContext();
    if (ctx === null) { setGenerating(false); return; }
    try {
      const r: LetterResult = await generateLetter(hospitalId, {
        template_key: active.key,
        chart_context: ctx,
      });
      setSlots(r.slots);
      setRendered(r.rendered);
      setMissingRequired(r.missing_required || []);
      setMissingOptional(r.missing_optional || []);
      if (r.error) {
        setErrorMsg("Generation reported an issue: " + r.error);
      }
    } catch (e: any) {
      setErrorMsg("Couldn't generate the letter: " + (e?.response?.data?.detail || e?.message || "please try again."));
    } finally { setGenerating(false); }
  };

  const reRender = async () => {
    if (!active) return;
    setErrorMsg(null);
    try {
      const r = await renderLetter(hospitalId, active.key, slots);
      setRendered(r);
    } catch (e: any) {
      setErrorMsg("Couldn't render the letter: " + (e?.response?.data?.detail || e?.message || "please try again."));
    }
  };

  const downloadPdf = async () => {
    if (!active) return;
    setErrorMsg(null);
    try {
      const url = await letterPdfUrl(hospitalId, active.key, slots);
      const a = document.createElement("a");
      a.href = url; a.download = `${active.key}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
    } catch (e: any) {
      setErrorMsg("Couldn't generate the PDF: " + (e?.response?.data?.detail || e?.message || "please try again."));
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
      const h = await generateHandout(hospitalId, { condition, reading_level: "standard" });
      setHandout(h);
    } catch (e: any) {
      setHandoutError("Couldn't build the handout: " + (e?.response?.data?.detail || e?.message || "please try again."));
    } finally { setHandoutBusy(false); }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} aria-label="Back to dashboard" className="rounded-md p-1 text-slate-500 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors"><ArrowLeft className="w-5 h-5" aria-hidden="true" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace document automation</div>
            <div className="font-semibold">Letters and forms</div>
          </div>
        </div>
      </div>

      {errorMsg && (
        <div role="alert" className="bg-rose-50 border-b border-rose-200 px-4 py-2 flex items-start gap-2 text-sm text-rose-900">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
          <div className="flex-1">{errorMsg}</div>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            aria-label="Dismiss error"
            className="rounded text-rose-700/70 hover:text-rose-900 text-xs font-semibold uppercase tracking-wide focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="max-w-7xl mx-auto p-4 grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border border-slate-200 p-3">
          <h2 className="text-xs uppercase tracking-wide text-slate-500 mb-2">Templates</h2>

          {categories.length > 0 && (
            <div className="mb-3">
              <label htmlFor="letter-category" className="block text-xs text-slate-500 mb-1">Category</label>
              <select
                id="letter-category"
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="w-full px-2 py-1.5 border border-slate-300 rounded text-sm bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500"
              >
                <option value={ALL_CATEGORIES}>All categories</option>
                {categories.map((c) => (
                  <option key={c.key} value={c.key}>{c.label}</option>
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
                className={`w-full text-left px-3 py-2 rounded-md text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 transition-colors ${active?.key === t.key ? "bg-blue-50 border border-blue-200 text-blue-900" : "hover:bg-slate-100"}`}
              >
                <div className="font-medium">{t.name}</div>
                <div className="text-xs text-slate-500">{t.audience}</div>
              </button>
            ))}
            {visibleTemplates.length === 0 && (
              <div className="px-3 py-4 text-xs text-slate-400">No templates in this category.</div>
            )}
          </div>
        </div>

        <div className="lg:col-span-3 space-y-3">
          {!active && (
            <div className="bg-white rounded-lg border border-slate-200 p-12 text-center text-slate-500">
              <FileText className="w-10 h-10 mx-auto mb-3 text-slate-300" />
              Pick a template on the left.
            </div>
          )}

          {active && (
            <>
              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <label htmlFor="letter-context" className="block text-xs uppercase tracking-wide text-slate-500 mb-1">Chart context (JSON)</label>
                <textarea
                  id="letter-context"
                  value={contextJson}
                  onChange={(e) => setContextJson(e.target.value)}
                  rows={6}
                  spellCheck={false}
                  className="w-full font-mono text-xs px-3 py-2 border border-slate-300 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500"
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <button type="button" onClick={generate} disabled={generating || busy} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1 hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">
                    {generating ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Sparkles className="w-3 h-3" aria-hidden="true" />} One-click generate
                  </button>
                  <button type="button" onClick={autofill} disabled={busy || generating} className="bg-white border border-slate-300 text-slate-700 px-4 py-1.5 rounded text-sm flex items-center gap-1 hover:bg-slate-100 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors">
                    {busy ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Sparkles className="w-3 h-3" aria-hidden="true" />} AI autofill
                  </button>
                </div>
              </div>

              {missingRequired.length > 0 && (
                <div role="alert" className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2 text-sm text-amber-900">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                  <div>
                    <div className="font-semibold">Required information still missing</div>
                    <div className="text-amber-800 mt-0.5">
                      Fill these slots before sending: {missingRequired.join(", ")}
                    </div>
                  </div>
                </div>
              )}
              {missingRequired.length === 0 && missingOptional.length > 0 && (
                <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-600">
                  Optional slots left blank: {missingOptional.join(", ")}
                </div>
              )}

              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Slots</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {active.slots.map((s) => {
                    const isMissing = missingRequired.includes(s);
                    return (
                      <div key={s}>
                        <label htmlFor={`letter-slot-${s}`} className="block text-xs text-slate-500">
                          {s}{isMissing && <span className="text-amber-600 font-semibold"> (required)</span>}
                        </label>
                        <input
                          id={`letter-slot-${s}`}
                          value={slots[s] || ""}
                          onChange={(e) => setSlots({ ...slots, [s]: e.target.value })}
                          className={`w-full px-2 py-1 border rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500 ${isMissing ? "border-amber-400 bg-amber-50" : "border-slate-300"}`}
                        />
                      </div>
                    );
                  })}
                </div>
                <div className="mt-3 flex gap-2">
                  <button type="button" onClick={reRender} className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500/50 focus-visible:ring-offset-2 transition-colors">Render</button>
                  <button type="button" onClick={downloadPdf} className="bg-emerald-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1 hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 focus-visible:ring-offset-2 transition-colors">
                    <Printer className="w-3 h-3" aria-hidden="true" /> Download PDF
                  </button>
                </div>
              </div>

              {rendered && (
                <div className="bg-white rounded-lg border border-slate-200 p-4">
                  <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Preview</div>
                  <pre className="whitespace-pre-wrap font-serif text-sm leading-relaxed">{rendered}</pre>
                </div>
              )}
            </>
          )}

          {/* Patient education handout — patient-facing copy, no emoji (QUAL-004). */}
          <div className="bg-white rounded-lg border border-slate-200 p-4">
            <div className="flex items-center gap-2 mb-1">
              <BookOpen className="w-4 h-4 text-blue-600" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Patient education handout</h2>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Generate a plain-language handout the patient can take home. Enter a condition or diagnosis.
            </p>
            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex-1">
                <label htmlFor="handout-condition" className="sr-only">Condition</label>
                <input
                  id="handout-condition"
                  value={handoutCondition}
                  onChange={(e) => setHandoutCondition(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") buildHandout(); }}
                  placeholder="e.g. Type 2 diabetes, Hypertension, Asthma"
                  className="w-full px-3 py-1.5 border border-slate-300 rounded text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:border-blue-500"
                />
              </div>
              <button
                type="button"
                onClick={buildHandout}
                disabled={handoutBusy}
                className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center justify-center gap-1 hover:bg-blue-700 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 transition-colors"
              >
                {handoutBusy ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" /> : <Sparkles className="w-3 h-3" aria-hidden="true" />} Generate handout
              </button>
            </div>

            {handoutError && (
              <div role="alert" className="mt-3 bg-rose-50 border border-rose-200 rounded p-2 flex items-start gap-2 text-sm text-rose-900">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                <span>{handoutError}</span>
              </div>
            )}

            {handout && (
              <article className="mt-4 border-t border-slate-200 pt-4 space-y-4">
                <header>
                  <h3 className="text-base font-semibold text-slate-900">{handout.title}</h3>
                  <div className="text-xs text-slate-500">{handout.condition}</div>
                </header>

                {handout.overview && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">Overview</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.overview}</p>
                  </section>
                )}

                {handout.why_it_happens && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">Why it happens</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.why_it_happens}</p>
                  </section>
                )}

                {handout.what_to_expect && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">What to expect</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.what_to_expect}</p>
                  </section>
                )}

                {handout.self_care.length > 0 && (
                  <section>
                    <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-slate-500 mb-1">
                      <Heart className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" /> Self-care
                    </h4>
                    <ul className="list-disc pl-5 space-y-1 text-sm text-slate-700">
                      {handout.self_care.map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </section>
                )}

                {handout.medication_notes && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">Medication notes</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.medication_notes}</p>
                  </section>
                )}

                {handout.red_flags.length > 0 && (
                  <section className="bg-rose-50 border border-rose-200 rounded-lg p-3">
                    <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-rose-700 mb-1">
                      <ShieldAlert className="w-3.5 h-3.5" aria-hidden="true" /> Warning signs
                    </h4>
                    <ul className="list-disc pl-5 space-y-1 text-sm text-rose-900">
                      {handout.red_flags.map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  </section>
                )}

                {handout.when_to_seek_care && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">When to seek care</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.when_to_seek_care}</p>
                  </section>
                )}

                {handout.follow_up && (
                  <section>
                    <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-1">Follow-up</h4>
                    <p className="text-sm leading-relaxed text-slate-700">{handout.follow_up}</p>
                  </section>
                )}

                {handout.closing && (
                  <p className="text-sm italic text-slate-500">{handout.closing}</p>
                )}
              </article>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
