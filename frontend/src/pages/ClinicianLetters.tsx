import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FileText, Sparkles, Printer, Loader2 } from "lucide-react";
import { listLetterTemplates, autofillLetter, renderLetter, letterPdfUrl } from "../lib/api";

type Tpl = { key: string; name: string; audience: string; slots: string[] };

export default function ClinicianLetters() {
  const { hospitalId = "demo" } = useParams();
  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [active, setActive] = useState<Tpl | null>(null);
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState("");
  const [contextJson, setContextJson] = useState('{\n  "patient_name": "Jane Doe",\n  "patient_dob": "1985-03-21",\n  "diagnosis": "Major depressive disorder",\n  "icd10": "F32.9"\n}');
  const [busy, setBusy] = useState(false);

  useEffect(() => { listLetterTemplates(hospitalId).then(setTemplates).catch(() => {}); }, [hospitalId]);

  const choose = (t: Tpl) => {
    setActive(t);
    const empty: Record<string, string> = {};
    t.slots.forEach((s) => { empty[s] = ""; });
    setSlots(empty);
    setRendered("");
  };

  const autofill = async () => {
    if (!active) return;
    setBusy(true);
    try {
      const ctx = JSON.parse(contextJson || "{}");
      const r = await autofillLetter(hospitalId, active.key, ctx);
      setSlots(r.slots);
      setRendered(r.rendered);
    } catch (e: any) {
      alert("Autofill failed: " + (e?.message || ""));
    } finally { setBusy(false); }
  };

  const reRender = async () => {
    if (!active) return;
    const r = await renderLetter(hospitalId, active.key, slots);
    setRendered(r);
  };

  const downloadPdf = async () => {
    if (!active) return;
    const url = await letterPdfUrl(hospitalId, active.key, slots);
    const a = document.createElement("a");
    a.href = url; a.download = `${active.key}.pdf`;
    document.body.appendChild(a); a.click(); a.remove();
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to={`/${hospitalId}/clinician`} className="text-slate-500 hover:text-slate-900"><ArrowLeft className="w-5 h-5" /></Link>
          <div>
            <div className="text-sm text-slate-500">Solace document automation</div>
            <div className="font-semibold">Letters and forms</div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-4 grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border border-slate-200 p-3">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Templates</div>
          <div className="space-y-1">
            {templates.map((t) => (
              <button
                key={t.key}
                onClick={() => choose(t)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm ${active?.key === t.key ? "bg-blue-50 border border-blue-200 text-blue-900" : "hover:bg-slate-100"}`}
              >
                <div className="font-medium">{t.name}</div>
                <div className="text-xs text-slate-500">{t.audience}</div>
              </button>
            ))}
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
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Chart context (JSON)</div>
                <textarea
                  value={contextJson}
                  onChange={(e) => setContextJson(e.target.value)}
                  rows={6}
                  className="w-full font-mono text-xs px-3 py-2 border border-slate-300 rounded-md"
                />
                <div className="mt-2 flex gap-2">
                  <button onClick={autofill} disabled={busy} className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1">
                    {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} AI autofill
                  </button>
                </div>
              </div>

              <div className="bg-white rounded-lg border border-slate-200 p-4">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Slots</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {active.slots.map((s) => (
                    <div key={s}>
                      <label className="block text-xs text-slate-500">{s}</label>
                      <input
                        value={slots[s] || ""}
                        onChange={(e) => setSlots({ ...slots, [s]: e.target.value })}
                        className="w-full px-2 py-1 border border-slate-300 rounded text-sm"
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex gap-2">
                  <button onClick={reRender} className="bg-slate-900 text-white px-4 py-1.5 rounded text-sm">Render</button>
                  <button onClick={downloadPdf} className="bg-emerald-600 text-white px-4 py-1.5 rounded text-sm flex items-center gap-1">
                    <Printer className="w-3 h-3" /> Download PDF
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
        </div>
      </div>
    </div>
  );
}
