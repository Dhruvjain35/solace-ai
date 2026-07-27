/*
 * Lead submission for the Demo and Contact forms. Posts to the /api/lead
 * serverless function; if that isn't configured (or the network fails), the
 * caller falls back to a mailto compose so a lead is never lost.
 */

export type Lead = {
  name?: string;
  email: string;
  org?: string;
  role?: string;
  topic?: string;
  message?: string;
  website?: string; // honeypot
  source: 'demo' | 'contact';
};

const LEAD_EMAIL = 'hello@solace.health';

/** Returns true if the backend accepted the lead. */
export async function submitLead(lead: Lead): Promise<boolean> {
  try {
    const r = await fetch('/api/lead', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(lead),
    });
    return r.ok;
  } catch {
    return false;
  }
}

/** Open the user's mail client with the lead prefilled. */
export function mailtoLead(lead: Lead): void {
  const subject = lead.source === 'demo' ? 'Demo request' : 'Contact request';
  const lines = [
    lead.name && `Name: ${lead.name}`,
    `Work email: ${lead.email}`,
    lead.org && `Organization: ${lead.org}`,
    lead.role && `Role: ${lead.role}`,
    lead.topic && `Topic: ${lead.topic}`,
    '',
    lead.message || (lead.source === 'demo' ? "I'd like to book a Solace demo." : ''),
  ].filter((l) => l !== undefined);
  window.location.href = `mailto:${LEAD_EMAIL}?subject=${encodeURIComponent(
    subject,
  )}&body=${encodeURIComponent(lines.join('\n'))}`;
}
