"use client";
import { useEffect, useRef, useState } from "react";
import { CircleAlert, Database, Loader2, Play, ShieldAlert, ShieldCheck, Square, UserX } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { StatusPill as ClaimPill } from "@/components/evidence";
import { Button, EmptyState, Field, HowTo, SectionHead, SourceChip, cardCls, inputCls } from "@/app/console/parts";
import { FLAG_LABEL, LIE_LABEL, TalentError, label, pct, sse, talent, type Screening, type StaffingEvent, type StaffingReport } from "@/lib/talent";
import { cn } from "@/lib/utils";

const ROLE_LABEL: Record<string, string> = {
  delivery: "Delivery", warehouse: "Warehouse", support: "Customer support", retail: "Retail", security: "Security", hospitality: "Hospitality",
};

type Step = { step: string; message: string; data?: Record<string, number> };

export default function StaffingPage() {
  const [shifts, setShifts] = useState(1000);
  const [fakeRate, setFakeRate] = useState(15);
  const [seed, setSeed] = useState(7);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [flagged, setFlagged] = useState<Screening[]>([]);
  const [report, setReport] = useState<StaffingReport | null>(null);
  const [fromLast, setFromLast] = useState(false);
  const [err, setErr] = useState<{ msg: string; noPool?: boolean } | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    talent
      .staffingLast()
      .then((r) => {
        setReport(r.report);
        setFromLast(true);
      })
      .catch(() => {});
  }, []);

  const run = async () => {
    const ctl = new AbortController();
    abort.current = ctl;
    setRunning(true);
    setErr(null);
    setSteps([]);
    setFlagged([]);
    setReport(null);
    setFromLast(false);
    try {
      for await (const ev of sse<StaffingEvent>("/staffing/run", { shifts, fake_rate: fakeRate / 100, seed, source: "fixture" }, ctl.signal)) {
        if (ev.type === "step") setSteps((s) => [...s, ev]);
        else if (ev.type === "flagged") setFlagged((f) => [...f, ev.screening]);
        else if (ev.type === "done") setReport(ev.report);
        else if (ev.type === "error") setErr({ msg: ev.message, noPool: /no recorded applicant pool/i.test(ev.message) });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        const msg = e instanceof Error ? e.message : String(e);
        setErr({
          msg: e instanceof TalentError && e.status === 401 ? "The backend needs an admin token for this. Set it with the key icon in the Countersign console, then try again." : msg,
          noPool: /no recorded applicant pool/i.test(msg),
        });
      }
    } finally {
      setRunning(false);
      abort.current = null;
    }
  };

  const screen = [...steps].reverse().find((s) => s.step === "screen")?.data;
  const total = steps.find((s) => s.step === "ingest")?.data?.applications;

  return (
    <div className="min-h-screen">
      <AppHeader active="/staffing" />
      <main className="mx-auto max-w-[1280px] space-y-6 px-4 py-6 sm:px-6 sm:py-10">
        <div>
          <h1 className="text-[26px] font-[590] leading-tight tracking-[-0.025em]">Fill shifts without hiring the fakes</h1>
          <p className="mt-2 max-w-[680px] text-[14px] leading-relaxed text-muted-foreground">
            Sourced takes a pile of applications for delivery, warehouse, support, retail, security and hospitality shifts across six cities. It checks
            every application against the person&apos;s Crustdata record (employer, title, tenure, city, and whether the profile is really theirs) and
            only gives shifts to people who cleared.
          </p>
        </div>

        <HowTo
          steps={[
            <>Pick how many shifts to fill and how many applications carry a <b className="font-[510]">planted lie</b>, so you can see if Sourced catches them.</>,
            <>Click <b className="font-[510]">Run staffing</b>. Every application is screened; flagged ones appear below as they are caught, with the record that disproves them.</>,
            <>Read the report: shifts filled by city and role, and how many of the planted fakes were caught.</>,
          ]}
        />

        <section className={cn(cardCls, "p-4")}>
          <div className="grid items-end gap-3 sm:grid-cols-[repeat(3,minmax(0,160px))_1fr]">
            <Field label="Shifts to fill" hint="Over the next few days">
              <input type="number" min={1} max={10000} value={shifts} onChange={(e) => setShifts(Math.max(1, Math.min(10000, Number(e.target.value) || 1)))} className={inputCls} disabled={running} />
            </Field>
            <Field label="Planted lies (%)" hint="Share of fake applications">
              <input type="number" min={0} max={90} value={fakeRate} onChange={(e) => setFakeRate(Math.max(0, Math.min(90, Number(e.target.value) || 0)))} className={inputCls} disabled={running} />
            </Field>
            <Field label="Seed" hint="Same seed, same run">
              <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} className={inputCls} disabled={running} />
            </Field>
            <div className="flex flex-wrap items-center justify-end gap-2 pb-[18px]">
              {running ? (
                <Button onClick={() => abort.current?.abort()} title="Stop watching this run">
                  <Square className="size-3.5" /> Stop
                </Button>
              ) : (
                <Button variant="primary" onClick={run} title="Screen every application and assign the shifts">
                  <Play className="size-3.5" /> Run staffing
                </Button>
              )}
            </div>
          </div>
          <p className="mt-1 flex items-center gap-1.5 text-[11.5px] text-faint">
            <Database className="size-3.5" />
            Applicants come from a recorded Crustdata pool of real shift workers. Nobody is contacted: the run only reads records.
          </p>
        </section>

        {err && (
          err.noPool ? (
            <div className={cardCls}>
              <EmptyState icon={Database} title="The applicant pool hasn't been recorded yet">
                Someone with a Crustdata key runs <span className="font-mono text-[11.5px]">python scripts/run_talent.py --live</span> once in the backend. After that, this page replays the recorded pool.
              </EmptyState>
            </div>
          ) : (
            <p className="flex items-start gap-2 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">
              <CircleAlert className="mt-0.5 size-3.5 shrink-0" /> {err.msg}
            </p>
          )
        )}

        {(running || steps.length > 0) && (
          <section className={cn(cardCls, "p-4")}>
            <SectionHead title="Progress" aside={running ? <Loader2 className="size-4 animate-spin text-primary" /> : undefined} />
            {total && screen && (
              <div className="mt-3">
                <div className="flex h-2 overflow-hidden rounded-full bg-elevated">
                  <div className="bg-verified transition-all" style={{ width: `${((screen.cleared ?? 0) / total) * 100}%` }} />
                  <div className="bg-contradicted transition-all" style={{ width: `${((screen.flagged ?? 0) / total) * 100}%` }} />
                  <div className="bg-border-strong transition-all" style={{ width: `${((screen.not_qualified ?? 0) / total) * 100}%` }} />
                </div>
                <p className="mt-1.5 text-[12px] tabular-nums text-muted-foreground">
                  {screen.done ?? 0} of {total} screened · <span className="text-verified">{screen.cleared ?? 0} cleared</span> · <span className="text-contradicted">{screen.flagged ?? 0} flagged</span>
                  {screen.not_qualified ? ` · ${screen.not_qualified} not qualified` : ""}
                </p>
              </div>
            )}
            <ol className="mt-3 space-y-1">
              {steps.filter((s, i) => s.step !== "screen" || i === steps.map((x) => x.step).lastIndexOf("screen")).map((s, i) => (
                <li key={i} className="flex gap-2 text-[12.5px]">
                  <span className="w-16 shrink-0 font-mono text-[11px] text-faint">{s.step}</span>
                  <span className="text-secondary">{s.message}</span>
                </li>
              ))}
            </ol>
          </section>
        )}

        {report ? <Report report={report} fromLast={fromLast} /> : !running && !err && steps.length === 0 && (
          <div className={cardCls}>
            <EmptyState icon={Play} title="No run yet">Set the numbers above and click Run staffing. A run of 1,000 shifts takes a few seconds.</EmptyState>
          </div>
        )}

        {flagged.length > 0 && <Flagged rows={flagged} />}
      </main>
    </div>
  );
}

