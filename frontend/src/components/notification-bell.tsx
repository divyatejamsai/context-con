"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, Check, Clock, OctagonX, Scale, Settings2, ShieldX, X } from "lucide-react";
import { getAdminToken } from "@/app/console/api";
import { cn } from "@/lib/utils";

// The console bell: approvals waiting on you, blocked messages, refused work and stopped agents (backend app/alerts).
// The same alerts go out by email (to the test inbox) and Slack, with one-click Approve / Reject links.

type Channel = { status: "sent" | "skipped" | "failed" | "off"; why?: string; for?: string; to?: string };
type Item = {
  alert_id: string; kind: "approval" | "block" | "rule" | "stop" | "test"; title: string; detail: string;
  facts: [string, string][]; agent_name?: string | null; approval_id?: string | null; created_at: string;
  console_path: string; channels: { email?: Channel; slack?: Channel }; read: boolean;
  approval_status?: string | null; decided_by?: string | null;
};
type Feed = { items: Item[]; unread: number };
type Prefs = { email: boolean; slack: boolean; approval: boolean; block: boolean; stop: boolean };
type PrefsView = { prefs: Prefs; labels: Record<string, string>;
  channels: { email: { ready: boolean; to?: string | null; why?: string | null }; slack: { ready: boolean; why?: string | null } } };

const BASE = "/api/backend/alerts";
const ICON = { approval: Clock, block: ShieldX, rule: Scale, stop: OctagonX, test: Bell } as const;
const TONE = { approval: "text-flag", block: "text-contradicted", rule: "text-contradicted", stop: "text-contradicted", test: "text-primary" } as const;
const DONE: Record<string, string> = {
  sent: "Approved and sent", signed: "Approved and signed", rejected: "Rejected", blocked_at_send: "Blocked at send",
  expired: "Expired", sending: "Sending…",
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const r = await fetch(path, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(token ? { "x-admin-token": token } : {}) } });
  const j = await r.json().catch(() => null);
  if (!r.ok) throw new Error(typeof j?.detail === "string" ? j.detail : j?.detail?.message ?? `Backend returned ${r.status}`);
  return j as T;
}

