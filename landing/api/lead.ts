/*
 * Lead capture — a Vercel serverless function for the marketing site's Demo and
 * Contact forms. No database: it forwards each lead to whichever channel is
 * configured via env vars, so it goes live the moment you set one.
 *
 *   LEAD_WEBHOOK_URL   Slack / Discord / Zapier incoming webhook (simplest)
 *   RESEND_API_KEY     send the lead as email via Resend
 *   LEAD_TO_EMAIL      destination for the Resend email (default contacthelp.solace@gmail.com)
 *   LEAD_FROM_EMAIL    verified Resend sender (default waitlist@mysolaceclinic.com)
 *
 * With nothing configured it returns 501 so the client falls back to a mailto
 * compose — the lead is never silently dropped.
 *
 * `api/` is outside the Vite tsconfig include, so the project build never type
 * checks this file; Vercel compiles it with its own Node toolchain.
 */

// Minimal request/response shapes (avoids a @vercel/node dependency).
type Req = { method?: string; body?: unknown };
type Res = {
  status: (code: number) => Res;
  json: (data: unknown) => void;
  setHeader: (name: string, value: string) => void;
};

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export default async function handler(req: Req, res: Res): Promise<void> {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }

  const body = (typeof req.body === 'string' ? safeParse(req.body) : req.body) as
    | Record<string, string>
    | undefined;
  const {
    name = '',
    email = '',
    org = '',
    role = '',
    topic = '',
    message = '',
    website = '', // honeypot
    source = 'contact',
  } = body ?? {};

  // Bots fill the hidden field; accept silently and drop.
  if (website) {
    res.status(200).json({ ok: true });
    return;
  }
  if (!email || !EMAIL_RE.test(email)) {
    res.status(422).json({ error: 'A valid work email is required.' });
    return;
  }

  const summary = [
    `New Solace lead · ${source}`,
    name && `Name: ${name}`,
    `Email: ${email}`,
    org && `Org: ${org}`,
    role && `Role: ${role}`,
    topic && `Topic: ${topic}`,
    message && `\n${message}`,
  ]
    .filter(Boolean)
    .join('\n');

  const webhook = process.env.LEAD_WEBHOOK_URL;
  const resendKey = process.env.RESEND_API_KEY;
  const to = process.env.LEAD_TO_EMAIL || 'contacthelp.solace@gmail.com';
  let delivered = false;

  /* Both branches check the response. They did not, and that was the one bug
     that mattered here: a configured-but-failing channel set delivered = true
     off a rejected request, so the page showed "You are on the list", never
     opened its mail draft, and the signup was gone. Resend returns 403 for an
     unverified sending domain, which is exactly the state a new account is in —
     so the failure would have arrived on the first real signup, not eventually.

     Anything that does not actually deliver has to fall through to a non-2xx,
     because a non-2xx is what makes the client compose the mail draft instead. */
  const failures: string[] = [];

  try {
    if (webhook) {
      const r = await fetch(webhook, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: summary, content: summary }),
      });
      if (r.ok) delivered = true;
      else failures.push(`webhook ${r.status}`);
    }
    if (resendKey) {
      const r = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { authorization: `Bearer ${resendKey}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          // Resend sends only from a domain verified on the account, or from
          // onboarding@resend.dev — and that one delivers only to the account
          // owner's own address. Configure LEAD_FROM_EMAIL to match whichever
          // you have; the default assumes mysolaceclinic.com is verified.
          from: process.env.LEAD_FROM_EMAIL || 'Solace <waitlist@mysolaceclinic.com>',
          to: [to],
          reply_to: email,
          subject: `New ${source} lead${org ? ` — ${org}` : ''}`,
          text: summary,
        }),
      });
      if (r.ok) delivered = true;
      else failures.push(`resend ${r.status} ${await r.text().catch(() => '')}`.trim());
    }
  } catch (err) {
    failures.push(`threw ${String(err)}`);
  }

  if (!delivered) {
    // Logged in full so a misconfiguration is one look at the Vercel logs, and
    // never returned to the browser: the response reaches the person signing up.
    console.error('[lead] undelivered', { source, channels: { webhook: !!webhook, resend: !!resendKey }, failures });
    res.status(failures.length ? 502 : 501).json({ error: 'Lead delivery is not configured.' });
    return;
  }
  res.status(200).json({ ok: true });
}

function safeParse(s: string): Record<string, string> {
  try {
    return JSON.parse(s);
  } catch {
    return {};
  }
}
