"use client";
import { ArrowDown, ArrowUp, Flag, Pin } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate } from "@/lib/types";
import { claimCounts, evidenceStrength } from "@/lib/run-state";
import { Avatar, EvidenceStrip, FitBadge, GuardBadge, StatusPill } from "@/components/evidence";

export interface Row {
  c: Candidate;
  rank: number;
  pinned: boolean;
  dismissed: boolean;
  fresh: boolean;
}

export function ShortlistRows({ rows, selected, onSelect }: { rows: Row[]; selected?: string; onSelect: (id: string) => void }) {
  return (
    <ol className="flex flex-col">
      {rows.map(({ c, rank, pinned, dismissed }, i) => {
        const k = claimCounts(c);
        const active = selected === c.id;
        return (
          <li key={c.id} style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }} className="animate-rise">
            <button
              data-row={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "group relative grid w-full grid-cols-[22px_32px_minmax(0,1fr)_auto] items-center gap-3 border-b border-border px-4 py-3 text-left transition-colors",
                active ? "bg-elevated" : "hover:bg-panel",
                dismissed && "opacity-40",
              )}
            >
              {active && <span className="absolute inset-y-0 left-0 w-[2px] bg-primary" />}
              <span className="text-right font-mono text-[11px] text-faint tabular-nums">{rank}</span>
              <Avatar name={c.name} size={32} />
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className={cn("truncate text-[14px] font-[510]", dismissed && "line-through")}>{c.name}</span>
                  {pinned && <Pin className="size-3 shrink-0 fill-primary text-primary" />}
                  {k.contradicted > 0 && <StatusPill status="contradicted" count={k.contradicted} className="ml-0.5" />}
                  <GuardBadge guard={c.guard} />
                </div>
                <p className="truncate text-[12.5px] text-muted-foreground">
                  {[c.title, c.company].filter(Boolean).join(" · ") || "Title unknown"}
                  {c.location && <span className="text-faint"> · {c.location.split(",")[0]}</span>}
                </p>
                <div className="mt-1.5 flex min-w-0 items-center gap-2.5">
                  <EvidenceStrip candidate={c} />
                  <span className="shrink-0 font-mono text-[10.5px] text-faint tabular-nums">
                    {k.verified}/{k.total}
                  </span>
                  {c.reasons?.[0]?.text && <span className="hidden truncate text-[12px] text-secondary md:inline">{c.reasons[0].text}</span>}
                </div>
                {!!c.flags?.length && (
                  <div className="mt-1 flex flex-wrap gap-x-3">
                    {c.flags.slice(0, 2).map((f) => (
                      <span key={f} className="inline-flex items-center gap-1 text-[11px] font-[510] text-flag">
                        <Flag className="size-3" /> {f}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <FitBadge score={c.score} />
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export type SortKey = "rank" | "fit" | "evidence" | "contradicted" | "name";

const COLS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: "rank", label: "#", className: "w-10 text-right" },
  { key: "name", label: "Candidate" },
  { key: "fit", label: "Fit", className: "w-20 text-right" },
  { key: "evidence", label: "Evidence", className: "w-36" },
  { key: "contradicted", label: "Contradicted", className: "w-24 text-right" },
  { key: null, label: "Location", className: "w-32 hidden 2xl:table-cell" },
  { key: null, label: "Flags", className: "hidden 2xl:table-cell" },
];

export function CompareTable({
  rows,
  selected,
  onSelect,
  sort,
  dir,
  onSort,
}: {
  rows: Row[];
  selected?: string;
  onSelect: (id: string) => void;
  sort: SortKey;
  dir: 1 | -1;
  onSort: (k: SortKey) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-border text-left text-[11.5px] text-muted-foreground">
            {COLS.map((col) => (
              <th key={col.label} className={cn("h-8 px-3 font-[510]", col.className)}>
                {col.key ? (
                  <button onClick={() => onSort(col.key!)} className="inline-flex items-center gap-1 hover:text-foreground">
                    {col.label}
                    {sort === col.key && (dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
                  </button>
                ) : (
                  col.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ c, rank, pinned, dismissed }) => {
            const k = claimCounts(c);
            return (
              <tr
                key={c.id}
                data-row={c.id}
                onClick={() => onSelect(c.id)}
                className={cn(
                  "h-12 cursor-pointer border-b border-border transition-colors",
                  selected === c.id ? "bg-elevated" : "hover:bg-panel",
                  dismissed && "opacity-40",
                )}
              >
                <td className="px-3 text-right font-mono text-[11px] text-faint tabular-nums">{rank}</td>
                <td className="px-3">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={c.name} size={24} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 font-[510]">
                        {c.name} {pinned && <Pin className="size-3 fill-primary text-primary" />}
                      </div>
                      <div className="truncate text-[12px] text-muted-foreground">{[c.title, c.company].filter(Boolean).join(" · ")}</div>
                    </div>
                  </div>
                </td>
                <td className="px-3 text-right font-mono tabular-nums">{c.score ?? "–"}</td>
                <td className="px-3">
                  <div className="flex items-center gap-2">
                    <EvidenceStrip candidate={c} />
                    <span className="font-mono text-[11px] text-faint tabular-nums">{evidenceStrength(c)}%</span>
                  </div>
                </td>
                <td className={cn("px-3 text-right font-mono tabular-nums", k.contradicted ? "text-contradicted" : "text-faint")}>{k.contradicted}</td>
                <td className="hidden truncate px-3 text-[12px] text-secondary 2xl:table-cell">{c.location?.split(",")[0] ?? "–"}</td>
                <td className="hidden px-3 text-[12px] text-flag 2xl:table-cell">{(c.flags ?? []).join(" · ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
