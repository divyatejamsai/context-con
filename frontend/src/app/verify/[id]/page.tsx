"use client";

import { use, useEffect, useState } from "react";

type Check = { name: string; label: string; status: "pass" | "fail" | "unverifiable"; detail: string };
type Seal = { seal_id: string; agent_name: string; kind: string; scope: string; to: string | null; company: string;
  sponsor: string; created_at: string; sha256: string; body: string; ledger_entry: string };
type Result = { verdict: "genuine" | "invalid" | "unconfirmed"; headline: string; checks: Check[]; seal: Seal | null };

const TONE = {
  genuine: { box: "border-verified/50 bg-verified/10", text: "text-verified", word: "Genuine" },
  invalid: { box: "border-contradicted/50 bg-contradicted/10", text: "text-contradicted", word: "Not valid" },
  unconfirmed: { box: "border-flag/50 bg-flag/10", text: "text-flag", word: "Can't confirm right now" },
};

export default function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [res, setRes] = useState<Result>();
  const [pasted, setPasted] = useState("");
  const [checked, setChecked] = useState<Result>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/public-verify?id=${encodeURIComponent(id)}`).then((r) => r.json()).then(setRes)
      .catch(() => setRes({ verdict: "unconfirmed", headline: "Agaxes can't be reached right now.", checks: [], seal: null }));
  }, [id]);

  const check = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/public-verify", { method: "POST", body: JSON.stringify({ seal_id: id, text: pasted }) });
      setChecked(await r.json());
    } finally { setBusy(false); }
  };

  const shown = checked ?? res;
  return (
    <main className="mx-auto max-w-[760px] px-4 py-10 sm:py-14">
      <p className="text-[12px] font-[590] uppercase tracking-wide text-faint">Agaxes · verify an AI agent</p>
      <h1 className="mt-2 text-[24px] font-[640] leading-tight">Is this message really from a governed AI agent?</h1>
      {!shown ? (
        <p className="mt-8 text-[14px] text-faint">Checking…</p>
      ) : (
        <>
          <section className={`mt-6 rounded-xl border p-5 ${TONE[shown.verdict].box}`}>
            <div className={`text-[20px] font-[680] ${TONE[shown.verdict].text}`}>{TONE[shown.verdict].word}</div>
            <p className="mt-1 text-[14px] leading-relaxed">{shown.headline}</p>
            {checked && <p className="mt-2 text-[12px] text-faint">Checked against the text you pasted.</p>}
          </section>

          {shown.checks.length > 0 && (
            <ul className="mt-5 divide-y divide-border rounded-xl border border-border-strong">
              {shown.checks.map((c) => (
                <li key={c.name} className="flex gap-3 px-4 py-3">
                  <span className={`mt-0.5 w-5 shrink-0 text-center font-[700] ${c.status === "pass" ? "text-verified" : c.status === "fail" ? "text-contradicted" : "text-flag"}`}>
                    {c.status === "pass" ? "✓" : c.status === "fail" ? "✕" : "?"}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-[590]">{c.label}</div>
                    <div className="text-[12.5px] text-faint break-words">{c.detail}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {res?.seal && (
            <section className="mt-6">
              <h2 className="text-[14px] font-[620]">What the agent signed</h2>
              <p className="mt-1 text-[12.5px] text-faint">
                {res.seal.agent_name} · {res.seal.kind === "offer_letter" ? "offer letter" : "message"}{res.seal.to ? ` to ${res.seal.to}` : ""} ·
                permission {res.seal.scope} · {new Date(res.seal.created_at).toLocaleString()}
              </p>
              <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg border border-border-strong bg-surface px-4 py-3 text-[13px] leading-relaxed">{res.seal.body}</pre>
              <p className="mt-1 break-all font-mono text-[11px] text-faint">sha256 {res.seal.sha256} · ledger {res.seal.ledger_entry}</p>
            </section>
          )}

          {res?.seal && (
            <section className="mt-6">
              <h2 className="text-[14px] font-[620]">Check the copy you received</h2>
              <p className="mt-1 text-[12.5px] text-faint">Paste the whole message, including its footer. Any change to it shows up here.</p>
              <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={6}
                className="mt-2 w-full rounded-lg border border-border-strong bg-transparent px-3 py-2 text-[13px]" />
              <button onClick={check} disabled={!pasted.trim() || busy}
                className="mt-2 h-9 rounded-lg bg-[var(--color-ink,#111)] px-4 text-[13px] font-[590] text-white disabled:opacity-40 dark:bg-white dark:text-black">
                {busy ? "Checking…" : "Check this text"}
              </button>
            </section>
          )}

          <p className="mt-10 text-[12px] text-faint">
            Agents and developers: <code>GET /api/verify/{id}</code> or <code>POST /api/verify {"{"}&quot;text&quot;: &quot;…&quot;{"}"}</code> on the Agaxes API returns the same verdict as JSON.
          </p>
        </>
      )}
    </main>
  );
}
