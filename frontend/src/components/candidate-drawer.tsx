"use client";
import { useState } from "react";
import { Check, Copy, ExternalLink, Flag, Mail } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ClaimBadge, normalizeStatus } from "@/components/claim-status";
import { ScoreRing } from "@/components/candidate-card";
import type { Candidate, Claim } from "@/lib/types";
import { cn } from "@/lib/utils";

function SourceLine({ claim }: { claim: Claim }) {
  const s = claim.source;
  if (!s || !s.endpoint) return <span className="text-contradicted">No source: treated as unverifiable</span>;
  const label = [s.endpoint, s.field].filter(Boolean).join(" → ");
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className="text-muted-foreground">Source</span>
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">Crustdata {label}</code>
      {s.url && (
        <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-primary hover:underline">
          link <ExternalLink className="size-3" />
        </a>
      )}
    </span>
  );
}

export function CandidateDrawer({ candidate: c, onClose }: { candidate: Candidate | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);

  const jumpTo = (id: string) => {
    setHighlight(id);
    document.getElementById(`claim-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setTimeout(() => setHighlight(null), 1500);
  };

  const copy = async () => {
    if (!c?.outreach_draft) return;
    try {
      await navigator.clipboard.writeText(c.outreach_draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  // Order claims so contradicted ones are seen first.
  const order = { contradicted: 0, verified: 1, unverifiable: 2 } as const;
  const claims = [...(c?.claims ?? [])].sort((a, b) => order[normalizeStatus(a.status)] - order[normalizeStatus(b.status)]);

  return (
    <Sheet open={!!c} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        {c && (
          <div className="flex h-full flex-col overflow-y-auto">
            <header className="flex items-start gap-4 border-b border-border p-6 pr-12">
              <ScoreRing score={c.score} size={60} />
              <div className="min-w-0">
                <SheetTitle className="text-xl font-semibold">{c.name}</SheetTitle>
                <SheetDescription className="text-sm text-muted-foreground">
                  {[c.title, c.company, c.location].filter(Boolean).join(" · ")}
                </SheetDescription>
                {c.profile_url && (
                  <a
                    href={c.profile_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    Profile <ExternalLink className="size-3" />
                  </a>
                )}
                {!!c.flags?.length && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {c.flags.map((f) => (
                      <Badge key={f} variant="flag">
                        <Flag />
                        {f}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </header>

            <section className="border-b border-border p-6">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Why this candidate</h4>
              {c.reasons?.length ? (
                <ul className="flex flex-col gap-2.5">
                  {c.reasons.map((r, i) => (
                    <li key={i} className="text-sm">
                      {r.text}
                      {r.claim_ids?.map((id) => (
                        <button
                          key={id}
                          onClick={() => jumpTo(id)}
                          className="ml-1 rounded bg-primary/10 px-1 align-super font-mono text-[10px] text-primary hover:bg-primary/20"
                          title="Jump to evidence"
                        >
                          {id}
                        </button>
                      ))}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No ranking reasons yet.</p>
              )}
            </section>

            <section className="border-b border-border p-6">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Claims checked ({claims.length})
              </h4>
              <ul className="flex flex-col gap-3">
                {claims.map((k) => {
                  const status = k.source?.endpoint ? normalizeStatus(k.status) : "unverifiable";
                  return (
                    <li
                      id={`claim-${k.id}`}
                      key={k.id}
                      className={cn(
                        "rounded-lg border border-border p-3 transition-colors",
                        status === "contradicted" && "border-contradicted/40 bg-contradicted/5",
                        highlight === k.id && "ring-2 ring-ring",
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium">
                          <span className="mr-1.5 font-mono text-[10px] text-muted-foreground">{k.id}</span>
                          {k.claim}
                        </p>
                        <ClaimBadge status={status} />
                      </div>
                      {k.evidence && <p className="mt-1.5 text-sm text-muted-foreground">{k.evidence}</p>}
                      <div className="mt-2 text-xs">
                        <SourceLine claim={k} />
                      </div>
                    </li>
                  );
                })}
                {!claims.length && <p className="text-sm text-muted-foreground">No claims verified for this candidate.</p>}
              </ul>
            </section>

            <section className="p-6">
              <div className="mb-3 flex items-center justify-between">
                <h4 className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <Mail className="size-3.5" /> Outreach draft
                </h4>
                {c.outreach_draft && (
                  <Button variant="outline" size="sm" onClick={copy}>
                    {copied ? <Check /> : <Copy />}
                    {copied ? "Copied" : "Copy"}
                  </Button>
                )}
              </div>
              {c.outreach_draft ? (
                <>
                  <pre className="whitespace-pre-wrap rounded-lg bg-muted p-4 font-sans text-sm leading-relaxed">{c.outreach_draft}</pre>
                  <p className="mt-2 text-xs text-muted-foreground">Draft only. The agent never sends messages.</p>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No draft: the agent only drafts outreach for strong, verified matches.</p>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