function ago(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function delivered(c: Item["channels"]) {
  const out = [];
  if (c.email?.status === "sent") out.push("emailed");
  if (c.slack?.status === "sent") out.push("on Slack");
  if (c.email?.status === "failed" || c.slack?.status === "failed") out.push("delivery failed");
  return out.join(" · ");
}

/** `up`: in the sidebar footer, open upward from the footer row. */
export function NotificationBell({ up }: { up?: boolean } = {}) {
  const router = useRouter();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<PrefsView | null>(null);
  const [showPrefs, setShowPrefs] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    call<Feed>(BASE).then(setFeed).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, open ? 5000 : 15000);
    return () => clearInterval(t);
  }, [load, open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  useEffect(() => {
    if (showPrefs && !settings) call<PrefsView>(`${BASE}/prefs`).then(setSettings).catch(() => {});
  }, [showPrefs, settings]);

  if (!feed) return null;

  const markAll = async () => {
    await call(`${BASE}/read`, { method: "POST", body: "{}" }).catch(() => {});
    load();
  };
  const go = async (it: Item) => {
    if (!it.read) await call(`${BASE}/read`, { method: "POST", body: JSON.stringify({ alert_ids: [it.alert_id] }) }).catch(() => {});
    setOpen(false);
    router.push(it.console_path);
    load();
  };
  const decide = async (it: Item, verb: "approve" | "reject") => {
    if (!it.approval_id) return;
    setBusy(`${it.alert_id}:${verb}`);
    setNote(null);
    try {
      const a = await call<{ status: string }>(`/api/backend/runtime/approvals/${it.approval_id}/${verb}`, { method: "POST", body: JSON.stringify({ by: "employer" }) });
      await call(`${BASE}/read`, { method: "POST", body: JSON.stringify({ alert_ids: [it.alert_id] }) }).catch(() => {});
      setNote(a.status === "pending" ? "Your approval is in. It needs a second person." : `${DONE[a.status] ?? a.status}.`);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "That didn't go through.");
    } finally {
      setBusy(null);
      load();
    }
  };
  const toggle = async (k: keyof Prefs) => {
    if (!settings) return;
    const next = await call<PrefsView>(`${BASE}/prefs`, { method: "PUT", body: JSON.stringify({ [k]: !settings.prefs[k] }) }).catch(() => null);
    if (next) setSettings(next);
  };
  const test = async () => {
    setNote(null);
    try {
      const a = await call<Item>(`${BASE}/test`, { method: "POST", body: "{}" });
      const e = a.channels.email, s = a.channels.slack;
      setNote(`Test alert: email ${e?.status === "sent" ? `sent to ${e.to}` : e?.why ?? e?.status}; Slack ${s?.status === "sent" ? "posted" : s?.why ?? s?.status}.`);
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't send a test alert.");
    }
    load();
  };

  return (
    <div ref={ref} className={up ? undefined : "relative"}>
      <button onClick={() => setOpen((o) => !o)} aria-label={feed.unread ? `${feed.unread} unread alerts` : "Alerts"} aria-expanded={open}
        title="Alerts: approvals waiting on you, blocks and stops"
        className="relative grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground">
        <Bell className="size-4" />
        {feed.unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 grid h-[15px] min-w-[15px] place-items-center rounded-full bg-contradicted px-1 text-[9.5px] font-[650] leading-none text-white">
            {feed.unread > 99 ? "99+" : feed.unread}
          </span>
        )}
      </button>
      {open && (
        <div role="dialog" aria-label="Alerts"
          className={cn("z-50 flex max-h-[min(560px,75vh)] flex-col rounded-lg border border-border bg-panel shadow-[var(--shadow)] animate-fade",
            up ? "absolute bottom-9 left-0 w-[380px]" : "fixed inset-x-3 top-14 sm:absolute sm:inset-x-auto sm:right-0 sm:top-9 sm:w-[380px]")}>
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <p className="text-[13px] font-[590]">Alerts</p>
            {feed.unread > 0 && <span className="text-[11.5px] text-muted-foreground">{feed.unread} new</span>}
            <div className="ml-auto flex items-center gap-0.5">
              {feed.unread > 0 && <button onClick={markAll} className="rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:bg-hover hover:text-foreground">Mark all read</button>}
              <button onClick={() => setShowPrefs((s) => !s)} aria-label="Alert settings" aria-pressed={showPrefs}
                className={cn("grid size-7 place-items-center rounded-md hover:bg-hover", showPrefs ? "text-foreground" : "text-muted-foreground")}>
                <Settings2 className="size-3.5" />
              </button>
            </div>
          </div>

          {showPrefs && (
            <div className="border-b border-border bg-elevated/50 px-3 py-2.5 text-[12.5px]">
              {!settings ? <p className="text-muted-foreground">Loading…</p> : (
                <>
                  <p className="mb-1.5 text-[11px] font-[510] text-faint">Where to reach me</p>
                  <Toggle on={settings.prefs.email} onClick={() => toggle("email")} label="Email"
                    hint={settings.channels.email.ready ? `to ${settings.channels.email.to} (the test inbox)` : settings.channels.email.why ?? "not set up"} />
                  <Toggle on={settings.prefs.slack} onClick={() => toggle("slack")} label="Slack"
                    hint={settings.channels.slack.ready ? "the workspace channel" : settings.channels.slack.why ?? "not set up"} />
                  <p className="mb-1.5 mt-2.5 text-[11px] font-[510] text-faint">What to send me</p>
                  {(["approval", "block", "stop"] as const).map((k) => (
                    <Toggle key={k} on={settings.prefs[k]} onClick={() => toggle(k)} label={settings.labels[k] ?? k} />
                  ))}
                  <button onClick={test} className="mt-2 rounded-md border border-border px-2.5 py-1 text-[12px] font-[510] hover:bg-hover">Send me a test alert</button>
                  <p className="mt-2 text-[11px] leading-snug text-faint">The bell always shows everything. Email and Slack carry Approve and Reject buttons that work once, for you, for 24 hours.</p>
                </>
              )}
            </div>
          )}

          {note && (
            <p className="flex items-start gap-2 border-b border-border px-3 py-2 text-[12px] text-secondary">
              <span className="min-w-0 flex-1">{note}</span>
              <button onClick={() => setNote(null)} aria-label="Dismiss" className="text-faint hover:text-foreground"><X className="size-3.5" /></button>
            </p>
          )}

          <ul className="min-h-0 flex-1 overflow-y-auto">
            {feed.items.length === 0 && (
              <li className="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
                Nothing yet. When an agent needs your approval, or something is blocked or stopped, it shows up here.
              </li>
            )}
            {feed.items.map((it) => {
              const Icon = ICON[it.kind] ?? Bell;
              const pending = it.kind === "approval" && it.approval_status === "pending";
              const how = delivered(it.channels);
              return (
                <li key={it.alert_id} className={cn("border-b border-border last:border-b-0", !it.read && "bg-primary/[0.04]")}>
                  <div className="flex gap-2.5 px-3 py-2.5">
                    <Icon className={cn("mt-0.5 size-4 shrink-0", TONE[it.kind] ?? "text-muted-foreground")} />
                    <div className="min-w-0 flex-1">
                      <button onClick={() => go(it)} className="block w-full text-left">
                        <span className={cn("block text-[12.5px] leading-snug", !it.read ? "font-[590]" : "font-[510]")}>{it.title}</span>
                        {it.detail && <span className="mt-0.5 line-clamp-2 whitespace-pre-line text-[12px] leading-snug text-muted-foreground">{it.detail}</span>}
                        <span className="mt-1 block text-[11px] text-faint">
                          {ago(it.created_at)}{how ? ` · ${how}` : ""}
                          {it.kind === "approval" && it.approval_status && !pending ? ` · ${DONE[it.approval_status] ?? it.approval_status}${it.decided_by ? ` by ${it.decided_by}` : ""}` : ""}
                        </span>
                      </button>
                      {pending && (
                        <div className="mt-1.5 flex gap-1.5">
                          <button onClick={() => decide(it, "approve")} disabled={!!busy}
                            className="inline-flex h-7 items-center gap-1 rounded-md bg-verified px-2.5 text-[12px] font-[590] text-white hover:brightness-110 disabled:opacity-60">
                            <Check className="size-3.5" /> {busy === `${it.alert_id}:approve` ? "Approving…" : "Approve"}
                          </button>
                          <button onClick={() => decide(it, "reject")} disabled={!!busy}
                            className="inline-flex h-7 items-center rounded-md border border-border px-2.5 text-[12px] font-[510] text-muted-foreground hover:bg-hover hover:text-foreground disabled:opacity-60">
                            {busy === `${it.alert_id}:reject` ? "Rejecting…" : "Reject"}
                          </button>
                        </div>
                      )}
                    </div>
                    {!it.read && <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" aria-label="unread" />}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function Toggle({ on, onClick, label, hint }: { on: boolean; onClick: () => void; label: string; hint?: string }) {
  return (
    <button onClick={onClick} role="switch" aria-checked={on} className="flex w-full items-center gap-2 py-1 text-left">
      <span className={cn("relative h-4 w-7 shrink-0 rounded-full transition", on ? "bg-primary" : "bg-border-strong")}>
        <span className={cn("absolute top-0.5 size-3 rounded-full bg-white transition-all", on ? "left-3.5" : "left-0.5")} />
      </span>
      <span className="min-w-0">
        <span className="text-[12.5px]">{label}</span>
        {hint && <span className="block truncate text-[11px] text-faint">{hint}</span>}
      </span>
    </button>
  );
}
