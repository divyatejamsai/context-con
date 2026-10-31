"use client";
import { ArrowDown, ArrowUp, Flag, Pin } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Candidate } from "@/lib/types";
import { claimCounts, evidenceStrength } from "@/lib/run-state";
import { Avatar, EvidenceStrip, FitBadge, StatusPill } from "@/components/evidence";

export interface Row {
  c: Candidate;
  rank: number;
  pinned: boolean;
  dismissed: boolean;
  fresh: boolean;
}

export function ShortlistRows({ rows, selected, onSelect }: { rows: Row[]; selected?: string; onSelect: (id: string) => void }) {
  return (
    <ol className="flex flex-col gap-3">
      {rows.map(({ c, rank, pinned, dismissed }, i) => {
        const k = claimCounts(c);
        const active = selected === c.id;
        return (
          <li key={c.id} style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }} className="animate-rise">
            <button
              data-row={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "press group relative grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border-2 border-ink p-3 text-left shadow-brut",
                active ? "bg-yellow text-on-color" : "bg-panel",
                dismissed && "opacity-45",
              )}
            >
              <span
                className={cn(
                  "font-display absolute -left-2.5 -top-2.5 grid size-7 place-items-center rounded-full border-2 border-ink text-[13px] font-extrabold shadow-brut-sm",
                  rank === 1 ? "bg-lime text-on-color" : "bg-panel text-foreground",
                )}
              >
                {rank}
              </span>
              <Avatar name={c.name} size={42} />
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className={cn("font-display truncate text-[17px] font-extrabold tracking-tight", dismissed && "line-through")}>{c.name}</span>
                  {pinned && <Pin className="size-3.5 shrink-0 fill-current" />}
                  {k.contradicted > 0 && <StatusPill status="contradicted" count={k.contradicted} className="ml-0.5" />}
                </div>
                <p className={cn("truncate text-[13px] font-medium", active ? "text-on-color/80" : "text-muted-foreground")}>
                  {[c.title, c.company].filter(Boolean).join(" · ") || "Title unknown"}
                  {c.location && <span> · {c.location.split(",")[0]}</span>}
                </p>
                <div className="mt-2 flex min-w-0 items-center gap-2">
                  <EvidenceStrip candidate={c} />
                  <span className="shrink-0 font-mono text-[11px] font-bold tabular-nums">
                    {k.verified}/{k.total}
                  </span>
                  {c.reasons?.[0]?.text && <span className="hidden truncate text-[12.5px] md:inline">{c.reasons[0].text}</span>}
                </div>
                {!!c.flags?.length && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {c.flags.slice(0, 2).map((f) => (
                      <span key={f} className="inline-flex items-center gap-1 rounded-md border-[1.5px] border-ink bg-coral/80 px-1.5 text-[11px] font-bold text-on-color">
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
  { key: "fit", label: "Fit", className: "w-16 text-right" },
  { key: "evidence", label: "Evidence", className: "w-40" },
  { key: "contradicted", label: "✗", className: "w-12 text-right" },
  { key: null, label: "Location", className: "w-32 hidden 2xl:table-cell" },
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
    <div className="overflow-x-auto rounded-xl border-2 border-ink bg-panel shadow-brut">
      <table className="w-full min-w-[520px] border-collapse text-[13px]">
        <thead>
          <tr className="border-b-2 border-ink bg-ink text-left text-[11px] uppercase tracking-wider text-background">
            {COLS.map((col) => (
              <th key={col.label} className={cn("h-9 px-3 font-bold", col.className)}>
                {col.key ? (
                  <button onClick={() => onSort(col.key!)} className="inline-flex items-center gap-1 uppercase">
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
                  "h-14 cursor-pointer border-b-2 border-ink/15 transition-colors last:border-0",
                  selected === c.id ? "bg-yellow text-on-color" : "hover:bg-hover",
                  dismissed && "opacity-40",
                )}
              >
                <td className="font-display px-3 text-right text-[15px] font-extrabold tabular-nums">{rank}</td>
                <td className="px-3">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={c.name} size={28} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 font-bold">
                        {c.name} {pinned && <Pin className="size-3 fill-current" />}
                      </div>
                      <div className="truncate text-[12px] opacity-70">{[c.title, c.company].filter(Boolean).join(" · ")}</div>
                    </div>
                  </div>
                </td>
                <td className="font-display px-3 text-right text-[17px] font-extrabold tabular-nums">{c.score ?? "–"}</td>
                <td className="px-3">
                  <div className="flex items-center gap-2">
                    <EvidenceStrip candidate={c} />
                    <span className="font-mono text-[11px] font-bold tabular-nums">{evidenceStrength(c)}%</span>
                  </div>
                </td>
                <td className="px-3 text-right">
                  {k.contradicted ? <StatusPill status="contradicted" count={k.contradicted} /> : <span className="font-mono text-faint">0</span>}
                </td>
                <td className="hidden truncate px-3 text-[12px] 2xl:table-cell">{c.location?.split(",")[0] ?? "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
