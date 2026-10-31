"use client";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, CheckCheck, Copy, Inbox, Loader2, Mail, MailX, RefreshCw, Reply, Search, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, Contact, OutboundConfig, OutboundMessage } from "@/lib/types";
import { AGENT_ID } from "@/lib/stream";
import { STATUS_TEXT, findContact, getOutboundConfig, isOpen, listMessages, refreshMessages, sendEmail } from "@/lib/outbound";
import { GuardBadge } from "@/components/evidence";

// One shared config fetch per page load.
let configPromise: Promise<OutboundConfig | null> | null = null;
const loadConfig = () => (configPromise ??= getOutboundConfig().catch(() => null));

const TONE: Record<string, string> = {
  sent: "border-primary/40 bg-primary/10 text-primary",
  delivered: "border-verified/30 bg-verified/10 text-verified",
  opened: "border-verified/30 bg-verified/10 text-verified",
  clicked: "border-verified/30 bg-verified/10 text-verified",
  replied: "border-verified/40 bg-verified/15 text-verified",
  bounced: "border-contradicted/30 bg-contradicted/10 text-contradicted",
  complained: "border-contradicted/30 bg-contradicted/10 text-contradicted",
  blocked: "border-contradicted/30 bg-contradicted/10 text-contradicted",
  failed: "border-contradicted/30 bg-contradicted/10 text-contradicted",
};

export function MessageStatus({ status, className }: { status: string; className?: string }) {
  const I = status === "replied" ? Reply : status === "delivered" || status === "opened" ? CheckCheck : ["blocked", "failed", "bounced"].includes(status) ? MailX : Send;
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-[11px] font-[510]", TONE[status] ?? "border-border-strong text-muted-foreground", className)}>
      <I className="size-3" />
      {STATUS_TEXT[status] ?? status}
    </span>
  );
}

export interface OutreachProps {
  candidate: Candidate;
  draft: string | undefined;
  onDraft: (text: string) => void;
}

