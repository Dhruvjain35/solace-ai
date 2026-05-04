import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Calendar, Check, Loader2, Phone, User } from "lucide-react";
import {
  getAppointmentAvailability,
  bookAppointment,
  type AppointmentSlot,
  type Appointment,
} from "../lib/api";

/**
 * Patient self-scheduling.
 *
 * Three-step flow:
 *   1. Pick a slot (filterable by day)
 *   2. Enter name + phone + reason
 *   3. Confirmation with code (and optional SMS confirmation if Twilio is wired)
 *
 * No auth — anyone with the QR / link can book. Quota throttle applies via the
 * backend identity-based rate limit, same as patient intake.
 */
export default function PatientSchedule() {
  const { hospitalId = "demo" } = useParams<{ hospitalId: string }>();
  const [slots, setSlots] = useState<AppointmentSlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [chosen, setChosen] = useState<AppointmentSlot | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Appointment | null>(null);

  useEffect(() => {
    setLoading(true);
    getAppointmentAvailability(hospitalId, 7)
      .then(setSlots)
      .catch((e) => setError(e?.message || "Couldn't load availability."))
      .finally(() => setLoading(false));
  }, [hospitalId]);

  // Group slots by date for the day-strip selector.
  const dayGroups = useMemo(() => {
    const groups = new Map<string, AppointmentSlot[]>();
    for (const s of slots) {
      const day = s.iso.slice(0, 10); // YYYY-MM-DD
      groups.set(day, [...(groups.get(day) || []), s]);
    }
    return Array.from(groups.entries());
  }, [slots]);

  const [activeDay, setActiveDay] = useState<string>("");
  useEffect(() => {
    if (!activeDay && dayGroups.length > 0) setActiveDay(dayGroups[0][0]);
  }, [dayGroups, activeDay]);

  async function submit() {
    if (!chosen || !name.trim() || !phone.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await bookAppointment(hospitalId, {
        slot_iso: chosen.iso,
        patient_name: name.trim(),
        patient_phone: phone.trim(),
        reason: reason.trim(),
      });
      if (r.success) {
        setConfirmed(r.appointment);
      } else {
        setError("Couldn't book that slot — try another.");
      }
    } catch (e: any) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail;
      setError(
        status === 409
          ? "Someone just booked that slot — please pick another."
          : detail || e?.message || "Couldn't book. Try again."
      );
    } finally {
      setBusy(false);
    }
  }

  if (confirmed) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center p-6 bg-surface-low">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-md w-full bg-surface-lowest rounded-xl shadow-card p-7 flex flex-col gap-4 text-center"
        >
          <div className="h-14 w-14 rounded-full bg-success/15 text-success mx-auto flex items-center justify-center">
            <Check size={28} />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">You're booked.</h1>
          <p className="text-text-muted">
            We'll text {confirmed.patient_phone} a reminder. If you need to cancel, reply CANCEL or
            call us with this code.
          </p>
          <div className="bg-surface-low rounded-lg p-4 flex flex-col gap-1">
            <div className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">
              Confirmation
            </div>
            <div className="text-3xl font-mono font-bold tracking-[0.2em] text-primary">
              {confirmed.confirmation_code}
            </div>
            <div className="text-sm text-ink mt-2">
              {confirmed.patient_name} · {confirmed.slot_iso}
            </div>
          </div>
          <Link
            to={`/${hospitalId}`}
            className="inline-flex items-center justify-center h-11 rounded-md bg-primary text-white font-semibold text-sm shadow-soft"
          >
            Done
          </Link>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex flex-col bg-surface">
      <header className="px-4 py-4 sticky top-0 bg-surface-lowest/90 backdrop-blur-xl shadow-soft flex items-center gap-3 z-10">
        <Link
          to={`/${hospitalId}`}
          aria-label="Back to intake"
          className="w-10 h-10 rounded-full hover:bg-surface-low flex items-center justify-center"
        >
          <ArrowLeft size={20} />
        </Link>
        <img src="/solace-logo.png" alt="Solace" className="h-10 w-auto" draggable={false} />
        <div className="ml-auto inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-text-muted font-semibold">
          <Calendar size={12} /> Self-scheduling
        </div>
      </header>

      <main className="flex-1 px-4 py-6 max-w-lg w-full mx-auto flex flex-col gap-6 pb-32">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Book your visit</h1>
          <p className="text-text-muted text-sm mt-1">
            Pick a 30-minute slot. We'll text you a confirmation.
          </p>
        </div>

        {loading && (
          <div className="flex items-center gap-2 text-text-muted">
            <Loader2 size={16} className="animate-spin" /> Loading availability…
          </div>
        )}
        {error && !loading && (
          <div className="p-3 rounded-md bg-error-container text-error text-sm">{error}</div>
        )}

        {!loading && dayGroups.length === 0 && (
          <div className="p-6 rounded-lg bg-surface-low text-center text-sm text-text-muted">
            No appointments available in the next 7 days. Please call the clinic.
          </div>
        )}

        {!loading && dayGroups.length > 0 && (
          <>
            {/* Day strip */}
            <div className="flex gap-2 overflow-x-auto -mx-4 px-4 pb-1">
              {dayGroups.map(([day, daySlots]) => {
                const d = new Date(day + "T12:00:00Z");
                const isActive = day === activeDay;
                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() => setActiveDay(day)}
                    className={`flex flex-col items-center px-3 py-2 rounded-lg shrink-0 min-w-[68px] ${
                      isActive ? "bg-primary text-white shadow-soft" : "bg-surface-lowest"
                    }`}
                  >
                    <span className="text-[10px] uppercase tracking-wider font-semibold opacity-80">
                      {d.toLocaleDateString(undefined, { weekday: "short" })}
                    </span>
                    <span className="text-base font-bold">
                      {d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    </span>
                    <span className={`text-[10px] mt-0.5 ${isActive ? "opacity-80" : "text-text-muted"}`}>
                      {daySlots.length} slot{daySlots.length === 1 ? "" : "s"}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Slot grid */}
            <div className="grid grid-cols-3 gap-2">
              {(dayGroups.find((g) => g[0] === activeDay)?.[1] || []).map((s) => {
                const t = new Date(s.iso);
                const isChosen = chosen?.iso === s.iso;
                return (
                  <button
                    key={s.iso}
                    type="button"
                    onClick={() => setChosen(s)}
                    className={`h-12 rounded-md font-mono text-sm font-semibold ${
                      isChosen
                        ? "bg-primary text-white shadow-soft"
                        : "bg-surface-lowest hover:bg-primary-fixed"
                    }`}
                  >
                    {t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true })}
                  </button>
                );
              })}
            </div>

            {chosen && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-surface-lowest rounded-xl p-5 shadow-soft flex flex-col gap-3"
              >
                <div className="flex items-center gap-2 text-primary">
                  <Calendar size={14} />
                  <div className="text-[11px] uppercase tracking-wider font-bold">Selected</div>
                </div>
                <div className="text-base font-semibold">{chosen.label}</div>

                <div className="grid grid-cols-1 gap-3 mt-1">
                  <Field
                    icon={User}
                    label="Your full name"
                    value={name}
                    onChange={setName}
                    placeholder="Marcus Johnson"
                  />
                  <Field
                    icon={Phone}
                    label="Phone for the reminder"
                    value={phone}
                    onChange={setPhone}
                    placeholder="(512) 555-0177"
                    inputMode="tel"
                  />
                  <Field
                    label="Reason for visit (optional)"
                    value={reason}
                    onChange={setReason}
                    placeholder="Annual checkup"
                  />
                </div>

                <button
                  type="button"
                  onClick={submit}
                  disabled={!name.trim() || !phone.trim() || busy}
                  className="mt-1 h-12 rounded-md bg-primary text-white font-semibold text-base shadow-soft disabled:opacity-60 inline-flex items-center justify-center gap-2"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                  Confirm booking
                </button>
              </motion.div>
            )}
          </>
        )}
      </main>
    </div>
  );
}


function Field({
  label,
  value,
  onChange,
  placeholder,
  icon: Icon,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  icon?: typeof User;
  inputMode?: "tel" | "text";
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wider text-text-muted font-semibold">{label}</span>
      <div className="relative">
        {Icon && (
          <Icon
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
          />
        )}
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          inputMode={inputMode || "text"}
          className={`w-full h-11 ${Icon ? "pl-8" : "pl-3"} pr-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-base outline-none`}
        />
      </div>
    </label>
  );
}
