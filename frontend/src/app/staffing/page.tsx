"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleAlert, Copy, Database, Download, Search, FileUp, FlaskConical, Loader2, Play, Plus, ShieldAlert, ShieldCheck, Square, Trash2, UserX, Users,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { StatusPill as ClaimPill } from "@/components/evidence";
import { Button, EmptyState, Field, HowTo, SectionHead, SourceChip, cardCls, inputCls } from "@/app/console/parts";
import {
  FLAG_LABEL, LIE_LABEL, TalentError, label, pct, ssePost, staffingUrl, talent,
  type GrowEvent, type Role, type RosterRow, type Screening, type StaffingEvent, type StaffingReport, type StaffingTemplates, type Upload,
} from "@/lib/talent";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const STORE = "sourced.staffing.v2";

type Step = { step: string; message: string; data?: Record<string, number> };
type Source = "recorded" | "upload";

interface Settings {
  template: string; roles: Role[]; start: string; days: number; source: Source; bench: number; rest: number; liveLookups: number;
  test: boolean; fakeRate: number; dupRate: number; noShowRate: number; seed: number;
}

const tomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
};

const list = (s: string) => s.split(/[,;]/).map((x) => x.trim()).filter(Boolean);
const slotsText = (r: Role) => r.slots.map((s) => `${s.start}-${s.end}`).join(", ");
const parseSlots = (s: string) => [...s.matchAll(/(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})/g)].map((m) => ({ start: m[1].padStart(5, "0"), end: m[2].padStart(5, "0") }));

/** Seats a role adds over the horizon: cities x days it runs x shift times x workers per shift. */
function seats(r: Role, start: string, days: number) {
  const d0 = new Date(`${start}T00:00:00`);
  let n = 0;
  for (let i = 0; i < days; i++) {
    const wd = (new Date(d0.getTime() + i * 86400000).getDay() + 6) % 7;
    if (!r.days.includes(wd)) continue;
    for (const c of r.cities) n += (r.city_headcount?.[c] ?? r.headcount) * r.slots.length;
  }
  return n;
}