export function Outreach({ candidate: c, draft, onDraft }: OutreachProps) {
  const text = draft ?? c.outreach_draft ?? "";
  const [subject, setSubject] = useState(c.outreach_subject ?? "");
  const [contact, setContact] = useState<Contact | null | undefined>(c.contact);
  const [looking, setLooking] = useState(false);
  const [cfg, setCfg] = useState<OutboundConfig | null>(null);
  const [msgs, setMsgs] = useState<OutboundMessage[]>(c.outreach?.message ? [c.outreach.message] : []);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const agent = !!AGENT_ID;

  useEffect(() => {
    setSubject(c.outreach_subject ?? "");
    setContact(c.contact);
    setResult(null);
    setMsgs(c.outreach?.message ? [c.outreach.message] : []);
  }, [c.id, c.outreach_subject, c.contact, c.outreach]);

  useEffect(() => {
    if (agent) loadConfig().then(setCfg);
  }, [agent]);

  const load = useCallback(async () => {
    if (!agent || !c.profile_url) return;
    try {
      setMsgs(await listMessages(c.profile_url));
    } catch {}
  }, [agent, c.profile_url]);

  useEffect(() => {
    load();
  }, [load]);

  // While anything we sent is still open, poll the provider and the inbox for delivery and replies.
  const waiting = msgs.some((m) => isOpen(m) && m.status !== "replied");
  useEffect(() => {
    if (!agent || !waiting) return;
    const t = setInterval(async () => {
      try {
        await refreshMessages();
        await load();
      } catch {}
    }, 20000);
    return () => clearInterval(t);
  }, [agent, waiting, load]);

  const lookup = async () => {
    if (!c.profile_url) return;
    setLooking(true);
    try {
      setContact(await findContact(c.profile_url));
    } catch (e) {
      setContact({ profile_url: c.profile_url, error: e instanceof Error ? e.message : String(e), note: "Lookup failed" });
    } finally {
      setLooking(false);
    }
  };

  const send = async () => {
    setSending(true);
    setResult(null);
    try {
      const r = await sendEmail(c, subject, text, contact);
      if (r.contact) setContact(r.contact);
      setResult({ ok: r.ok, text: r.detail });
      await load();
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSending(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  };

  const checkNow = async () => {
    try {
      await refreshMessages();
    } catch {}
    load();
  };

  if (!c.outreach_draft && !draft) {
    return <p className="text-[13px] text-faint">No draft. The agent only writes outreach for strong, verified matches.</p>;
  }

  const sentMsgs = msgs.filter((m) => m.status !== "blocked" && m.status !== "failed");
  const canSend = agent && cfg?.ready && !!contact?.email && !!text.trim() && !sending;
  const why = !agent
    ? "Sending needs the agent backend (set NEXT_PUBLIC_AGENT_ID)"
    : !cfg
      ? "Checking email setup..."
      : !cfg.ready
        ? cfg.reason
        : !contact?.email
          ? "No email for this person yet"
          : "";

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-hidden rounded-lg border border-border bg-background/40 focus-within:border-primary/50">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2 text-[12px]">
          <span className="min-w-0 text-muted-foreground">
            To <span className="text-foreground">{c.name}</span>
            {contact?.email ? (
              <>
                {" "}
                <span className="font-mono text-[11.5px] text-foreground">&lt;{contact.email}&gt;</span>
              </>
            ) : null}
          </span>
          {agent && !contact?.email && c.profile_url && (
            <button onClick={lookup} disabled={looking} className="inline-flex h-6 items-center gap-1 rounded-md border border-border-strong bg-elevated px-2 text-[11px] font-[510] hover:bg-hover disabled:opacity-60">
              {looking ? <Loader2 className="size-3 animate-spin" /> : <Search className="size-3" />} Find email on Crustdata
            </button>
          )}
        </div>
        {(contact?.note || contact?.error) && (
          <p className={cn("border-b border-border px-3 py-1.5 text-[11.5px]", contact?.email ? "text-muted-foreground" : "text-unverifiable")}>
            {contact.email ? <Check className="mr-1 inline size-3 text-verified" /> : <AlertTriangle className="mr-1 inline size-3" />}
            {contact.error ? `Lookup failed: ${contact.error}` : contact.note}
            {contact.source?.endpoint && <span className="ml-1 font-mono text-faint">· {contact.source.endpoint}.{contact.source.field}</span>}
          </p>
        )}
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          aria-label="Subject"
          className="w-full border-b border-border bg-transparent px-3 py-2 text-[13px] font-[510] focus:outline-none"
        />
        <textarea
          value={text}
          onChange={(e) => onDraft(e.target.value)}
          aria-label="Email body"
          rows={Math.min(14, Math.max(6, text.split("\n").length + 1))}
          className="w-full resize-y bg-transparent px-3 py-2.5 text-[13.5px] leading-relaxed text-secondary focus:outline-none"
        />
        {c.guard && (
          <details className="border-t border-border px-3 py-2 text-[12px]">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2">
              <span className="font-[510] text-muted-foreground">Send Guard on the draft · {(c.guard.checks ?? []).length} checks</span>
              <GuardBadge guard={c.guard} />
            </summary>
            {c.guard.error && <p className="mt-1 text-contradicted">{c.guard.error}. Blocked to be safe.</p>}
            <ul className="mt-1">
              {(c.guard.checks ?? []).map((k, i) => (
                <li key={k.id ?? i} className="flex gap-2 py-0.5">
                  {k.status === "pass" ? <Check className="mt-0.5 size-3 shrink-0 text-verified" /> : <X className={cn("mt-0.5 size-3 shrink-0", k.status === "fail" ? "text-contradicted" : "text-unverifiable")} />}
                  <span className="min-w-0">
                    <span className="text-secondary">{k.name}</span>
                    {k.detail && <span className="text-faint"> · {k.detail}</span>}
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-[11px] text-faint">If you edit the email, Send Guard checks your version again when you press Send.</p>
          </details>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
          <span className="text-[11.5px] text-muted-foreground">
            {why ||
`Goes to your test inbox ${cfg?.test_to}, never to ${c.name.split(" ")[0]}`}
          </span>
          <div className="flex items-center gap-1.5">
            {draft !== undefined && draft !== c.outreach_draft && (
              <button onClick={() => onDraft(c.outreach_draft ?? "")} className="text-[11px] text-muted-foreground hover:text-foreground">
                Reset
              </button>
            )}
            <button onClick={copy} className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2 text-[11.5px] font-[510] hover:bg-hover">
              {copied ? <Check className="size-3" /> : <Copy className="size-3" />} {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={send}
              disabled={!canSend}
              title={why || "Send Guard checks the email, then it is sent"}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-primary/60 bg-primary px-2.5 text-[12px] font-[590] text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {sending ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />} {sending ? "Checking and sending" : sentMsgs.length ? "Send again" : "Send email"}
            </button>
          </div>
        </div>
      </div>

      {result && (
        <p className={cn("rounded-md border px-3 py-2 text-[12.5px]", result.ok ? "border-verified/30 bg-verified/10 text-verified" : "border-contradicted/30 bg-contradicted/[0.06] text-contradicted")}>
          {result.ok ? <Check className="mr-1 inline size-3.5" /> : <AlertTriangle className="mr-1 inline size-3.5" />}
          {result.text}
        </p>
      )}

      {!!msgs.length && (
        <div className="rounded-lg border border-border bg-background/30">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <span className="inline-flex items-center gap-1.5 text-[12px] font-[510] text-muted-foreground">
              <Mail className="size-3.5" /> Emails to {c.name.split(" ")[0]}
            </span>
            <button onClick={checkNow} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground" title={cfg?.replies ? "Check delivery and replies now" : "Check delivery now (replies need IMAP set up)"}>
              <RefreshCw className="size-3" /> Check now
            </button>
          </div>
          <ol className="divide-y divide-border">
            {msgs.map((m) => (
              <li key={m.id} className="px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-[510]">{m.subject}</p>
                    <p className="text-[11.5px] text-muted-foreground">{m.detail}</p>
                  </div>
                  <MessageStatus status={m.status} />
                </div>
                <ol className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-faint">
                  {m.events.map((e, i) => (
                    <li key={i}>
                      {STATUS_TEXT[e.status] ?? e.status} {new Date(e.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </li>
                  ))}
                </ol>
                {m.replies.map((r) => (
                  <div key={r.message_id} className="mt-2 rounded-md border border-verified/25 bg-verified/[0.06] px-2.5 py-2">
                    <p className="mb-1 inline-flex items-center gap-1 text-[11px] font-[510] text-verified">
                      <Inbox className="size-3" /> Reply from {r.from}
                      {r.date && <span className="font-normal text-faint"> · {new Date(r.date).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>}
                    </p>
                    <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-secondary">{r.text || "(empty reply)"}</p>
                  </div>
                ))}
              </li>
            ))}
          </ol>
          {waiting && (
            <p className="border-t border-border px-3 py-1.5 text-[11px] text-faint">
              {cfg?.replies ? "Watching for delivery and replies every 20 seconds." : "Watching delivery. Replies show up here once IMAP is set up."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
