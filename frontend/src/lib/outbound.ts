import { AGENT_ID, API_URL } from "./stream";
import type { Candidate, Contact, OutboundConfig, OutboundMessage, SendResult } from "./types";

// Real outbound (backend/app/outbound): email from Crustdata, Send Guard, a real provider, status and replies.

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`Backend returned ${res.status}: ${(await res.text().catch(() => "")).slice(0, 200)}`);
  return res.json() as Promise<T>;
}

export const getOutboundConfig = () => fetch(`${API_URL}/api/outbound/config`).then((r) => json<OutboundConfig>(r));

export const findContact = (profileUrl: string) =>
  fetch(`${API_URL}/api/contacts?profile_url=${encodeURIComponent(profileUrl)}`).then((r) => json<Contact>(r));

export const listMessages = (profileUrl?: string) =>
  fetch(`${API_URL}/api/messages${profileUrl ? `?profile_url=${encodeURIComponent(profileUrl)}` : ""}`)
    .then((r) => json<{ messages: OutboundMessage[] }>(r))
    .then((d) => d.messages);

export const refreshMessages = () =>
  fetch(`${API_URL}/api/messages/refresh`, { method: "POST" }).then((r) =>
    json<{ messages: OutboundMessage[]; new_replies: number; errors: string[]; replies_enabled: boolean }>(r),
  );

export function sendEmail(c: Candidate, subject: string, body: string, contact?: Contact | null) {
  return fetch(`${API_URL}/api/agents/${encodeURIComponent(AGENT_ID || "sourced")}/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      to: { name: c.name, profile_url: c.profile_url, company: c.company },
      subject,
      body,
      email: contact?.email ? contact : null,
    }),
  }).then((r) => json<SendResult>(r));
}

export const STATUS_TEXT: Record<string, string> = {
  sent: "Sent",
  delivery_delayed: "Delivery delayed",
  delivered: "Delivered",
  opened: "Opened",
  clicked: "Clicked",
  replied: "Replied",
  bounced: "Bounced",
  complained: "Marked as spam",
  blocked: "Blocked by Send Guard",
  failed: "Failed to send",
};

export const isOpen = (m: OutboundMessage) => !["blocked", "failed", "bounced", "complained"].includes(m.status);