function load(): Partial<Settings> {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

export default function StaffingPage() {
  const [tpl, setTpl] = useState<StaffingTemplates | null>(null);
  const [cfg, setCfg] = useState<Settings>({
    template: "quick-commerce", roles: [], start: tomorrow(), days: 7, source: "recorded", bench: 10, rest: 10, liveLookups: 0,
    test: false, fakeRate: 15, dupRate: 3, noShowRate: 8, seed: 7,
  });
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [flagged, setFlagged] = useState<Screening[]>([]);
  const [report, setReport] = useState<StaffingReport | null>(null);
  const [fromLast, setFromLast] = useState(false);
  const [runId, setRunId] = useState(0);
  const [err, setErr] = useState<{ msg: string; noPool?: boolean } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const set = (p: Partial<Settings>) => setCfg((c) => ({ ...c, ...p }));

  const refreshPool = () => talent.staffingTemplates().then(setTpl).catch(() => {});

  useEffect(() => {
    talent
      .staffingTemplates()
      .then((t) => {
        setTpl(t);
        const saved = load();
        setCfg((c) => {
          const next = { ...c, ...saved, start: saved.start && saved.start >= tomorrow() ? saved.start : c.start };
          if (!next.roles?.length) next.roles = t.templates.find((x) => x.id === (saved.template ?? t.default))?.roles ?? t.templates[0].roles;
          return next;
        });
      })
      .catch((e) => setErr({ msg: e instanceof Error ? e.message : String(e) }));
    talent
      .staffingLast()
      .then((r) => {
        setReport(r.report);
        setFromLast(true);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!tpl) return;
    try {
      localStorage.setItem(STORE, JSON.stringify(cfg));
    } catch {
      // private window: settings just aren't remembered
    }
  }, [cfg, tpl]);

  const total = useMemo(() => cfg.roles.reduce((n, r) => n + seats(r, cfg.start, cfg.days), 0), [cfg.roles, cfg.start, cfg.days]);
  const inPool = (r: Role) => tpl?.pool_by_role?.[r.id] ?? 0;
  const thinRoles = cfg.source === "recorded" && tpl ? cfg.roles.filter((r) => inPool(r) < 30 && !recordedLike(r, tpl)) : [];

  const pickTemplate = (id: string) => {
    const t = tpl?.templates.find((x) => x.id === id);
    if (t) set({ template: id, roles: structuredClone(t.roles) });
  };

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setUploading(true);
    setErr(null);
    try {
      const up = await talent.staffingUpload(await f.text(), f.name);
      setUpload(up);
      set({ source: "upload", test: false });
    } catch (e) {
      setErr({ msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setUploading(false);
    }
  };

  const run = async () => {
    const ctl = new AbortController();
    abort.current = ctl;
    setRunning(true);
    setErr(null);
    setSteps([]);
    setFlagged([]);
    setReport(null);
    setFromLast(false);
    const testOn = cfg.test && cfg.source === "recorded";
    try {
      for await (const ev of ssePost<StaffingEvent>("/staffing/run/stream", {
        roles: cfg.roles, start: cfg.start, days: cfg.days, source: cfg.source, upload_id: upload?.upload_id,
        bench_rate: cfg.bench / 100, rest_hours: cfg.rest, live_lookups: cfg.source === "upload" ? cfg.liveLookups : 0,
        test_mode: testOn, fake_rate: cfg.fakeRate / 100, duplicate_rate: cfg.dupRate / 100, no_show_rate: cfg.noShowRate / 100, seed: cfg.seed,
      }, ctl.signal)) {
        if (ev.type === "step") setSteps((s) => [...s, ev]);
        else if (ev.type === "flagged") setFlagged((f) => [...f, ev.screening]);
        else if (ev.type === "done") {
          setReport(ev.report);
          setRunId((n) => n + 1);
        } else if (ev.type === "error") setErr({ msg: ev.message, noPool: /no recorded applicant pool/i.test(ev.message) });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        const msg = e instanceof Error ? e.message : String(e);
        setErr({
          msg: e instanceof TalentError && e.status === 401 ? `The backend needs an admin token for this. Set it with the key icon in the ${BRAND.name} console, then try again.` : msg,
          noPool: /no recorded applicant pool/i.test(msg),
        });
      }
    } finally {
      setRunning(false);
      abort.current = null;
    }
  };

  const screen = [...steps].reverse().find((s) => s.step === "screen")?.data;
  const totalApps = steps.find((s) => s.step === "ingest")?.data?.applications;
  const canRun = !running && cfg.roles.length > 0 && total > 0 && (cfg.source === "recorded" || !!upload);

  return (
    <div className="min-h-screen">
      <AppHeader active="/staffing" />
      <main className="mx-auto max-w-[1280px] space-y-6 px-4 py-6 sm:px-6 sm:py-10">
        <div>
          <h1 className="text-[26px] font-[590] leading-tight tracking-[-0.025em]">Fill shifts at volume without hiring the fakes</h1>
          <p className="mt-2 max-w-[720px] text-[14px] leading-relaxed text-muted-foreground">
            For any role you hire for in bulk: delivery and warehouse, BPO agents, festive retail staff, nurses, event crews or campus freshers. Sourced
            checks every application against the person&apos;s Crustdata record (employer, title, tenure, city, and whether the profile is really theirs),
            checks it against the role&apos;s own requirements, merges people who applied twice, and only books people who cleared. Nobody is booked on two
            shifts at once, and every shift gets backups for no-shows.
          </p>
        </div>

        <HowTo
          steps={[
            <>Set up the <b className="font-[510]">roles</b> you&apos;re hiring for, or start from a template. Each role has its own cities, shift times, headcount and requirements.</>,
            <>Add <b className="font-[510]">applications</b>: upload a CSV, or use the recorded Crustdata pool of real shift workers.</>,
            <>Click <b className="font-[510]">Run staffing</b>. Read the roster, who was screened out and why, and the backup bench.</>,
          ]}
        />

        <RolesCard
          cfg={cfg} set={set} tpl={tpl} total={total} running={running} onTemplate={pickTemplate} thinRoles={thinRoles}
        />

        <section className={cn(cardCls, "p-4")}>
          <SectionHead title="Applications">Where the applicants come from. Recorded data is used first, so a run costs no Crustdata credits.</SectionHead>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <SourceOption
              active={cfg.source === "recorded"} onClick={() => set({ source: "recorded" })} disabled={running} icon={Database}
              title="Recorded Crustdata pool" detail={`${(tpl?.pool_total ?? 0).toLocaleString()} real people found with Crustdata searches for these kinds of roles, saved so a run costs no credits.`}
            />
            <SourceOption
              active={cfg.source === "upload"} onClick={() => set({ source: "upload", test: false })} disabled={running} icon={FileUp}
              title="Upload a CSV" detail={upload ? `${upload.name ?? "Upload"}: ${upload.applications.toLocaleString()} applications` : "Your own applications: one row per applicant, with their profile URL."}
            />
          </div>
          {cfg.source === "recorded" && <GrowPool roles={cfg.roles} template={cfg.template} tpl={tpl} disabled={running} onDone={refreshPool} />}
          {cfg.source === "upload" && (
            <div className="mt-3 space-y-3 rounded-lg border border-border bg-elevated/60 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <label className={cn("inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border-strong bg-panel px-3 text-[12.5px] font-[510] text-secondary hover:bg-hover", (running || uploading) && "pointer-events-none opacity-40")}>
                  {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <FileUp className="size-3.5" />} {upload ? "Replace CSV" : "Choose CSV"}
                  <input type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />
                </label>
                <a href={staffingUrl(`/staffing/sample.csv?template=${encodeURIComponent(cfg.template)}`)} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-muted-foreground hover:bg-elevated hover:text-foreground">
                  <Download className="size-3.5" /> Sample CSV
                </a>
              </div>
              <p className="text-[11.5px] leading-relaxed text-faint">
                Columns (names are matched loosely): <span className="font-mono">{(tpl?.csv_columns ?? ["name", "profile_url", "phone", "email", "role", "city"]).join(", ")}</span>.
                Role can be the role&apos;s title. Availability takes days like &quot;Mon-Fri&quot; or &quot;weekends&quot;; skills, certifications and languages are separated by semicolons.
              </p>
              {upload && (
                <div className="text-[12.5px] text-secondary">
                  <p>
                    <b className="font-[590] tabular-nums">{upload.applications.toLocaleString()}</b> applications read ·{" "}
                    <span className="tabular-nums">{upload.in_recorded_data.toLocaleString()}</span> already in the recorded data
                    {upload.no_profile_url ? ` · ${upload.no_profile_url} without a profile URL` : ""}
                    {upload.error_count ? <span className="text-flag"> · {upload.error_count} rows skipped</span> : ""}
                  </p>
                  {upload.errors.length > 0 && (
                    <p className="mt-1 text-[11.5px] text-muted-foreground">{upload.errors.slice(0, 3).map((e) => `row ${e.row}: ${e.error}`).join(" · ")}</p>
                  )}
                  <p className="mt-1 text-[11.5px] text-muted-foreground">
                    Roles in the file: {Object.entries(upload.roles).slice(0, 6).map(([k, n]) => `${k} (${n})`).join(", ")}
                  </p>
                </div>
              )}
              <div className="grid items-end gap-3 sm:grid-cols-[220px_1fr]">
                <Field label="Live Crustdata lookups" hint="Profiles not in the recorded data. 0 holds them instead.">
                  <input type="number" min={0} max={1000} value={cfg.liveLookups} onChange={(e) => set({ liveLookups: clamp(e.target.value, 0, 1000) })} className={inputCls} disabled={running} />
                </Field>
                <p className="pb-[18px] text-[11.5px] text-faint">
                  {cfg.liveLookups > 0
                    ? `Up to ${cfg.liveLookups} profiles are looked up on Crustdata, which uses credits. The rest are held for later.`
                    : upload && upload.applications - upload.in_recorded_data > 0
                      ? `${(upload.applications - upload.in_recorded_data).toLocaleString()} profiles aren't in the recorded data. They'll be held, not flagged, until they're looked up.`
                      : "No credits are used."}
                </p>
              </div>
            </div>
          )}
        </section>

        <section className={cn(cardCls, "p-4")}>
          <div className="grid items-end gap-3 sm:grid-cols-[repeat(2,minmax(0,170px))_1fr]">
            <Field label="Backup bench (%)" hint="Standby workers per shift, for no-shows">
              <input type="number" min={0} max={100} value={cfg.bench} onChange={(e) => set({ bench: clamp(e.target.value, 0, 100) })} className={inputCls} disabled={running} />
            </Field>
            <Field label="Rest between shifts (hours)" hint="Nobody works shifts closer than this">
              <input type="number" min={0} max={24} value={cfg.rest} onChange={(e) => set({ rest: clamp(e.target.value, 0, 24) })} className={inputCls} disabled={running} />
            </Field>
            <div className="flex flex-wrap items-center justify-end gap-3 pb-[18px]">
              <span className="text-[12px] tabular-nums text-muted-foreground">{total.toLocaleString()} shifts · {cfg.roles.length} roles</span>
              {running ? (
                <Button onClick={() => abort.current?.abort()} title="Stop watching this run">
                  <Square className="size-3.5" /> Stop
                </Button>
              ) : (
                <Button variant="primary" onClick={run} disabled={!canRun} title={canRun ? "Screen every application and book the shifts" : cfg.source === "upload" && !upload ? "Upload a CSV first" : "Add a role with at least one shift"}>
                  <Play className="size-3.5" /> Run staffing
                </Button>
              )}
            </div>
          </div>
          <p className="mt-1 flex items-center gap-1.5 text-[11.5px] text-faint">
            <Database className="size-3.5" /> Nobody is contacted: the run only reads records and builds a roster.
          </p>
        </section>

        <TestMode cfg={cfg} set={set} running={running} />

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
            {totalApps && screen && (
              <div className="mt-3">
                <div className="flex h-2 overflow-hidden rounded-full bg-elevated">
                  <div className="bg-verified transition-all" style={{ width: `${((screen.cleared ?? 0) / totalApps) * 100}%` }} />
                  <div className="bg-contradicted transition-all" style={{ width: `${((screen.flagged ?? 0) / totalApps) * 100}%` }} />
                  <div className="bg-border-strong transition-all" style={{ width: `${(((screen.not_qualified ?? 0) + (screen.duplicate ?? 0) + (screen.held ?? 0)) / totalApps) * 100}%` }} />
                </div>
                <p className="mt-1.5 text-[12px] tabular-nums text-muted-foreground">
                  {screen.done ?? 0} of {totalApps} screened · <span className="text-verified">{screen.cleared ?? 0} cleared</span> · <span className="text-contradicted">{screen.flagged ?? 0} flagged</span>
                  {screen.not_qualified ? ` · ${screen.not_qualified} not qualified` : ""}
                  {screen.duplicate ? ` · ${screen.duplicate} duplicates` : ""}
                  {screen.held ? ` · ${screen.held} held` : ""}
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
            <EmptyState icon={Play} title="No run yet">Set up the roles above and click Run staffing. A run of 1,000 shifts takes a few seconds.</EmptyState>
          </div>
        )}

        {report && !running && <Roster key={`r${runId}`} report={report} />}
        {(flagged.length > 0 || (report && !running && !fromLast)) && <ScreenedOut key={`s${runId}`} live={flagged} done={!!report && !running} report={report} />}
      </main>
    </div>
  );
}

function recordedLike(r: Role, tpl: StaffingTemplates) {
  // a template role that draws on the same lines of work as the recorded pool (BPO agents from support, store staff from retail)
  const words = ["support", "customer", "retail", "store", "cashier", "security", "delivery", "warehouse", "inventory", "hospitality", "steward", "barista", "stock", "chat"];
  return tpl.recorded_roles.length > 0 && r.keywords.some((k) => words.some((w) => k.includes(w)));
}

const clamp = (v: string, lo: number, hi: number) => Math.max(lo, Math.min(hi, Number(v) || 0));

function SourceOption({ active, onClick, disabled, icon: I, title, detail }: { active: boolean; onClick: () => void; disabled?: boolean; icon: React.ElementType; title: string; detail: string }) {
  return (
    <button
      type="button" onClick={onClick} disabled={disabled}
      className={cn("flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition disabled:opacity-50", active ? "border-primary/50 bg-primary/[0.06]" : "border-border-strong hover:bg-hover")}
      aria-pressed={active}
    >
      <I className={cn("mt-0.5 size-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} />
      <span className="min-w-0">
        <span className="block text-[13px] font-[510]">{title}</span>
        <span className="block text-[12px] leading-snug text-muted-foreground">{detail}</span>
      </span>
    </button>
  );
}

// ---- growing the pool from Crustdata ----------------------------------------------------------------------------

function GrowPool({ roles, template, tpl, disabled, onDone }: {
  roles: Role[]; template: string; tpl: StaffingTemplates | null; disabled: boolean; onDone: () => void;
}) {
  const [per, setPer] = useState(300);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const title = (id: string) => roles.find((r) => r.id === id)?.title ?? id;
  const go = async () => {
    setBusy(true);
    setErr(null);
    setLog([]);
    try {
      for await (const ev of ssePost<GrowEvent>("/staffing/pool/grow", { template, roles, per_role: per }, new AbortController().signal)) {
        if (ev.type === "role") setLog((l) => [...l, `${title(ev.role)}: ${ev.found.toLocaleString()} people`]);
        else if (ev.type === "done") setLog((l) => [...l, `${ev.new.toLocaleString()} new people added. The pool now has ${ev.total.toLocaleString()}.`]);
        else if (ev.type === "error") setErr(ev.message);
      }
      onDone();
    } catch (e) {
      setErr(e instanceof TalentError && e.status === 401 ? `The backend needs an admin token for this. Set it with the key icon in the ${BRAND.name} console.` : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mt-3 rounded-lg border border-border bg-elevated/60 p-3">
      <div className="grid items-end gap-3 sm:grid-cols-[170px_auto_1fr]">
        <Field label="People per role">
          <input type="number" min={10} max={2000} step={50} value={per} onChange={(e) => setPer(clamp(e.target.value, 10, 2000))} className={inputCls} disabled={busy || disabled} />
        </Field>
        <div className="pb-[1px]">
          <Button onClick={go} disabled={busy || disabled || roles.length === 0} title="Run one Crustdata Person Search per role and add the people to the recorded pool">
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />} Search Crustdata for more applicants
          </Button>
        </div>
        <p className="text-[11.5px] leading-snug text-faint">
          One live Person Search per role ({roles.length} roles), in each role&apos;s cities, using its job titles. Uses Crustdata credits; pages already
          searched come from the cache for free. New people are saved, so later runs cost nothing.
        </p>
      </div>
      {log.length > 0 && <ul className="mt-2 space-y-0.5 text-[12px] text-secondary">{log.map((l, i) => <li key={i}>{l}</li>)}</ul>}
      {err && <p className="mt-2 text-[12px] text-contradicted">{err}</p>}
      {!tpl?.pool_total && !busy && !log.length && <p className="mt-2 text-[12px] text-muted-foreground">No pool recorded yet for these roles.</p>}
    </div>
  );
}

// ---- roles -----------------------------------------------------------------------------------------------------------

function RolesCard({ cfg, set, tpl, total, running, onTemplate, thinRoles }: {
  cfg: Settings; set: (p: Partial<Settings>) => void; tpl: StaffingTemplates | null; total: number; running: boolean;
  onTemplate: (id: string) => void; thinRoles: Role[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  const update = (i: number, p: Partial<Role>) => set({ roles: cfg.roles.map((r, j) => (j === i ? { ...r, ...p } : r)) });
  const remove = (i: number) => set({ roles: cfg.roles.filter((_, j) => j !== i) });
  const add = () => {
    const base: Role = {
      id: "", title: "New role", cities: ["Bangalore"], slots: [{ start: "09:00", end: "17:00" }], days: [0, 1, 2, 3, 4, 5, 6], headcount: 1,
      min_years: 0, max_years: null, related_experience: true, keywords: [], skills: [], certifications: [], languages: [],
    };
    let id = "new-role";
    for (let n = 2; cfg.roles.some((r) => r.id === id); n++) id = `new-role-${n}`;
    set({ roles: [...cfg.roles, { ...base, id }] });
    setOpen(id);
  };
  const dup = (i: number) => {
    const r = cfg.roles[i];
    let id = `${r.id}-copy`;
    for (let n = 2; cfg.roles.some((x) => x.id === id); n++) id = `${r.id}-copy-${n}`;
    set({ roles: [...cfg.roles.slice(0, i + 1), { ...structuredClone(r), id, title: `${r.title} (copy)` }, ...cfg.roles.slice(i + 1)] });
    setOpen(id);
  };
  const blurb = tpl?.templates.find((t) => t.id === cfg.template)?.blurb;

  return (
    <section className={cn(cardCls, "overflow-hidden")}>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border px-4 py-3">
        <SectionHead title="Roles you're hiring for">
          Each role has its own cities, shift times, workers per shift and requirements. Start from a template and edit it.
        </SectionHead>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Template">
            <select value={cfg.template} onChange={(e) => onTemplate(e.target.value)} className={cn(inputCls, "w-[230px]")} disabled={running || !tpl}>
              {(tpl?.templates ?? []).map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="First day">
            <input type="date" value={cfg.start} onChange={(e) => set({ start: e.target.value || tomorrow() })} className={cn(inputCls, "w-[150px]")} disabled={running} />
          </Field>
          <Field label="Days">
            <input type="number" min={1} max={28} value={cfg.days} onChange={(e) => set({ days: clamp(e.target.value, 1, 28) })} className={cn(inputCls, "w-[70px]")} disabled={running} />
          </Field>
        </div>
      </div>
      {blurb && <p className="border-b border-border bg-elevated/50 px-4 py-2 text-[12px] text-muted-foreground">{blurb}</p>}
      {thinRoles.length > 0 && (
        <p className="flex items-start gap-2 border-b border-border bg-flag/[0.06] px-4 py-2 text-[12px] text-secondary">
          <CircleAlert className="mt-0.5 size-3.5 shrink-0 text-flag" />
          <span>
            The recorded pool has few or no {thinRoles.map((r) => r.title.toLowerCase()).join(", ")} applicants, so those shifts will mostly stay open. Search
            Crustdata for more under Applications, or upload your own.
          </span>
        </p>
      )}
      {!tpl && <p className="px-4 py-6 text-center text-[12.5px] text-muted-foreground"><Loader2 className="mr-1.5 inline size-3.5 animate-spin" />Loading roles…</p>}
      <ul className="divide-y divide-border">
        {cfg.roles.map((r, i) => {
          const isOpen = open === r.id;
          const n = seats(r, cfg.start, cfg.days);
          const needs = [
            r.related_experience ? (r.min_years ? `${r.min_years}+ yrs of this work` : "has done this work") : r.min_years ? `${r.min_years}+ yrs of work` : "no experience needed",
            ...(r.max_years != null ? [`at most ${r.max_years} yrs`] : []), ...r.skills, ...r.certifications, ...r.languages.map((l) => `speaks ${l}`),
          ];
          return (
            <li key={r.id}>
              <div className="flex flex-wrap items-start gap-x-4 gap-y-1.5 px-4 py-3">
                <button type="button" onClick={() => setOpen(isOpen ? null : r.id)} className="min-w-0 flex-1 text-left" aria-expanded={isOpen}>
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-[13.5px] font-[590]">{r.title}</span>
                    <span className="text-[12px] tabular-nums text-muted-foreground">{n.toLocaleString()} shifts</span>
                    {tpl?.pool_by_role && <span className="text-[12px] tabular-nums text-faint">· {(tpl.pool_by_role[r.id] ?? 0).toLocaleString()} searched for this role</span>}
                  </span>
                  <span className="mt-0.5 block text-[12px] text-muted-foreground">
                    {r.cities.join(", ")} · {slotsText(r)} · {r.headcount} per shift{Object.keys(r.city_headcount ?? {}).length ? " (more in some cities)" : ""}
                    {r.days.length < 7 ? ` · ${r.days.map((d) => DAYS[d]).join(" ")}` : ""}
                  </span>
                  <span className="mt-1.5 flex flex-wrap gap-1">
                    {needs.map((x) => <span key={x} className="rounded border border-border bg-elevated px-1.5 py-px text-[11px] text-secondary">{x}</span>)}
                  </span>
                </button>
                <span className="flex shrink-0 items-center gap-1">
                  <Button variant="ghost" onClick={() => setOpen(isOpen ? null : r.id)} disabled={running}>{isOpen ? "Done" : "Edit"}</Button>
                  <Button variant="ghost" onClick={() => dup(i)} disabled={running} title="Duplicate this role"><Copy className="size-3.5" /></Button>
                  <Button variant="ghost" onClick={() => remove(i)} disabled={running} title="Remove this role"><Trash2 className="size-3.5" /></Button>
                </span>
              </div>
              {isOpen && <RoleEditor role={r} onChange={(p) => update(i, p)} cities={tpl?.cities ?? []} />}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2.5">
        <Button onClick={add} disabled={running}><Plus className="size-3.5" /> Add role</Button>
        <span className="text-[12px] tabular-nums text-muted-foreground">{total.toLocaleString()} shifts to fill over {cfg.days} days</span>
      </div>
    </section>
  );
}

/** Text inputs that keep what's typed and only parse on blur, so "07:00-1" doesn't vanish mid-edit. */
function TextList({ value, onCommit, placeholder, className }: { value: string; onCommit: (s: string) => void; placeholder?: string; className?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <input value={v} placeholder={placeholder} onChange={(e) => setV(e.target.value)} onBlur={() => onCommit(v)} className={cn(inputCls, className)} />;
}

function RoleEditor({ role: r, onChange, cities }: { role: Role; onChange: (p: Partial<Role>) => void; cities: string[] }) {
  return (
    <div className="grid gap-3 border-t border-border bg-elevated/50 px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
      <Field label="Role title">
        <TextList value={r.title} onCommit={(t) => onChange({ title: t.trim() || r.title })} />
      </Field>
      <Field label="Cities" hint="Comma separated">
        <TextList value={r.cities.join(", ")} onCommit={(t) => onChange({ cities: list(t).length ? list(t) : r.cities })} placeholder={cities.slice(0, 3).join(", ")} />
      </Field>
      <Field label="Shift times" hint="e.g. 07:00-15:00, 22:00-06:00 (overnight is fine)">
        <TextList value={slotsText(r)} onCommit={(t) => onChange({ slots: parseSlots(t).length ? parseSlots(t) : r.slots })} />
      </Field>
      <Field label="Workers per shift" hint="Per city, per day">
        <input type="number" min={0} max={500} value={r.headcount} onChange={(e) => onChange({ headcount: clamp(e.target.value, 0, 500), city_headcount: {} })} className={inputCls} />
      </Field>
      <div className="sm:col-span-2">
        <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">Days it runs</span>
        <div className="flex flex-wrap gap-1">
          {DAYS.map((d, i) => {
            const on = r.days.includes(i);
            return (
              <button key={d} type="button" aria-pressed={on}
                onClick={() => onChange({ days: on ? (r.days.length > 1 ? r.days.filter((x) => x !== i) : r.days) : [...r.days, i].sort() })}
                className={cn("h-8 w-11 rounded-md border text-[12px] font-[510] transition", on ? "border-primary/50 bg-primary/[0.08] text-foreground" : "border-border-strong text-muted-foreground hover:bg-hover")}
              >{d}</button>
            );
          })}
        </div>
      </div>
      <Field label="Minimum experience (years)">
        <input type="number" min={0} max={40} step={0.5} value={r.min_years} onChange={(e) => onChange({ min_years: clamp(e.target.value, 0, 40) })} className={inputCls} />
      </Field>
      <Field label="Maximum experience (years)" hint="Leave empty for no limit (freshers: 1)">
        <input type="number" min={0} max={40} step={0.5} value={r.max_years ?? ""} onChange={(e) => onChange({ max_years: e.target.value === "" ? null : clamp(e.target.value, 0, 40) })} className={inputCls} />
      </Field>
      <label className="flex items-start gap-2 sm:col-span-2">
        <input type="checkbox" className="mt-0.5 size-3.5 accent-[var(--primary)]" checked={r.related_experience} onChange={(e) => onChange({ related_experience: e.target.checked })} />
        <span>
          <span className="block text-[12.5px] font-[510]">Must have done this work before</span>
          <span className="block text-[11.5px] text-muted-foreground">Checked against job titles on the Crustdata record. Turn off for fresher or open-to-all roles.</span>
        </span>
      </label>
      <Field label="Job titles that count as this work" hint="Comma separated, matched against the record">
        <TextList value={r.keywords.join(", ")} onCommit={(t) => onChange({ keywords: list(t) })} placeholder="nurse, nursing, icu" />
      </Field>
      <Field label="Required skills" hint="Checked on the record, else self-reported and tested">
        <TextList value={r.skills.join(", ")} onCommit={(t) => onChange({ skills: list(t) })} placeholder="Typing 30 wpm, POS billing" />
      </Field>
      <Field label="Required certifications" hint="Document seen at onboarding">
        <TextList value={r.certifications.join(", ")} onCommit={(t) => onChange({ certifications: list(t) })} placeholder="Two-wheeler licence, BLS" />
      </Field>
      <Field label="Languages" hint="Confirmed at the interview">
        <TextList value={r.languages.join(", ")} onCommit={(t) => onChange({ languages: list(t) })} placeholder="English, Hindi" />
      </Field>
    </div>
  );
}

// ---- test mode -------------------------------------------------------------------------------------------------------

function TestMode({ cfg, set, running }: { cfg: Settings; set: (p: Partial<Settings>) => void; running: boolean }) {
  const allowed = cfg.source === "recorded";
  const on = cfg.test && allowed;
  return (
    <section className={cn("rounded-xl border border-dashed p-4", on ? "border-flag/50 bg-flag/[0.05]" : "border-border-strong")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <FlaskConical className={cn("mt-0.5 size-4 shrink-0", on ? "text-flag" : "text-muted-foreground")} />
          <div className="min-w-0">
            <h3 className="text-[14px] font-[590]">Test mode / audit</h3>
            <p className="mt-0.5 max-w-[640px] text-[12px] leading-relaxed text-muted-foreground">
              For proving the screen works, not for real hiring. Sourced plants lies and repeat applications in the recorded pool, keeps an answer key
              aside, and scores itself against it. It also simulates no-shows to test the bench.
              {!allowed && " Only available with the recorded pool."}
            </p>
          </div>
        </div>
        <label className={cn("inline-flex cursor-pointer items-center gap-2 text-[12.5px] font-[510]", (!allowed || running) && "cursor-not-allowed opacity-50")}>
          <span>{on ? "On" : "Off"}</span>
          <button
            type="button" role="switch" aria-checked={on} aria-label="Test mode" disabled={!allowed || running} onClick={() => set({ test: !cfg.test })}
            className={cn("relative h-5 w-9 rounded-full border transition", on ? "border-flag bg-flag" : "border-border-strong bg-elevated")}
          >
            <span className={cn("absolute top-0.5 size-3.5 rounded-full bg-panel shadow transition-all", on ? "left-[18px]" : "left-0.5")} />
          </button>
        </label>
      </div>
      {on && (
        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <Field label="Planted lies (%)" hint="Applications with one lie">
            <input type="number" min={0} max={90} value={cfg.fakeRate} onChange={(e) => set({ fakeRate: clamp(e.target.value, 0, 90) })} className={inputCls} disabled={running} />
          </Field>
          <Field label="Repeat applications (%)" hint="Honest people applying twice">
            <input type="number" min={0} max={30} value={cfg.dupRate} onChange={(e) => set({ dupRate: clamp(e.target.value, 0, 30) })} className={inputCls} disabled={running} />
          </Field>
          <Field label="No-shows to simulate (%)" hint="Of booked shifts">
            <input type="number" min={0} max={50} value={cfg.noShowRate} onChange={(e) => set({ noShowRate: clamp(e.target.value, 0, 50) })} className={inputCls} disabled={running} />
          </Field>
          <Field label="Seed" hint="Same seed, same run">
            <input type="number" value={cfg.seed} onChange={(e) => set({ seed: Number(e.target.value) || 0 })} className={inputCls} disabled={running} />
          </Field>
        </div>
      )}
    </section>
  );
}

// ---- report ----------------------------------------------------------------------------------------------------------

function Report({ report: r, fromLast }: { report: StaffingReport; fromLast: boolean }) {
  const fc = r.fake_catch;
  const staffedFakes = fc?.fakes_staffed?.length ?? 0;
  const screened = r.screening.cleared + r.screening.flagged + (r.screening.not_qualified ?? 0) + (r.screening.duplicate ?? 0) + (r.screening.held ?? 0);
  const bench = r.bench;
  const drill = r.no_show_drill;
  return (
    <div className="space-y-6">
      {fromLast && <p className="text-[12px] text-faint">Showing the last run on this backend. Run again to see the roster and each screened-out application.</p>}
      <div className="grid gap-px overflow-hidden rounded-xl border border-border-strong bg-border sm:grid-cols-2 lg:grid-cols-4">
        <Tile k="Shifts filled" v={`${r.filled.toLocaleString()} / ${r.shifts.toLocaleString()}`} sub={`${pct(r.fill_rate, 1)} fill rate`} />
        <Tile k="Applications screened" v={screened.toLocaleString()} sub={`${r.screening.cleared} cleared · ${r.screening.flagged} flagged${r.screening.duplicate ? ` · ${r.screening.duplicate} repeats` : ""}`} />
        <Tile
          k="People booked" v={String(r.workers_used ?? "–")}
          sub={r.double_bookings != null ? (r.double_bookings === 0 ? "nobody on two shifts at once" : `${r.double_bookings} double-bookings`) : r.workers_cleared ? `of ${r.workers_cleared} cleared` : undefined}
          tone={r.double_bookings ? "text-contradicted" : undefined}
        />
        {fc ? (
          <Tile k="Fakes given a shift" v={String(staffedFakes)} sub={staffedFakes ? "a planted lie got through" : "no planted lie got a shift"} tone={staffedFakes ? "text-contradicted" : "text-verified"} />
        ) : (
          <Tile k="Backup bench" v={bench ? `${bench.standby_found.toLocaleString()}` : "–"} sub={bench?.coverage != null ? `standby slots · ${pct(bench.coverage)} of target` : "standby slots"} />
        )}
      </div>

      {fc && (
        <section className={cn(cardCls, "border-flag/40 p-4")}>
          <SectionHead
            title="Test mode: did Sourced catch the planted lies?"
            aside={
              <span className="flex gap-3 text-[12px] text-muted-foreground">
                <span title="Of everything Sourced flagged, the share that really was a planted lie">Precision <b className="font-[590] tabular-nums text-foreground">{pct(fc.precision, 1)}</b></span>
                <span title="Of all planted lies, the share Sourced caught">Recall <b className="font-[590] tabular-nums text-foreground">{pct(fc.recall, 1)}</b></span>
              </span>
            }
          >
            {fc.fakes_planted} of {fc.applications} applications carried one lie. Sourced flagged {fc.flagged}: {fc.true_positives} real lies,{" "}
            {fc.false_positives} honest people flagged by mistake, {fc.false_negatives} lies missed.
            {fc.duplicates_planted ? ` ${fc.duplicates_caught} of ${fc.duplicates_planted} repeat applications were merged.` : ""}
            {drill ? ` In the no-show drill, ${drill.no_shows} booked workers didn't turn up: ${drill.from_bench} were covered from the bench, ${drill.from_pool} from the pool, ${drill.uncovered} stayed open.` : ""}
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

      {r.roles && (
        <section className={cn(cardCls, "overflow-x-auto")}>
          <div className="px-4 pt-4"><SectionHead title="By role">Applicants, who cleared the role&apos;s requirements, and shifts filled.</SectionHead></div>
          <table className="mt-3 w-full min-w-[560px] text-[12.5px]">
            <thead className="border-y border-border bg-elevated/60 text-left text-[11.5px] text-muted-foreground">
              <tr><th className="px-4 py-1.5 font-[510]">Role</th><th className="px-2 py-1.5 text-right font-[510]">Applied</th><th className="px-2 py-1.5 text-right font-[510]">Cleared</th><th className="px-2 py-1.5 text-right font-[510]">Shifts</th><th className="px-4 py-1.5 text-right font-[510]">Filled</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {Object.entries(r.roles).map(([id, v]) => (
                <tr key={id}>
                  <td className="px-4 py-2"><span className="font-[510]">{v.title}</span><span className="block text-[11px] text-faint">{v.cities.join(", ")}</span></td>
                  <td className="px-2 py-2 text-right tabular-nums">{v.applied}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{v.cleared}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{v.seats}</td>
                  <td className={cn("px-4 py-2 text-right tabular-nums", v.seats && v.filled < v.seats && "text-flag")}>{v.filled} · {pct(v.seats ? v.filled / v.seats : null)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <FillTable title="Shifts filled by city" rows={r.by_city} />
        <section className={cn(cardCls, "p-4")}>
          <SectionHead title="People and the bench" />
          <ul className="mt-3 space-y-1.5 text-[12.5px]">
            <Line k="Different people who applied" v={r.people} />
            <Line k="Repeat applications merged" v={r.duplicates?.repeat_applications} />
            <Line k="Held: one phone or email behind several people" v={r.duplicates?.shared_contact} />
            <Line k={`Double-bookings (with ${r.rest_hours ?? 10}h rest between shifts)`} v={r.double_bookings} />
            {bench && <Line k={`Standby slots for no-shows (target ${pct(bench.rate)} of each shift)`} v={`${bench.standby_found} of ${bench.standby_wanted}`} />}
            {bench && <Line k="Shift times with a backup ready" v={`${bench.shift_times_covered} of ${bench.shift_times}`} />}
            {r.onboarding_checks && r.onboarding_checks.workers > 0 && <Line k="Cleared workers with a document or language to confirm" v={r.onboarding_checks.workers} />}
            {r.lookups && <Line k="Live Crustdata lookups this run" v={r.lookups.live} />}
          </ul>
        </section>
      </div>

      {Object.keys(r.open_reasons).length > 0 && (
        <section className={cn(cardCls, "p-4")}>
          <SectionHead title="Why some shifts are still open">The shifts nobody cleared could take, grouped by reason.</SectionHead>
          <ul className="mt-3 space-y-1">
            {Object.entries(r.open_reasons).map(([k, n]) => (
              <li key={k} className="flex justify-between gap-3 text-[12.5px]"><span>{k.replace(/_/g, " ")}</span><span className="tabular-nums text-muted-foreground">{n}</span></li>
            ))}
          </ul>
        </section>
      )}
      {r.pool && (
        <p className="text-[11.5px] text-faint">
          {r.pool.source === "upload" ? `Applications: ${r.pool.file ?? "uploaded CSV"} (${r.pool.rows} rows), checked against ${r.pool.records} recorded Crustdata records` : `Applicant pool: ${r.pool.records} recorded Crustdata records`}
          {r.test_mode ? " · test mode" : ""}{r.horizon ? ` · shifts from ${r.horizon.start} for ${r.horizon.days} days` : ""}{r.today ? ` · run date ${r.today}` : ""}
        </p>
      )}
    </div>
  );
}

function Line({ k, v }: { k: string; v?: number | string | null }) {
  return (
    <li className="flex justify-between gap-3">
      <span className="text-secondary">{k}</span>
      <span className="shrink-0 tabular-nums text-muted-foreground">{v ?? "–"}</span>
    </li>
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
          <li key={k} className="grid grid-cols-[110px_minmax(0,1fr)_88px] items-center gap-3 text-[12.5px]">
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

// ---- roster ----------------------------------------------------------------------------------------------------------

function Roster({ report }: { report: StaffingReport }) {
  const [rows, setRows] = useState<RosterRow[]>([]);
  const [count, setCount] = useState(0);
  const [role, setRole] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const per = 50;
  const roles = report.roles ?? {};

  useEffect(() => {
    let live = true;
    talent
      .staffingRoster({ role, city, status, q, offset: page * per, limit: per })
      .then((r) => {
        if (!live) return;
        setRows(r.rows);
        setCount(r.total);
        setErr(null);
      })
      .catch((e) => live && setErr(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [role, city, status, q, page, tick]);

  const noShow = async (sid: string) => {
    setBusy(sid);
    setNote(null);
    try {
      const out = await talent.staffingNoShow(sid);
      setRows((rs) => rs.map((r) => (r.id === sid ? out.shift : r)));
      setTick((n) => n + 1); // the backup left the bench of the shifts beside it too
      setNote(out.backup ? `${sid}: ${out.shift.worker_name ?? out.backup} takes the shift (from the ${out.from === "bench" ? "backup bench" : "cleared pool"}).` : `${sid}: nobody on the bench or in the pool is free, so it's open again.`);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const time = (r: RosterRow) => r.slot ?? (r.start ? r.start.slice(11, 16) : "");
  const sel = "h-7 rounded-md border border-border-strong bg-panel px-1.5 text-[12px]";
  return (
    <section className={cn(cardCls, "overflow-hidden")}>
      <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border px-4 py-3">
        <SectionHead title={`Roster (${count.toLocaleString()} shifts)`}>Who works each shift, and who is on standby. Mark a no-show to backfill it from the bench.</SectionHead>
        <div className="flex flex-wrap items-center gap-1.5">
          <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Search name or shift" className={cn(sel, "w-[150px] px-2")} />
          <select value={role} onChange={(e) => { setRole(e.target.value); setPage(0); }} className={sel}>
            <option value="">All roles</option>
            {Object.entries(roles).map(([id, v]) => <option key={id} value={id}>{v.title}</option>)}
          </select>
          <select value={city} onChange={(e) => { setCity(e.target.value); setPage(0); }} className={sel}>
            <option value="">All cities</option>
            {Object.keys(report.by_city).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }} className={sel}>
            <option value="all">All shifts</option><option value="filled">Filled</option><option value="open">Open</option><option value="no_show">No-shows</option>
          </select>
          <a href={staffingUrl("/staffing/roster.csv")} className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] text-muted-foreground hover:bg-elevated hover:text-foreground"><Download className="size-3.5" /> CSV</a>
        </div>
      </div>
      {note && <p className="border-b border-border bg-verified/[0.06] px-4 py-2 text-[12px] text-secondary">{note}</p>}
      {err && <p className="px-4 py-3 text-[12px] text-contradicted">{err}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-[12.5px]">
          <thead className="border-b border-border bg-elevated/60 text-left text-[11.5px] text-muted-foreground">
            <tr>
              <th className="px-4 py-1.5 font-[510]">Shift</th><th className="px-2 py-1.5 font-[510]">Role</th><th className="px-2 py-1.5 font-[510]">When</th>
              <th className="px-2 py-1.5 font-[510]">Worker</th><th className="px-2 py-1.5 font-[510]">Standby</th><th className="px-4 py-1.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.id} className="align-top">
                <td className="px-4 py-2 font-mono text-[11.5px] text-muted-foreground">{r.id}</td>
                <td className="px-2 py-2">{r.role_label}<span className="block text-[11px] text-faint">{r.city}</span></td>
                <td className="px-2 py-2 tabular-nums">{r.weekday} {r.date.slice(5)}<span className="block text-[11px] text-faint">{time(r)}</span></td>
                <td className="px-2 py-2">
                  {r.worker ? <>{r.worker_name}<span className="block text-[11px] text-faint">{r.worker}</span></> : <span className="text-flag">{r.open_reason ?? "open"}</span>}
                  {r.no_show && <span className="block text-[11px] text-contradicted">no-show: {r.no_show}</span>}
                </td>
                <td className="px-2 py-2 text-[12px] text-muted-foreground">{r.bench?.length ? r.bench.map((b) => b.name ?? b.worker).join(", ") : "–"}</td>
                <td className="px-4 py-2 text-right">
                  {r.worker && (
                    <Button variant="ghost" onClick={() => noShow(r.id)} disabled={busy !== null} title="This worker didn't turn up: give the shift to a backup">
                      {busy === r.id ? <Loader2 className="size-3.5 animate-spin" /> : <UserX className="size-3.5" />} No-show
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {count > per && (
        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[12px] text-muted-foreground">
          <span className="tabular-nums">{page * per + 1}–{Math.min(count, (page + 1) * per)} of {count.toLocaleString()}</span>
          <span className="flex gap-1">
            <Button variant="ghost" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>Previous</Button>
            <Button variant="ghost" onClick={() => setPage((p) => p + 1)} disabled={(page + 1) * per >= count}>Next</Button>
          </span>
        </div>
      )}
    </section>
  );
}

// ---- screened out ----------------------------------------------------------------------------------------------------

const TABS = [
  { key: "flagged", label: "Flagged", what: "No shift was given to these people. Open one to see which record disproves the application." },
  { key: "not_qualified", label: "Not qualified", what: "Honest, but they don't meet the role's requirements." },
  { key: "duplicate", label: "Repeats", what: "The same person applying again for the same role. Merged into their first application." },
  { key: "held", label: "Held", what: "Not checked yet: not in the recorded Crustdata data, or no profile URL. Turn on live lookups to check them." },
] as const;

function ScreenedOut({ live, done, report }: { live: Screening[]; done: boolean; report: StaffingReport | null }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("flagged");
  const [rows, setRows] = useState<Record<string, Screening[]>>({});
  const [kind, setKind] = useState("all");

  useEffect(() => {
    if (!done) return;
    for (const t of TABS) {
      talent.staffingScreenings(t.key).then((r) => setRows((m) => ({ ...m, [t.key]: r.rows }))).catch(() => {});
    }
  }, [done]);

  const counts: Record<string, number> = {
    flagged: report?.screening.flagged ?? live.length, not_qualified: report?.screening.not_qualified ?? 0,
    duplicate: report?.screening.duplicate ?? 0, held: report?.screening.held ?? 0,
  };
  const all = tab === "flagged" ? rows.flagged ?? live : rows[tab] ?? [];
  const kinds = [...new Set(all.map((r) => r.kind ?? "other"))];
  const shown = kind === "all" ? all : all.filter((r) => (r.kind ?? "other") === kind);
  const roleName = (id: string) => report?.roles?.[id]?.title ?? id;
  const what = TABS.find((t) => t.key === tab)?.what;

  return (
    <section className={cn(cardCls, "overflow-hidden")}>
      <div className="border-b border-border px-4 pt-3">
        <SectionHead title="Screened out">{what}</SectionHead>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-2">
          <div className="flex gap-1" role="tablist">
            {TABS.map((t) => (
              <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => { setTab(t.key); setKind("all"); }}
                className={cn("-mb-px border-b-2 px-2.5 py-1.5 text-[12.5px] font-[510] transition", tab === t.key ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}
              >{t.label} <span className="tabular-nums text-faint">{counts[t.key] ?? 0}</span></button>
            ))}
          </div>
          {kinds.length > 1 && (
            <select value={kind} onChange={(e) => setKind(e.target.value)} className="mb-1.5 h-7 rounded-md border border-border-strong bg-panel px-1.5 text-[12px]">
              <option value="all">All reasons</option>
              {kinds.map((k) => <option key={k} value={k}>{label(FLAG_LABEL, k)} ({all.filter((r) => (r.kind ?? "other") === k).length})</option>)}
            </select>
          )}
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="px-4 py-6 text-center text-[12.5px] text-muted-foreground">{done ? "Nobody here." : "Loading…"}</p>
      ) : (
        <ul className="max-h-[640px] divide-y divide-border overflow-y-auto">
          {shown.slice(0, 500).map((s) => (
            <li key={s.app_id}>
              <details className="group">
                <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-2.5 hover:bg-hover">
                  {s.outcome !== "flagged" ? <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" /> : s.kind === "identity_unverifiable" || s.kind === "shared_contact" ? <ShieldAlert className="mt-0.5 size-4 shrink-0 text-flag" /> : s.kind === "identity_mismatch" ? <UserX className="mt-0.5 size-4 shrink-0 text-contradicted" /> : <ShieldCheck className="mt-0.5 size-4 shrink-0 text-contradicted" />}
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-[13px] font-[510]">{s.name}</span>
                      <span className="text-[11.5px] text-muted-foreground">{roleName(s.role)} · {s.city || "no city"} · {s.app_id}</span>
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
          {shown.length > 500 && <li className="px-4 py-2 text-[12px] text-faint">Showing the first 500.</li>}
        </ul>
      )}
    </section>
  );
}
