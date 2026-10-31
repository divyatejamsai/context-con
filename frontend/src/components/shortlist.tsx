"use client";
import { ArrowDown, ArrowUp, Flag, Pin } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate } from "@/lib/types";
import { claimCounts, evidenceStrength } from "@/lib/run-state";
import { EvidenceStrip, FitMeter } from "@/components/evidence";

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
          <li key={c.id} style={{ animationDelay: `${Math.min(i, 6) * 40}ms` }} className="animate-rise">
            <button
              data-row={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "group relative grid w-full grid-cols-[40px_1fr_auto] items-start gap-3 border-b border-rule px-4 py-4 text-left transition-colors",
                active ? "bg-paper" : "hover:bg-paper/60",
                dismissed && "opacity-45",
              )}
            >
              <span className={cn("absolute inset-y-0 left-0 w-[3px]", active ? "bg-foreground" : k.contradicted ? "bg-contradicted" : "bg-transparent")} />
              <span className="font-display pt-0.5 text-3xl font-light leading-none tabular-nums text-muted-foreground group-hover:text-foreground">
                {String(rank).padStart(2, "0")}
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={cn("font-display truncate text-xl font-medium leading-tight", dismissed && "line-through")}>{c.name}</span>
                  {pinned && <Pin className="size-3.5 shrink-0 fill-foreground" />}
                </div>
                <p className="truncate text-sm text-muted-foreground">
                  {[c.title, c.company].filter(Boolean).join(" · ") || "Title unknown"}
                  {c.location && <span> · {c.location.split(",")[0]}</span>}
                </p>
                {c.reasons?.[0]?.text && <p className="mt-1.5 line-clamp-1 text-sm">{c.reasons[0].text}</p>}
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <EvidenceStrip candidate={c} />
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {k.verified}/{k.total} verified
                    {k.contradicted > 0 && <span className="text-contradicted"> · {k.contradicted} contradicted</span>}
                  </span>
                  {(c.flags ?? []).slice(0, 2).map((f) => (
                    <span key={f} className="inline-flex items-center gap-1 text-[11px] font-medium text-flag">
                      <Flag className="size-3" /> {f}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 pt-1">
                <FitMeter score={c.score} />
                <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">fit</span>
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export type SortKey = "rank" | "fit" | "evidence" | "contradicted" | "name";

const COLS: { key: SortKey | null; label: string; className?: string }[] = [
  { key: "rank", label: "#", className: "w-10" },
  { key: "name", label: "Candidate" },
  { key: "fit", label: "Fit", className: "w-28" },
  { key: "evidence", label: "Verified", className: "w-32" },
  { key: "contradicted", label: "✗", className: "w-12" },
  { key: null, label: "Location", className: "w-28 hidden 2xl:table-cell" },
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
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-foreground/70 text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            {COLS.map((col) => (
              <th key={col.label} className={cn("px-3 py-2 font-medium", col.className)}>
                {col.key ? (
                  <button onClick={() => onSort(col.key!)} className="inline-flex items-center gap-1 uppercase hover:text-foreground">
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
                  "cursor-pointer border-b border-rule transition-colors",
                  selected === c.id ? "bg-paper" : "hover:bg-paper/60",
                  dismissed && "opacity-45",
                )}
              >
                <td className="px-3 py-2.5 font-mono text-xs tabular-nums text-muted-foreground">{String(rank).padStart(2, "0")}</td>
                <td className="px-3 py-2.5">
                  <div className="font-display flex items-center gap-1.5 text-base font-medium">
                    {c.name} {pinned && <Pin className="size-3 fill-foreground" />}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">{[c.title, c.company].filter(Boolean).join(" · ")}</div>
                </td>
                <td className="px-3 py-2.5">
                  <FitMeter score={c.score} />
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <EvidenceStrip candidate={c} />
                    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{evidenceStrength(c)}%</span>
                  </div>
                </td>
                <td className={cn("px-3 py-2.5 font-mono text-xs tabular-nums", k.contradicted ? "font-medium text-contradicted" : "text-muted-foreground")}>
                  {k.contradicted}
                </td>
                <td className="hidden truncate px-3 py-2.5 text-xs 2xl:table-cell">{c.location?.split(",")[0] ?? "–"}</td>
                <td className="hidden px-3 py-2.5 text-xs text-flag 2xl:table-cell">{(c.flags ?? []).join(" · ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
