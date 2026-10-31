"use client";
import { useEffect, useMemo, useState } from "react";
import { Building2, Check, ExternalLink, EyeOff, Flag, Info, Link2, Mail, MapPin, Pin, RotateCcw, Gauge, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate, ClaimStatus } from "@/lib/types";
import { claimCounts, evidenceStrength, normalizeStatus } from "@/lib/run-state";
import { Avatar, FitBadge, GuardBadge, StatusIcon, StatusPill, STATUS_LABEL, matchLabel } from "@/components/evidence";
import { Outreach } from "@/components/outreach";

type Filter = "all" | ClaimStatus;

export interface DossierProps {
  candidate: Candidate;
  rank: number;
  pinned: boolean;
  dismissed: boolean;
  draft: string | undefined;
  onDraft: (text: string) => void;
  onPin: () => void;
  onDismiss: () => void;
}

const Section = ({ title, hint, aside, children }: { title: string; hint?: string; aside?: React.ReactNode; children: React.ReactNode }) => (
  <section className="border-t border-border px-5 py-4">
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div className="min-w-0">
        <h4 className="text-[13px] font-[590]">{title}</h4>
        {hint && <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{hint}</p>}
      </div>
      {aside}
    </div>
    {children}
  </section>
);

function Prop({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[104px_1fr] items-center gap-2 py-1 text-[13px]">
      <span className="flex items-center gap-1.5 text-muted-foreground">
        {icon}
        {label}
      </span>
      <span className="min-w-0 truncate">{children}</span>
    </div>
  );
}

