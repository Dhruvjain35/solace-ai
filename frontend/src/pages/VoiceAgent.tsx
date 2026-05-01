import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Phone, PhoneCall, PhoneOff, Send, Loader2, ArrowRight,
  Mic, Volume2, MessageSquare, Sparkles, ShieldCheck, Globe2,
  AlertOctagon,
} from "lucide-react";
import {
  voiceSimulatorStart,
  voiceSimulatorTurn,
  voiceSimulatorEnd,
  type VoiceTurnResponse,
} from "../lib/api";
import { LANGUAGES, type LangCode } from "../lib/i18n";

type Message = {
  role: "agent" | "caller";
  text: string;
  audioUrl?: string | null;
  tool?: string | null;
  escalate?: "human" | "911" | null;
};

const HOSPITAL_PHONE = "+1 (512) 555-0177"; // demo number — flip when Twilio is provisioned
const HOSPITAL_ID = "demo";

export default function VoiceAgent() {
  const [language, setLanguage] = useState<LangCode>("en");
  const [callId, setCallId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoplay, setAutoplay] = useState(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Always scroll to the latest line.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // End the simulator session if the user navigates away.
  useEffect(() => {
    return () => {
      if (callId) voiceSimulatorEnd(callId).catch(() => {});
    };
  }, [callId]);

  function playAudio(url: string | null | undefined) {
    if (!url || !autoplay) return;
    if (!audioRef.current) audioRef.current = new Audio();
    audioRef.current.src = url;
    audioRef.current.play().catch(() => {
      // Browsers block autoplay until first user gesture — that's fine here,
      // the first `playAudio` call comes from a button click.
    });
  }

  async function startCall() {
    setError(null);
    setBusy(true);
    setMessages([]);
    try {
      const r = await voiceSimulatorStart(HOSPITAL_ID, language);
      setCallId(r.call_id);
      const msg: Message = { role: "agent", text: r.say, audioUrl: r.audio_url };
      setMessages([msg]);
      playAudio(r.audio_url);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to start call");
    } finally {
      setBusy(false);
    }
  }

  async function sendTurn() {
    if (!callId || !input.trim() || busy) return;
    const userText = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "caller", text: userText }]);
    setBusy(true);
    try {
      const r: VoiceTurnResponse = await voiceSimulatorTurn(callId, userText);
      const reply: Message = {
        role: "agent",
        text: r.say,
        audioUrl: r.audio_url,
        tool: r.tool,
        escalate: r.escalate,
      };
      setMessages((prev) => [...prev, reply]);
      playAudio(r.audio_url);
      if (r.escalate) {
        // Conversation ended on the agent side. Lock further input.
        setTimeout(() => endCall(`escalate_${r.escalate}`), 1500);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Send failed");
    } finally {
      setBusy(false);
    }
  }

  async function endCall(disposition = "ended_by_user") {
    if (!callId) return;
    try {
      await voiceSimulatorEnd(callId, disposition);
    } catch {
      /* swallow */
    }
    setCallId(null);
  }

  return (
    <div
      className="min-h-screen"
      style={{
        background:
          "radial-gradient(1100px 600px at 20% -10%, rgba(203,227,233,0.30) 0%, transparent 60%), " +
          "radial-gradient(900px 500px at 100% 110%, rgba(64,99,114,0.12) 0%, transparent 55%), " +
          "#F8F9F9",
      }}
    >
      <header className="max-w-6xl mx-auto px-6 py-6 flex items-center justify-between">
        <Link to="/demo" className="flex items-center gap-3">
          <img src="/solace-logo.png" alt="Solace" className="h-12 w-auto select-none" draggable={false} />
        </Link>
        <nav className="flex items-center gap-4 text-sm">
          <Link to="/demo" className="text-text-muted hover:text-ink">Patient intake</Link>
          <Link to="/demo/clinician" className="text-text-muted hover:text-ink">Clinician</Link>
          <span className="text-primary font-semibold">Voice agent</span>
        </nav>
      </header>

      <main className="max-w-6xl mx-auto px-6 pb-16">
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-start">
          <div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-primary font-bold mb-3">
              Voice agent · for hospitals
            </div>
            <h1 className="text-4xl sm:text-5xl font-bold tracking-editorial-tight leading-[1.05]">
              Patients dial in.<br />
              Solace answers — <span className="text-primary">in their language</span>.
            </h1>
            <p className="mt-5 text-lg text-text-muted leading-relaxed max-w-xl">
              The same Whisper + Claude + ElevenLabs stack that powers waiting-room intake now answers your main line. Triage, scheduling, FAQ, escalation — all 24/7, in 10+ languages, with a real clinician one warm-transfer away.
            </p>

            <div className="mt-8 bg-surface-lowest rounded-xl shadow-card p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                    Demo hospital line
                  </div>
                  <div className="font-mono text-2xl font-bold tracking-editorial mt-0.5">{HOSPITAL_PHONE}</div>
                </div>
                <a
                  href={`tel:${HOSPITAL_PHONE.replace(/[^\d+]/g, "")}`}
                  className="inline-flex items-center gap-2 h-11 px-4 rounded-md bg-primary text-white text-sm font-semibold shadow-soft hover:bg-primary-hover transition-colors"
                >
                  <Phone size={16} /> Call now
                </a>
              </div>
              <div className="text-[12px] text-text-muted leading-snug">
                Provisioned via Twilio Voice (BAA-eligible). Number maps to hospital_id <span className="font-mono">{HOSPITAL_ID}</span>; route additional numbers per facility from the admin console.
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3">
              <Stat icon={Globe2}     label="Languages"   value="10+ live" />
              <Stat icon={ShieldCheck} label="Compliance"  value="HIPAA · BAA-pending" />
              <Stat icon={Sparkles}    label="Same brain"  value="Whisper · Claude · ElevenLabs" />
              <Stat icon={Volume2}     label="Cost per call" value="~$0.05–0.10" />
            </div>
          </div>

          <Simulator
            language={language}
            setLanguage={setLanguage}
            messages={messages}
            input={input}
            setInput={setInput}
            busy={busy}
            callId={callId}
            error={error}
            autoplay={autoplay}
            setAutoplay={setAutoplay}
            scrollRef={scrollRef}
            onStart={startCall}
            onSend={sendTurn}
            onEnd={() => endCall("ended_by_user")}
          />
        </section>

        <section className="mt-16">
          <h2 className="text-2xl font-bold tracking-editorial mb-6">How it works</h2>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <Step n={1} title="Caller dials in"          body="Twilio routes the call by dialed-number → hospital_id." Icon={PhoneCall} />
            <Step n={2} title="Agent listens"            body="Twilio <Record> → S3 → Whisper STT in the caller's language." Icon={Mic} />
            <Step n={3} title="Claude reasons"           body="Tool-using Claude picks: triage, book, FAQ, transfer, or 911." Icon={Sparkles} />
            <Step n={4} title="ElevenLabs speaks back"  body="Cached MP3 in S3 — repeat phrases cost $0 after first run." Icon={Volume2} />
          </div>
        </section>

        <section className="mt-12 grid grid-cols-1 md:grid-cols-2 gap-4">
          <Capability
            title="Triage on the phone"
            body="Caller describes symptoms; agent runs the same ESI engine the patient flow uses, then advises stay-home / book-now / come-in / 911. SHAP-explainable, audit-logged."
            Icon={Sparkles}
          />
          <Capability
            title="Scheduling without humans"
            body="Books appointments, generates phone-spelled confirmation codes, cancels by code. Voice-booked slots show up next to web-booked ones in the clinician dashboard."
            Icon={MessageSquare}
          />
          <Capability
            title="Always-on FAQ"
            body="Hours, address, parking, billing, what to bring, current wait time. Hospital-specific knowledge base, swap to RAG when content scales."
            Icon={Globe2}
          />
          <Capability
            title="Emergency-aware"
            body={`Hard-coded triggers ("chest pain", "stroke", "can't breathe", "overdose") bypass Claude entirely — the agent says "dial 911" instantly and warm-transfers to a clinician.`}
            Icon={AlertOctagon}
          />
        </section>

        <section className="mt-12 bg-surface-lowest rounded-xl p-6 shadow-card">
          <h3 className="text-lg font-bold tracking-editorial mb-3">Cost engineering</h3>
          <ul className="text-[14px] leading-relaxed text-ink space-y-2">
            <li><span className="font-semibold">Same Lambda</span> — no Fargate, no WebSocket. Twilio <span className="font-mono">&lt;Record&gt;</span> pattern keeps the agent on the existing arm64 container.</li>
            <li><span className="font-semibold">TTS cache by hash</span> — every phrase the agent speaks gets stored in S3 keyed on <span className="font-mono">sha256(voice + lang + text)</span>. Greetings, "anything else?", FAQ canned answers cost $0 after the first generation.</li>
            <li><span className="font-semibold">Twilio voice</span> $0.0085/min in + $1/mo per number. Whisper $0.006/min. Claude Sonnet ~$0.005-0.015/turn. ElevenLabs cached.</li>
            <li><span className="font-semibold">PAY_PER_REQUEST DynamoDB</span> — zero idle cost between calls. 90-day TTL on call rows, 30-day on appointments.</li>
            <li><span className="font-semibold">Per-call envelope</span> roughly <span className="font-mono">$0.05 + $0.015 × minutes</span> — a 4-min call is under nine cents, all-in.</li>
          </ul>
        </section>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------------

type SimulatorProps = {
  language: LangCode;
  setLanguage: (c: LangCode) => void;
  messages: Message[];
  input: string;
  setInput: (s: string) => void;
  busy: boolean;
  callId: string | null;
  error: string | null;
  autoplay: boolean;
  setAutoplay: (b: boolean) => void;
  scrollRef: React.MutableRefObject<HTMLDivElement | null>;
  onStart: () => void;
  onSend: () => void;
  onEnd: () => void;
};

function Simulator(p: SimulatorProps) {
  const supportedLangs = LANGUAGES.filter((l) =>
    ["en", "es", "zh", "vi", "ar", "fr", "pt", "ko", "hi", "ru"].includes(l.code)
  );
  return (
    <div className="bg-surface-lowest rounded-xl shadow-card overflow-hidden flex flex-col h-[560px]">
      <div className="px-5 py-3 bg-primary-gradient text-white flex items-center justify-between">
        <div className="flex items-center gap-2">
          <PhoneCall size={16} />
          <span className="font-semibold tracking-editorial">In-browser simulator</span>
        </div>
        <label className="text-[11px] flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={p.autoplay}
            onChange={(e) => p.setAutoplay(e.target.checked)}
            className="h-3 w-3 accent-white"
          />
          autoplay voice
        </label>
      </div>

      <div ref={p.scrollRef} className="flex-1 overflow-y-auto p-5 flex flex-col gap-3">
        {!p.callId && p.messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center gap-3">
            <div className="text-text-muted text-sm">No active call.</div>
            <div className="flex flex-col items-center gap-2 w-full max-w-xs">
              <select
                value={p.language}
                onChange={(e) => p.setLanguage(e.target.value as LangCode)}
                className="w-full h-10 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none"
              >
                {supportedLangs.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.flag}  {l.native} ({l.english})
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={p.onStart}
                disabled={p.busy}
                className="w-full h-11 inline-flex items-center justify-center gap-2 rounded-md bg-primary text-white font-semibold shadow-soft hover:bg-primary-hover disabled:opacity-60"
              >
                {p.busy ? <Loader2 size={16} className="animate-spin" /> : <PhoneCall size={16} />}
                Start simulator call
              </button>
            </div>
          </div>
        )}

        <AnimatePresence initial={false}>
          {p.messages.map((m, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.18 }}
              className={`flex ${m.role === "caller" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[78%] px-3.5 py-2 rounded-2xl text-[14px] leading-snug ${
                  m.role === "caller"
                    ? "bg-primary text-white rounded-br-md"
                    : m.escalate === "911"
                    ? "bg-error text-white rounded-bl-md"
                    : m.escalate === "human"
                    ? "bg-warning text-white rounded-bl-md"
                    : "bg-surface-low text-ink rounded-bl-md"
                }`}
              >
                <div>{m.text}</div>
                {m.tool && (
                  <div className="mt-1 text-[10px] uppercase tracking-wider opacity-70">
                    tool · {m.tool}
                  </div>
                )}
                {m.audioUrl && (
                  <audio
                    controls
                    src={m.audioUrl}
                    className="mt-1.5 h-7 w-full"
                    style={{ maxWidth: 240 }}
                  />
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {p.error && (
        <div className="px-5 py-2 bg-error-container text-error text-xs">{p.error}</div>
      )}

      {p.callId && (
        <div className="border-t border-line p-3 flex items-center gap-2">
          <input
            type="text"
            value={p.input}
            onChange={(e) => p.setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") p.onSend();
            }}
            placeholder="Type what the caller would say…"
            className="flex-1 h-10 px-3 rounded-md bg-surface-low ring-1 ring-line focus:ring-primary focus:ring-2 text-sm outline-none"
            disabled={p.busy}
            autoFocus
          />
          <button
            type="button"
            onClick={p.onSend}
            disabled={p.busy || !p.input.trim()}
            className="h-10 w-10 inline-flex items-center justify-center rounded-md bg-primary text-white disabled:opacity-50"
            aria-label="Send"
          >
            {p.busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
          <button
            type="button"
            onClick={p.onEnd}
            className="h-10 px-3 inline-flex items-center gap-1 rounded-md bg-surface-low text-text-muted hover:text-error text-xs font-medium"
          >
            <PhoneOff size={14} /> End
          </button>
        </div>
      )}
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Phone; label: string; value: string }) {
  return (
    <div className="bg-surface-lowest rounded-lg p-3 shadow-soft flex items-start gap-3">
      <div className="h-9 w-9 rounded-md bg-primary-fixed flex items-center justify-center text-primary shrink-0">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">{label}</div>
        <div className="text-sm font-semibold tracking-editorial truncate">{value}</div>
      </div>
    </div>
  );
}

function Step({ n, title, body, Icon }: { n: number; title: string; body: string; Icon: typeof Phone }) {
  return (
    <div className="bg-surface-lowest rounded-lg p-4 shadow-soft">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] font-mono text-text-muted">0{n}</span>
        <Icon size={14} className="text-primary" />
      </div>
      <div className="font-semibold tracking-editorial mb-1">{title}</div>
      <div className="text-[13px] text-text-muted leading-snug">{body}</div>
      <ArrowRight size={12} className="text-text-muted mt-3" />
    </div>
  );
}

function Capability({ title, body, Icon }: { title: string; body: string; Icon: typeof Phone }) {
  return (
    <div className="bg-surface-lowest rounded-lg p-5 shadow-soft">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={16} className="text-primary" />
        <div className="font-semibold tracking-editorial text-[15px]">{title}</div>
      </div>
      <div className="text-[13.5px] text-ink leading-relaxed">{body}</div>
    </div>
  );
}
