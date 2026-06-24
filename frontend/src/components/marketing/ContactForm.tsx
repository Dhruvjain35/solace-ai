import { FormEvent, useState } from "react";
import { isAxiosError } from "axios";
import { CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "../../lib/api";
import { Button } from "../ui/Button";

type Topic = "demo" | "sales" | "security" | "support" | "other";

const TOPICS: { value: Topic; label: string }[] = [
  { value: "demo", label: "Book a demo" },
  { value: "sales", label: "Sales" },
  { value: "security", label: "Security" },
  { value: "support", label: "Support" },
  { value: "other", label: "Other" },
];

const inputCls =
  "w-full rounded-md bg-surface-lowest px-3.5 py-2.5 text-sm ring-1 ring-line focus:ring-2 focus:ring-primary/40 focus:outline-none placeholder:text-text-muted/60";
const labelCls = "block text-sm font-medium text-text-muted mb-1.5";

export function ContactForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [organization, setOrganization] = useState("");
  const [role, setRole] = useState("");
  const [topic, setTopic] = useState<Topic>("demo");
  const [message, setMessage] = useState("");
  // Honeypot — hidden from humans; bots that auto-fill it get silently dropped.
  const [website, setWebsite] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      await api.post("/api/contact", {
        name: name.trim(),
        email: email.trim(),
        organization: organization.trim() || null,
        role: role.trim() || null,
        topic,
        message: message.trim(),
        website: website || null,
      });
      setDone(true);
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 429) {
        setError(
          "You've reached the submission limit for now. Please try again in a little while, or email us directly."
        );
      } else if (isAxiosError(err) && err.response?.status === 422) {
        setError("Please check your details — the email address looks invalid or a field is too long.");
      } else {
        setError("Something went wrong sending your message. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="card-clean p-8 text-center" role="status">
        <CheckCircle2 size={32} className="mx-auto mb-3 text-primary" aria-hidden />
        <h3 className="text-lg font-semibold">Thanks — we'll get back to you within one business day.</h3>
        <p className="mt-2 text-sm text-text-muted">
          Your message is in our queue. For anything urgent, mention it in a follow-up.
        </p>
      </div>
    );
  }

  return (
    <form className="card-clean p-6 sm:p-8" onSubmit={handleSubmit} noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="contact-name" className={labelCls}>
            Name
          </label>
          <input
            id="contact-name"
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={200}
            autoComplete="name"
            placeholder="Dr. Maya Singh"
          />
        </div>
        <div>
          <label htmlFor="contact-email" className={labelCls}>
            Work email
          </label>
          <input
            id="contact-email"
            type="email"
            className={inputCls}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            placeholder="you@organization.org"
          />
        </div>
        <div>
          <label htmlFor="contact-organization" className={labelCls}>
            Organization <span className="font-normal text-text-muted/70">(optional)</span>
          </label>
          <input
            id="contact-organization"
            className={inputCls}
            value={organization}
            onChange={(e) => setOrganization(e.target.value)}
            maxLength={200}
            autoComplete="organization"
            placeholder="Riverside Health"
          />
        </div>
        <div>
          <label htmlFor="contact-role" className={labelCls}>
            Role <span className="font-normal text-text-muted/70">(optional)</span>
          </label>
          <input
            id="contact-role"
            className={inputCls}
            value={role}
            onChange={(e) => setRole(e.target.value)}
            maxLength={100}
            autoComplete="organization-title"
            placeholder="CMO, IT Director, Clinician…"
          />
        </div>
      </div>

      <div className="mt-4">
        <label htmlFor="contact-topic" className={labelCls}>
          Topic
        </label>
        <select
          id="contact-topic"
          className={inputCls}
          value={topic}
          onChange={(e) => setTopic(e.target.value as Topic)}
        >
          {TOPICS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-4">
        <label htmlFor="contact-message" className={labelCls}>
          Message
        </label>
        <textarea
          id="contact-message"
          className={`${inputCls} min-h-32 resize-y`}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          required
          maxLength={4000}
          placeholder="Tell us about your team and what you're looking for."
        />
      </div>

      {/* Honeypot — invisible to humans, skipped by keyboard and screen readers. */}
      <div className="sr-only" aria-hidden="true">
        <label htmlFor="contact-website">Website</label>
        <input
          id="contact-website"
          name="website"
          type="text"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          autoComplete="off"
          tabIndex={-1}
        />
      </div>

      {error && (
        <div
          className="mt-4 flex items-start gap-2 rounded-md bg-error/5 px-3.5 py-2.5 text-sm text-error ring-1 ring-error/20"
          role="alert"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-6">
        <Button type="submit" shape="pill" loading={submitting} fullWidth>
          Send message
        </Button>
      </div>
    </form>
  );
}