export function Dossier({ candidate: c, rank, pinned, dismissed, draft, onDraft, onPin, onDismiss }: DossierProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [hl, setHl] = useState<string | null>(null);
  useEffect(() => setFilter("all"), [c.id]);

  const counts = claimCounts(c);
  const strength = evidenceStrength(c);
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const claims = useMemo(
    () =>
      (c.claims ?? [])
        .map((k) => ({ ...k, status: normalizeStatus(k.status, !!k.source?.endpoint) }))
        .sort((a, b) => order[a.status] - order[b.status]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [c.claims],
  );
  // Citation numbers follow the claims list order, so [1] in a reason is the first claim below.
  const cite = useMemo(() => new Map(claims.map((k, i) => [k.id, i + 1])), [claims]);
  const shown = filter === "all" ? claims : claims.filter((k) => k.status === filter);
  const m = matchLabel(c.score);

  const jump = (id: string) => {
    setFilter("all");
    setHl(id);
    requestAnimationFrame(() => document.getElementById(`claim-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
    setTimeout(() => setHl(null), 1600);
  };


  return (
    <article className={cn("flex flex-col", dismissed && "opacity-60")}>
      <header className="px-5 pb-4 pt-5">
        <div className="flex items-start gap-3">
          <Avatar name={c.name} size={40} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[11px] text-faint">
              <span className="font-mono">#{rank}</span>
              <span>·</span>
              <span className="font-mono">{c.id}</span>
            </div>
            <h2 className="truncate text-[20px] font-[590] leading-tight tracking-[-0.012em]">{c.name}</h2>
            <p className="truncate text-[13px] text-secondary">{[c.title, c.company].filter(Boolean).join(" at ") || "Title unknown"}</p>
          </div>
          <FitBadge score={c.score} />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-1.5">
          <button
            onClick={onPin}
            title={pinned ? "Unpin this candidate" : "Keep this candidate at the top of the shortlist"}
            aria-pressed={pinned}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12px] font-[510] transition",
              pinned ? "border-primary/50 bg-primary/15 text-primary" : "border-border-strong bg-elevated hover:bg-hover",
            )}
          >
            <Pin className="size-3.5" /> {pinned ? "Pinned to top" : "Pin to top"} <kbd>P</kbd>
          </button>
          <button
            onClick={onDismiss}
            title={dismissed ? "Bring this candidate back into the shortlist" : "Not a fit: move to the bottom and leave out of exports"}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2.5 text-[12px] font-[510] transition hover:bg-hover"
          >
            {dismissed ? <RotateCcw className="size-3.5" /> : <EyeOff className="size-3.5" />} {dismissed ? "Restore" : "Not a fit"} <kbd>X</kbd>
          </button>
          {c.profile_url && (
            <a
              href={c.profile_url}
              target="_blank"
              rel="noreferrer"
              title="Open their public profile in a new tab"
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2.5 text-[12px] font-[510] transition hover:bg-hover"
            >
              Open profile <ExternalLink className="size-3" />
            </a>
          )}
        </div>

        <div className="mt-4 rounded-lg border border-border bg-background/40 px-3 py-1.5">
          <Prop icon={<Building2 className="size-3.5" />} label="Company">{c.company ?? <span className="text-faint">Unknown</span>}</Prop>
          <Prop icon={<MapPin className="size-3.5" />} label="Location">{c.location ?? <span className="text-faint">Unknown</span>}</Prop>
          <Prop icon={<Gauge className="size-3.5" />} label="Fit">
            <span className={m.cls}>{m.label}</span> <span className="text-faint">· {c.score ?? "–"}/100</span>
          </Prop>
          <Prop icon={<Check className="size-3.5" />} label="Evidence">
            <span className="inline-flex items-center gap-1.5">
              <span className="font-mono tabular-nums">{strength}%</span>
              <span className="text-faint">verified · {counts.total} claims</span>
            </span>
          </Prop>
          {c.guard && (
            <Prop icon={<ShieldCheck className="size-3.5" />} label="Send Guard">
              <span className="inline-flex items-center gap-1.5">
                <GuardBadge guard={c.guard} />
                <span className="text-faint">{c.guard.decision === "allow" ? (c.outreach?.status === "sent" ? "cleared and emailed" : "draft cleared to send") : "draft blocked"}</span>
              </span>
            </Prop>
          )}
          {c.contact && (
            <Prop icon={<Mail className="size-3.5" />} label="Email">
              {c.contact.email ? (
                <span className="inline-flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-mono text-[12px]">{c.contact.email}</span>
                  <span className="shrink-0 text-faint">· {c.contact.kind}{c.contact.status ? `, ${c.contact.status}` : ""}</span>
                </span>
              ) : (
                <span className="text-faint">{c.contact.error ? "lookup failed" : "none on Crustdata"}</span>
              )}
            </Prop>
          )}
          {!!c.flags?.length && (
            <Prop icon={<Flag className="size-3.5" />} label="Flags">
              <span className="flex flex-wrap gap-1">
                {c.flags.map((f) => (
                  <span key={f} className="rounded-full border border-flag/30 bg-flag/10 px-1.5 text-[11px] font-[510] text-flag">
                    {f}
                  </span>
                ))}
              </span>
            </Prop>
          )}
        </div>
      </header>

      <Section title="Why this candidate" hint="The ranker's reasons. Each number jumps to the claim that backs it.">
        {c.reasons?.length ? (
          <ul className="flex flex-col gap-2">
            {c.reasons.map((r, i) => (
              <li key={i} className="flex gap-2 text-[13.5px] leading-relaxed text-secondary">
                <span className="mt-[9px] size-1 shrink-0 rounded-full bg-faint" />
                <span>
                  {r.text}
                  {r.claim_ids?.map((id) => (
                    <button
                      key={id}
                      onClick={() => jump(id)}
                      title={`Show claim ${id}`}
                      className="ml-1 inline-flex h-4 min-w-4 -translate-y-px items-center justify-center rounded border border-primary/30 bg-primary/10 px-1 font-mono text-[10px] text-primary hover:bg-primary/20"
                    >
                      {cite.get(id) ?? id}
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-faint">No ranking reasons yet.</p>
        )}
      </Section>

      <Section
        title={`Claims checked · ${counts.total}`}
        hint="Each fact compared with Crustdata. Verified matches, contradicted means Crustdata says otherwise, unverifiable means there was nothing to check."
        aside={
          <div className="flex gap-0.5 rounded-md border border-border bg-background/40 p-0.5 text-[11px]">
            {(["all", "contradicted", "verified", "unverifiable"] as Filter[]).map((f) => {
              const n = f === "all" ? counts.total : counts[f];
              if (f !== "all" && !n) return null;
              return (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-[510]",
                    filter === f ? "bg-elevated text-foreground shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {f !== "all" && <StatusIcon status={f} className="size-3" />}
                  {f === "all" ? "All" : STATUS_LABEL[f]} <span className="font-mono text-faint">{n}</span>
                </button>
              );
            })}
          </div>
        }
      >
        <HowChecked />
        <ol className="flex flex-col gap-1.5">
          {shown.map((k) => (
            <li
              key={k.id}
              id={`claim-${k.id}`}
              className={cn(
                "rounded-lg border px-3 py-2.5 transition-colors",
                k.status === "contradicted" ? "border-contradicted/30 bg-contradicted/[0.06]" : "border-border bg-background/30",
                hl === k.id && "border-primary/60 bg-primary/10",
              )}
            >
              <div className="flex items-start gap-2.5">
                <span className="mt-px font-mono text-[10.5px] text-faint tabular-nums">{cite.get(k.id)}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[13.5px] font-[510] leading-snug">{k.claim}</p>
                    <StatusPill status={k.status} />
                  </div>
                  {k.evidence && <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{k.evidence}</p>}
                  <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                    {k.source?.endpoint ? (
                      <>
                        <span className="inline-flex items-center gap-1 rounded border border-border bg-elevated px-1.5 py-px font-mono text-secondary">
                          <Link2 className="size-3 text-faint" />
                          {sourceLabel(k.source.endpoint)}
                          {k.source.field && <span className="text-faint" title={`${k.source.endpoint}.${k.source.field}`}>· {fieldLabel(k.source.field)}</span>}
                        </span>
                        {k.source.url && (
                          <a href={k.source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
                            {safeHost(k.source.url)} <ExternalLink className="size-3" />
                          </a>
                        )}
                      </>
                    ) : (
                      <span className="text-contradicted">No source returned, so it doesn&apos;t count as evidence</span>
                    )}
                  </p>
                </div>
              </div>
            </li>
          ))}
          {!shown.length && <p className="text-[13px] text-faint">No claims checked for this candidate.</p>}
        </ol>
      </Section>

      <Section
        title="Email"
        hint="Written from verified facts only, signed by the person Sourced works for. The address comes from Crustdata. Send Guard checks the exact text before it goes out."
      >
        <Outreach candidate={c} draft={draft} onDraft={onDraft} />
      </Section>
    </article>
  );
}

const SOURCE_LABEL: Record<string, string> = {
  "person/enrich": "Crustdata person record",
  "person/search": "Crustdata search result",
  "company/enrich": "Crustdata company record",
  "company/identify": "Crustdata company match",
  "web/search": "Web search",
  "web/fetch": "Web page",
  "job/search": "Crustdata job listings",
};
const sourceLabel = (e: string) => SOURCE_LABEL[e] ?? e;

/** experience.employment_details.current[0].start_date -> "current job, start date" */
function fieldLabel(f: string) {
  const s = f
    .replace(/experience\.employment_details\.current(\[\d+\])?/, "current job")
    .replace(/experience\.employment_details\.past(\[\d+\])?/, "past job")
    .replace(/experience\.employment_details/, "work history")
    .replace(/basic_profile\./, "profile ")
    .replace(/funding\./, "funding ")
    .replace(/headcount\./, "headcount ")
    .replace(/\./g, ", ")
    .replace(/_/g, " ");
  return s.trim();
}

function HowChecked() {
  return (
    <details className="mb-3 rounded-lg border border-border bg-background/30 px-3 py-2 text-[12.5px] leading-relaxed text-muted-foreground">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-[510] text-secondary">
        <Info className="size-3.5" /> How Sourced checks a claim
      </summary>
      <div className="mt-2 flex flex-col gap-1.5">
        <p>
          A claim is something said about this person: by them (their profile headline and title, or a resume you give Sourced) or by the
          agent (&quot;5 years in backend roles&quot;). Sourced checks each one against the structured records Crustdata keeps: the
          person&apos;s employment history (employers, titles, start and end dates, location) and each employer&apos;s company record (size,
          funding stage, industry, founding year).
        </p>
        <ul className="flex flex-col gap-1">
          <li><span className="font-[510] text-verified">Verified</span>: the records agree, and the chip below names the record and field.</li>
          <li><span className="font-[510] text-contradicted">Contradicted</span>: a record says otherwise, for example the headline names an employer they left two years ago.</li>
          <li><span className="font-[510] text-secondary">Unverifiable</span>: no record covers it, so it is not counted as evidence and never helps the score.</li>
        </ul>
        <p>
          What it can&apos;t tell you: whether the person is good at the job or open to moving. Records are only as fresh as Crustdata&apos;s last
          update, and an old profile is flagged as stale.
        </p>
      </div>
    </details>
  );
}

function safeHost(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "link";
  }
}
