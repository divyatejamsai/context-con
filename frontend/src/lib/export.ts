import type { Candidate, Criteria } from "./types";
import { claimCounts, normalizeStatus } from "./run-state";

const srcText = (s?: { endpoint: string; field?: string | null; url?: string | null } | null) =>
  !s?.endpoint ? "no source" : `Crustdata ${s.endpoint}${s.field ? ` → ${s.field}` : ""}${s.url ? ` (${s.url})` : ""}`;

export function toMarkdown(brief: string, criteria: Criteria | undefined, cands: Candidate[]): string {
  const lines: string[] = [`# Shortlist`, ``, `> ${brief.trim()}`, ``];
  if (criteria?.role) lines.push(`**Role:** ${criteria.role}${criteria.seniority ? ` (${criteria.seniority})` : ""}`, ``);
  cands.forEach((c, i) => {
    const k = claimCounts(c);
    lines.push(`## ${i + 1}. ${c.name} · fit ${c.score ?? "–"}/100`);
    lines.push(`${[c.title, c.company, c.location].filter(Boolean).join(" · ")}${c.profile_url ? `  \n${c.profile_url}` : ""}`, ``);
    lines.push(`Evidence: ${k.verified} verified, ${k.contradicted} contradicted, ${k.unverifiable} unverifiable`);
    if (c.flags?.length) lines.push(`Flags: ${c.flags.join("; ")}`);
    lines.push(``, `**Why**`);
    for (const r of c.reasons ?? []) lines.push(`- ${r.text}${r.claim_ids?.length ? ` [${r.claim_ids.join(", ")}]` : ""}`);
    lines.push(``, `**Claims**`);
    for (const cl of c.claims ?? [])
      lines.push(`- [${cl.id}] ${normalizeStatus(cl.status, !!cl.source?.endpoint).toUpperCase()}: ${cl.claim}. ${cl.evidence ?? ""} _(${srcText(cl.source)})_`);
    if (c.outreach_draft) lines.push(``, `**Outreach draft**`, ``, ...c.outreach_draft.split("\n").map((l) => `> ${l}`));
    lines.push(``);
  });
  return lines.join("\n");
}

export function toCSV(cands: Candidate[]): string {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = ["rank", "name", "title", "company", "location", "fit", "verified", "contradicted", "unverifiable", "flags", "profile_url"];
  const rows = cands.map((c, i) => {
    const k = claimCounts(c);
    return [i + 1, c.name, c.title, c.company, c.location, c.score, k.verified, k.contradicted, k.unverifiable, (c.flags ?? []).join("; "), c.profile_url];
  });
  return [head, ...rows].map((r) => r.map(esc).join(",")).join("\n");
}

export function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