function Report({ report: r, fromLast }: { report: StaffingReport; fromLast: boolean }) {
  const fc = r.fake_catch;
  const staffedFakes = fc?.fakes_staffed?.length ?? 0;
  return (
    <div className="space-y-6">
      {fromLast && <p className="text-[12px] text-faint">Showing the last run on this backend. Run again to see each flagged application.</p>}
      <div className="grid gap-px overflow-hidden rounded-xl border border-border-strong bg-border sm:grid-cols-4">
        <Tile k="Shifts filled" v={`${r.filled} / ${r.shifts}`} sub={`${pct(r.fill_rate, 1)} fill rate`} />
        <Tile k="Applications screened" v={String(r.screening.cleared + r.screening.flagged + (r.screening.not_qualified ?? 0))} sub={`${r.screening.cleared} cleared · ${r.screening.flagged} flagged`} />
        <Tile k="Workers used" v={String(r.workers_used ?? "–")} sub={r.workers_cleared ? `of ${r.workers_cleared} cleared` : undefined} />
        <Tile
          k="Fakes given a shift"
          v={String(staffedFakes)}
          sub={staffedFakes ? "a planted lie got through" : "no planted lie got a shift"}
          tone={staffedFakes ? "text-contradicted" : "text-verified"}
        />
      </div>

      {fc && (
        <section className={cn(cardCls, "p-4")}>
          <SectionHead
            title="Did Sourced catch the planted lies?"
            aside={
              <span className="flex gap-3 text-[12px] text-muted-foreground">
                <span title="Of everything Sourced flagged, the share that really was a planted lie">Precision <b className="font-[590] tabular-nums text-foreground">{pct(fc.precision, 1)}</b></span>
                <span title="Of all planted lies, the share Sourced caught">Recall <b className="font-[590] tabular-nums text-foreground">{pct(fc.recall, 1)}</b></span>
              </span>
            }
          >
            {fc.fakes_planted} of {fc.applications} applications carried one lie. Sourced flagged {fc.flagged}: {fc.true_positives} real lies,{" "}
            {fc.false_positives} honest people flagged by mistake, {fc.false_negatives} lies missed.
          </SectionHead>
          <ul className="mt-4 grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
            {Object.entries(fc.by_lie_type).sort((a, b) => b[1].planted - a[1].planted).map(([k, v]) => (
              <li key={k}>
                <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
                  <span>{label(LIE_LABEL, k)}</span>
                  <span className="tabular-nums text-muted-foreground">{v.caught} of {v.planted} caught</span>
                </div>
                <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-elevated">
                  <div className={cn("rounded-full", v.caught === v.planted ? "bg-verified" : "bg-flag")} style={{ width: `${v.planted ? (v.caught / v.planted) * 100 : 0}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <FillTable title="Shifts filled by city" rows={r.by_city} />
        <FillTable title="Shifts filled by type of work" rows={r.by_role} names={ROLE_LABEL} />
      </div>

      {Object.keys(r.open_reasons).length > 0 && (
        <section className={cn(cardCls, "p-4")}>
          <SectionHead title="Why some shifts are still open">The shifts nobody cleared could take, grouped by reason.</SectionHead>
          <ul className="mt-3 space-y-1">
            {Object.entries(r.open_reasons).map(([k, n]) => (
              <li key={k} className="flex justify-between text-[12.5px]"><span>{k.replace(/_/g, " ")}</span><span className="tabular-nums text-muted-foreground">{n}</span></li>
            ))}
          </ul>
        </section>
      )}
      {r.pool && <p className="text-[11.5px] text-faint">Applicant pool: {r.pool.records} records · source: {r.pool.source === "fixture" ? "recorded Crustdata pool" : "live Crustdata search"}{r.today ? ` · run date ${r.today}` : ""}</p>}
    </div>
  );
}

function Tile({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: string }) {
  return (
    <div className="bg-panel px-4 py-3">
      <p className="text-[11.5px] text-muted-foreground">{k}</p>
      <p className={cn("mt-0.5 text-[22px] font-[620] tabular-nums tracking-[-0.02em]", tone)}>{v}</p>
      {sub && <p className="text-[11px] text-faint">{sub}</p>}
    </div>
  );
}

function FillTable({ title, rows, names }: { title: string; rows: StaffingReport["by_city"]; names?: Record<string, string> }) {
  const max = Math.max(1, ...Object.values(rows).map((r) => r.filled));
  return (
    <section className={cn(cardCls, "p-4")}>
      <SectionHead title={title} />
      <ul className="mt-3 space-y-2">
        {Object.entries(rows).sort((a, b) => b[1].filled - a[1].filled).map(([k, v]) => (
          <li key={k} className="grid grid-cols-[120px_minmax(0,1fr)_88px] items-center gap-3 text-[12.5px]">
            <span className="truncate">{names?.[k] ?? k}</span>
            <span className="h-1.5 overflow-hidden rounded-full bg-elevated">
              <span className="block h-full rounded-full bg-primary/80" style={{ width: `${(v.filled / max) * 100}%` }} />
            </span>
            <span className="text-right tabular-nums text-muted-foreground">
              {v.filled} · <span className={v.fill_rate < 1 ? "text-flag" : undefined}>{pct(v.fill_rate)}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Flagged({ rows }: { rows: Screening[] }) {
  const [kind, setKind] = useState<string>("all");
  const kinds = [...new Set(rows.map((r) => r.kind ?? "other"))];
  const shown = kind === "all" ? rows : rows.filter((r) => (r.kind ?? "other") === kind);
  return (
    <section className={cn(cardCls, "overflow-hidden")}>
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border px-4 py-3">
        <SectionHead title={`Flagged applications (${rows.length})`}>No shift was given to these people. Open one to see which record disproves the application.</SectionHead>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="h-7 rounded-md border border-border-strong bg-panel px-1.5 text-[12px]">
          <option value="all">All reasons</option>
          {kinds.map((k) => <option key={k} value={k}>{label(FLAG_LABEL, k)} ({rows.filter((r) => (r.kind ?? "other") === k).length})</option>)}
        </select>
      </div>
      <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
        {shown.map((s) => (
          <li key={s.app_id}>
            <details className="group">
              <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-2.5 hover:bg-hover">
                {s.kind === "identity_unverifiable" ? <ShieldAlert className="mt-0.5 size-4 shrink-0 text-flag" /> : s.kind === "identity_mismatch" ? <UserX className="mt-0.5 size-4 shrink-0 text-contradicted" /> : <ShieldCheck className="mt-0.5 size-4 shrink-0 text-contradicted" />}
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-[13px] font-[510]">{s.name}</span>
                    <span className="text-[11.5px] text-muted-foreground">{ROLE_LABEL[s.role] ?? s.role} · {s.city} · {s.app_id}</span>
                  </span>
                  <span className="block text-[12px] text-secondary">{s.reason}</span>
                </span>
                <span className="shrink-0 rounded border border-border px-1.5 py-px text-[10.5px] text-muted-foreground">{label(FLAG_LABEL, s.kind ?? "other")}</span>
              </summary>
              {(s.claims?.length ?? 0) > 0 && (
                <ul className="divide-y divide-border border-t border-border bg-elevated/60 px-4">
                  {s.claims!.map((c, i) => (
                    <li key={`${c.id}-${i}`} className="flex flex-wrap items-start justify-between gap-2 py-2 pl-7">
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12.5px]">{c.claim}</span>
                        {c.evidence && <span className="block text-[11.5px] text-muted-foreground">{c.evidence}</span>}
                      </span>
                      <span className="flex flex-col items-end gap-1">
                        <ClaimPill status={c.source?.endpoint ? c.status : "unverifiable"} />
                        <SourceChip source={c.source} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}
