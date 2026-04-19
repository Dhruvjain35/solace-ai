import { useEffect, useState } from "react";
import { Check, Loader2, Send, StickyNote } from "lucide-react";
import { createNote, publishPatientSummary } from "../../lib/api";
import type { ClinicianNote, PatientEducation } from "../../types";

type Props = {
  hospitalId: string;
  patientId: string;
  pin: string;
  initialNotes: ClinicianNote[];
  initialEducation: PatientEducation | null;
  publishedAt: string | null;
};

export function NotesPanel({
  hospitalId,
  patientId,
  pin,
  initialNotes,
  initialEducation,
  publishedAt,
}: Props) {
  const [notes, setNotes] = useState<ClinicianNote[]>(initialNotes);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [education, setEducation] = useState<PatientEducation | null>(initialEducation);
  const [publishedTs, setPublishedTs] = useState<string | null>(publishedAt);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setNotes(initialNotes);
    setEducation(initialEducation);
    setPublishedTs(publishedAt);
  }, [initialNotes, initialEducation, publishedAt, patientId]);

  async function saveNote() {
    if (!draft.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const note = await createNote(hospitalId, patientId, pin, draft.trim());
      setNotes((prev) => [...prev, note]);
      setDraft("");
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Could not save note.");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    setPublishing(true);
    setError(null);
    try {
      const summary = await publishPatientSummary(hospitalId, patientId, pin);
      setEducation(summary);
      setPublishedTs(new Date().toISOString());
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Could not publish summary.");
    } finally {
      setPublishing(false);
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-[0.14em] text-text-muted font-semibold">
          Clinician notes
        </div>
        {notes.length > 0 && (
          <button
            type="button"
            onClick={publish}
            disabled={publishing}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-white text-xs font-medium disabled:opacity-50"
          >
            {publishing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {publishedTs ? "Republish to patient" : "Publish to patient"}
          </button>
        )}
      </div>

      <div className="flex flex-col gap-2">
        {notes.length === 0 ? (
          <div className="text-sm text-text-muted bg-surface-low rounded-lg p-3 flex items-start gap-2">
            <StickyNote size={14} className="mt-0.5 shrink-0" />
            No notes yet. Add what you observed, what you're ordering, or how you explained it.
          </div>
        ) : (
          notes.map((n) => (
            <div key={n.note_id} className="bg-surface-lowest rounded-lg p-3 shadow-soft">
              <div className="text-sm whitespace-pre-wrap leading-relaxed">{n.text}</div>
              <div className="text-[10px] text-text-muted mt-1 font-mono">
                {n.author} · {new Date(n.created_at).toLocaleTimeString()}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="mt-3">
        <textarea
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Add a note… (what you saw, your plan, what you told the patient)"
          className="w-full p-3 rounded-md bg-surface-lowest ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none transition-all resize-y"
        />
        <div className="flex items-center gap-2 mt-2">
          <button
            type="button"
            onClick={saveNote}
            disabled={!draft.trim() || saving}
            className="inline-flex items-center gap-1.5 h-9 px-4 rounded-md bg-primary text-white text-sm font-medium disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Save note
          </button>
        </div>
      </div>

      {education && (
        <div className="mt-4 bg-primary-fixed/40 rounded-lg p-3">
          <div className="text-[11px] uppercase tracking-[0.14em] text-primary font-semibold mb-1">
            Patient-facing summary {publishedTs && `· ${new Date(publishedTs).toLocaleTimeString()}`}
          </div>
          <div className="text-sm font-semibold">{education.headline}</div>
          <div className="text-sm mt-1">{education.what_we_are_doing}</div>
          {education.things_to_do_at_home?.length > 0 && (
            <ul className="text-sm mt-2 list-disc ml-5">
              {education.things_to_do_at_home.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          )}
          <div className="text-sm mt-2">
            <span className="font-semibold">When to come back: </span>
            {education.when_to_come_back}
          </div>
          <div className="text-sm italic mt-2 text-text-muted">{education.closing}</div>
        </div>
      )}

      {error && (
        <div className="mt-3 p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
      )}
    </section>
  );
}
