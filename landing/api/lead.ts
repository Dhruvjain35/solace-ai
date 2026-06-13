/*
 * Lead capture — a Vercel serverless function for the marketing site's Demo and
 * Contact forms. No database: it forwards each lead to whichever channel is
 * configured via env vars, so it goes live the moment you set one.
 *
 *   LEAD_WEBHOOK_URL   Slack / Discord / Zapier incoming webhook (simplest)
 *   RESEND_API_KEY     send the lead as email via Resend
 *   LEAD_TO_EMAIL      destination for the Resend email (default hello@solace.health)
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
  const to = process.env.LEAD_TO_EMAIL || 'hello@solace.health';
  let delivered = false;

  try {
    if (webhook) {
      await fetch(webhook, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: summary, content: summary }),
      });
      delivered = true;
    }
    if (resendKey) {
      await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: { authorization: `Bearer ${resendKey}`, 'content-type': 'application/json' },
        body: JSON.stringify({
          from: 'Solace Leads <leads@solace.health>',
          to: [to],
          reply_to: email,
          subject: `New ${source} lead${org ? ` — ${org}` : ''}`,
          text: summary,
        }),
      });
      delivered = true;
    }
  } catch {
    res.status(502).json({ error: 'Could not deliver the request right now.' });
    return;
  }

  if (!delivered) {
    res.status(501).json({ error: 'Lead delivery is not configured.' });
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
