"use client";
// Rules: company rules set without code (backend/app/rules). Pick a template, fill in the blanks, and Agaxes enforces
// it whenever an agent acts: in Send Guard, the approval inbox and the runtime. Every change is versioned and on the
// ledger, and every time a rule stops or holds something it says which rule did it.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, History, Loader2, Plus, Scale, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { ApiError, rulesApi, type Agent, type Rule, type RuleTemplate, type RuleType, type RulesView as View } from "./api";
import { Button, EmptyState, Field, PageHead, SectionHead, ago, cardCls, inputCls } from "./parts";

type Params = Record<string, string | number>;

const toForm = (t: RuleTemplate, p: Record<string, unknown>): Params => {
  const out: Params = {};
  for (const f of t.fields) {
    const v = p[f.name] ?? t.example[f.name] ?? "";
    out[f.name] = Array.isArray(v) ? v.join("\n") : (v as string | number);
  }
  return out;
};

const OUTCOME_TONE = (o: string) => /block|stopped|refused/i.test(o) ? "text-contradicted" : /held|wait|needs/i.test(o) ? "text-flag" : "text-muted-foreground";

export function RulesView({ agents }: { agents: Agent[] }) {
  const [data, setData] = useState<View | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [editing, setEditing] = useState<{ rule?: Rule; type: RuleType } | null>(null);

  const load = useCallback(() => {
    rulesApi.list().then((d) => { setData(d); setError(null); }).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 5000); // enforcement shows up as agents work
    return () => clearInterval(t);
  }, [load]);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    setNote(null);
    try {
      await fn();
      setNote({ tone: "ok", text: ok });
      load();
      return true;
    } catch (e) {
      setNote({ tone: "bad", text: e instanceof Error ? e.message : String(e) });
      return false;
    } finally {
      setBusy(null);
    }
  };

  const live = agents.filter((a) => a.status !== "offboarded");
  const tmpl = (t: RuleType) => data?.templates.find((x) => x.type === t);
  const can = !!data?.can_edit;
  const used = new Set((data?.rules ?? []).map((r) => r.type));

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-6 sm:px-8 sm:py-8">
      <PageHead title="Rules">
        Your company&apos;s rules for its AI employees, written without code. {BRAND.name} enforces them the moment an agent
        acts, and every block or hold names the rule that caused it. Each change is versioned and written to the ledger.
      </PageHead>

      {error && <p className="mt-5 text-[12.5px] text-contradicted">{error}</p>}
      {data && !can && (
        <p className="mt-5 rounded-lg border border-border-strong bg-elevated px-3 py-2.5 text-[12.5px] text-secondary">
          You can see the rules that govern your agents. Only an admin or owner can add or change them.
        </p>
      )}
      {note && <p className={cn("mt-4 text-[12.5px]", note.tone === "ok" ? "text-verified" : "text-contradicted")}>{note.text}</p>}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-w-0">
          <SectionHead title={data ? `Rules in force (${data.rules.filter((r) => r.enabled).length})` : "Rules in force"}
            aside={can && !editing ? <Button variant="primary" onClick={() => setEditing({ type: "offer_approvers" })}><Plus className="size-3.5" /> New rule</Button> : undefined} />

          {editing && data && (
            <RuleForm key={editing.rule?.rule_id ?? editing.type} templates={data.templates} agents={live} rule={editing.rule} type={editing.type}
              busy={busy === "save"} onCancel={() => setEditing(null)}
              onSave={async (type, params, agentIds, name) => {
                const ok = editing.rule
                  ? await run("save", () => rulesApi.update(editing.rule!.rule_id, { params, agents: agentIds, name }), "Rule updated. The new version applies from now on, and the change is on the ledger.")
                  : await run("save", () => rulesApi.create({ type, params, agents: agentIds, name }), "Rule added. It applies from now on, and the change is on the ledger.");
                if (ok) setEditing(null);
              }} />
          )}

          <div className="mt-3 space-y-3">
            {!data ? (
              <p className="flex items-center gap-2 px-1 py-4 text-[13px] text-faint"><Loader2 className="size-4 animate-spin" /> Loading</p>
            ) : !data.rules.length ? (
              <div className={cardCls}>
                <EmptyState icon={Scale} title="No rules yet">
                  {can ? "Start from one of the suggestions on the right, or write your own with New rule." : "Your admins haven't set any rules yet."}
                </EmptyState>
              </div>
            ) : data.rules.map((r) => (
              <RuleCard key={r.rule_id} r={r} can={can && r.editable} busy={busy}
                onToggle={() => run(`t:${r.rule_id}`, () => rulesApi.update(r.rule_id, { enabled: !r.enabled }), r.enabled ? "Rule turned off. It no longer applies; the change is on the ledger." : "Rule turned on.")}
                onEdit={() => setEditing({ rule: r, type: r.type })}
                onDelete={() => run(`d:${r.rule_id}`, () => rulesApi.remove(r.rule_id), "Rule deleted. Its history stays on the ledger.")} />
            ))}
          </div>

          <div className="mt-8">
            <SectionHead title="Recently enforced">
              Every time a rule stopped, held or slowed something. Each one is a ledger entry.
            </SectionHead>
          </div>
          <ul className={cn(cardCls, "mt-3 divide-y divide-border")}>
            {!data?.recent.length ? (
              <li className="px-4 py-4 text-[12.5px] text-muted-foreground">Nothing yet. When a rule blocks or holds an agent, it shows up here.</li>
            ) : data.recent.map((e) => (
              <li key={e.hash} className="px-4 py-2.5 text-[12.5px]">
                <p className="flex flex-wrap items-baseline gap-x-1.5">
                  <span className="font-[590]">{e.agent_name ?? "An agent"}</span>
                  <span className={OUTCOME_TONE(e.outcome)}>{e.outcome}</span>
                  {e.to?.name && <span className="text-muted-foreground">· {e.to.name}{e.to.company ? ` (${e.to.company})` : ""}</span>}
                  <span className="ml-auto text-[11px] text-faint">{ago(e.ts)}</span>
                </p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  Rule “{e.name}” <span className="text-faint">v{e.version}</span>: {e.detail}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <aside className="min-w-0">
          <SectionHead title={can ? "Suggested rules" : "Kinds of rule"} />
          <ol className={cn(cardCls, "mt-3 divide-y divide-border")}>
            {(data?.templates ?? []).map((t) => (
              <li key={t.type} className="px-4 py-3">
                <p className="text-[13px] font-[590]">{t.example_sentence}</p>
                <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{t.description}</p>
                {can && (
                  <div className="mt-2 flex gap-2">
                    <Button variant="secondary" disabled={!!busy} onClick={() => run(`s:${t.type}`, () => rulesApi.create({ type: t.type, params: t.example }), `Added: ${t.example_sentence}.`)}>
                      {busy === `s:${t.type}` ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />} {used.has(t.type) ? "Add another" : "Add this"}
                    </Button>
                    <Button variant="ghost" disabled={!!busy} onClick={() => setEditing({ type: t.type })}>Customize</Button>
                  </div>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-3 px-1 text-[11.5px] leading-relaxed text-faint">
            {tmpl("offer_approvers") ? "Offer amounts are read from the compensation line (₹42 LPA, 35 lakh, ₹1.2 Cr). If the amount can't be read, the rule applies anyway. " : ""}
            Rules are checked when the agent acts and again when a person approves, so a rule added later still counts.
          </p>
        </aside>
      </div>
    </main>
  );
}

function RuleCard({ r, can, busy, onToggle, onEdit, onDelete }: {
  r: Rule; can: boolean; busy: string | null; onToggle: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<Rule | null>(null);
  useEffect(() => {
    if (open) rulesApi.get(r.rule_id).then(setFull).catch(() => setFull(null));
  }, [open, r.rule_id, r.version]);
  return (
    <div className={cn(cardCls, "p-4", !r.enabled && "opacity-60")}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-[590] leading-snug">{r.name || r.sentence}</p>
          {r.name && <p className="mt-0.5 text-[12px] text-muted-foreground">{r.sentence}</p>}
          <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
            <span className="rounded border border-border px-1.5 py-px">{r.type_label}</span>
            <span className="rounded border border-border px-1.5 py-px">{r.agent_names.length ? r.agent_names.join(", ") : "Whole company"}</span>
            {r.workspace_id === null && <span className="rounded border border-border px-1.5 py-px">Every company</span>}
            <span>v{r.version} · changed {ago(r.updated_at)} by {r.updated_by}</span>
            {!!r.enforced_count && <span className="text-flag">· enforced {r.enforced_count}×</span>}
          </p>
        </div>
        {can && (
          <label className="flex shrink-0 cursor-pointer items-center gap-2 text-[12px] text-muted-foreground">
            {busy === `t:${r.rule_id}` && <Loader2 className="size-3.5 animate-spin" />}
            <input type="checkbox" checked={r.enabled} disabled={!!busy} onChange={onToggle} className="size-4 accent-[var(--primary)]" />
            {r.enabled ? "On" : "Off"}
          </label>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {can && <Button variant="secondary" onClick={onEdit} disabled={!!busy}>Edit</Button>}
        <Button variant="ghost" onClick={() => setOpen(!open)}><History className="size-3.5" /> History <ChevronRight className={cn("size-3.5 transition", open && "rotate-90")} /></Button>
        {can && <Button variant="ghost" className="ml-auto text-contradicted" onClick={onDelete} disabled={!!busy}><Trash2 className="size-3.5" /> Delete</Button>}
      </div>
      {open && (
        <ol className="mt-3 space-y-1.5 border-l border-border pl-3 text-[12px]">
          {!full ? <li className="text-faint">Loading</li> : [...(full.history ?? [])].reverse().map((h) => (
            <li key={h.version}>
              <span className="font-[590]">v{h.version}</span> <span className="text-muted-foreground">{h.change} by {h.by}, {ago(h.at)}</span>
              <span className="block text-secondary">{h.sentence}{!h.enabled && h.change !== "deleted" ? " (off)" : ""}</span>
              {h.note && <span className="block text-faint">“{h.note}”</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function RuleForm({ templates, agents, rule, type, busy, onCancel, onSave }: {
  templates: RuleTemplate[]; agents: Agent[]; rule?: Rule; type: RuleType; busy: boolean; onCancel: () => void;
  onSave: (type: RuleType, params: Params, agents: string[], name?: string) => void;
}) {
  const [t, setT] = useState<RuleType>(rule?.type ?? type);
  const tpl = useMemo(() => templates.find((x) => x.type === t)!, [templates, t]);
  const [params, setParams] = useState<Params>(() => toForm(tpl, rule?.params ?? {}));
  const [picked, setPicked] = useState<string[]>(rule?.agents ?? []);
  const [name, setName] = useState(rule?.name ?? "");
  const [preview, setPreview] = useState<{ ok: boolean; sentence?: string; error?: string } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    const n = ++seq.current;
    const h = setTimeout(() => {
      rulesApi.preview({ type: t, params, agents: picked }).then((p) => n === seq.current && setPreview(p)).catch(() => {});
    }, 250);
    return () => clearTimeout(h);
  }, [t, params, picked]);

  const pickType = (nt: RuleType) => {
    setT(nt);
    setParams(toForm(templates.find((x) => x.type === nt)!, {}));
  };

  return (
    <div className={cn(cardCls, "mt-3 p-4")}>
      {!rule && (
        <div className="flex flex-wrap gap-1.5">
          {templates.map((x) => (
            <button key={x.type} onClick={() => pickType(x.type)}
              className={cn("rounded-md border px-2.5 py-1 text-[12px] font-[510]", x.type === t ? "border-primary bg-primary/10 text-foreground" : "border-border-strong text-muted-foreground hover:bg-hover")}>
              {x.label}
            </button>
          ))}
        </div>
      )}
      <p className="mt-2 text-[12px] text-muted-foreground">{tpl.description}</p>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {tpl.fields.map((f) => (
          <div key={f.name} className={f.type === "list" ? "sm:col-span-2" : undefined}>
            <Field label={f.label}>
              {f.type === "select" ? (
                <select value={String(params[f.name] ?? "")} onChange={(e) => setParams({ ...params, [f.name]: e.target.value })} className={inputCls}>
                  {(f.options ?? []).map((o) => <option key={o} value={o}>{f.option_labels?.[o] ?? o}</option>)}
                </select>
              ) : f.type === "list" ? (
                <textarea value={String(params[f.name] ?? "")} placeholder={f.placeholder} onChange={(e) => setParams({ ...params, [f.name]: e.target.value })}
                  className={cn(inputCls, "h-24 py-2")} />
              ) : (
                <input value={String(params[f.name] ?? "")} placeholder={f.placeholder} type={f.type === "number" ? "number" : "text"} min={f.min} max={f.max}
                  onChange={(e) => setParams({ ...params, [f.name]: f.type === "number" ? Number(e.target.value) : e.target.value })} className={inputCls} />
              )}
            </Field>
          </div>
        ))}
      </div>

      <div className="mt-3">
        <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">Applies to</span>
        <div className="flex flex-wrap gap-1.5">
          <button onClick={() => setPicked([])} className={cn("rounded-full border px-2.5 py-0.5 text-[12px]", !picked.length ? "border-primary bg-primary/10" : "border-border-strong text-muted-foreground")}>Whole company</button>
          {agents.map((a) => {
            const on = picked.includes(a.agent_id);
            return (
              <button key={a.agent_id} onClick={() => setPicked(on ? picked.filter((x) => x !== a.agent_id) : [...picked, a.agent_id])}
                className={cn("rounded-full border px-2.5 py-0.5 text-[12px]", on ? "border-primary bg-primary/10" : "border-border-strong text-muted-foreground")}>
                {a.name}
              </button>
            );
          })}
        </div>
      </div>

      <div className="mt-3">
        <Field label="Name (optional)" hint="Shown instead of the sentence, e.g. “Client no-poach list”.">
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder={preview?.sentence ?? ""} />
        </Field>
      </div>

      <div className={cn("mt-4 rounded-md border px-3 py-2 text-[13px]", preview?.ok === false ? "border-contradicted/40 text-contradicted" : "border-border bg-elevated")}>
        {preview?.ok === false ? preview.error : <><span className="text-[11px] uppercase tracking-wide text-faint">The rule</span><br /><span className="font-[590]">{preview?.sentence ?? "…"}</span></>}
      </div>

      <div className="mt-3 flex gap-2">
        <Button variant="primary" disabled={busy || preview?.ok === false} onClick={() => onSave(t, params, picked, name.trim() || undefined)}>
          {busy && <Loader2 className="size-3.5 animate-spin" />} {rule ? `Save as v${rule.version + 1}` : "Add rule"}
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
