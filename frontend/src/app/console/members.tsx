"use client";
// Members: who in the company can see and control its agents (backend/app/accounts/members_api.py).
import { useCallback, useEffect, useState } from "react";
import { Loader2, ShieldAlert, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { ApiError, api, type Member, type Workspace, type WorkspaceRole } from "./api";
import { EmptyState, PageHead, SectionHead, ago, cardCls } from "./parts";

const ROLE_LABEL: Record<WorkspaceRole, string> = { viewer: "Viewer", member: "Member", admin: "Admin", owner: "Owner" };
// The role list from the backend also carries the platform operator, which isn't a workspace role.
const roleLabel = (r: string) => (ROLE_LABEL as Record<string, string>)[r] ?? (r === "operator" ? "Platform operator" : r);

export function MembersView({ ws }: { ws: Workspace | null }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  // The platform operator ranks above an owner, so it can manage its own workspace too.
  const owner = ws?.via === "session" && (ws.role === "owner" || ws.role === "operator");

  const load = useCallback(() => {
    setError(null);
    api.members().then(setMembers).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const change = async (m: Member, role: WorkspaceRole) => {
    if (role === m.workspace_role) return;
    setBusy(m.id);
    setNote(null);
    try {
      await api.setRole(m.id, role);
      setNote({ tone: "ok", text: `${m.full_name || m.email} is now ${ROLE_LABEL[role].toLowerCase()}. The change is on the ledger.` });
      load();
    } catch (e) {
      setNote({ tone: "bad", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-6 sm:px-8 sm:py-8">
      <PageHead title="Members">
        Everyone at {ws?.company?.name ?? "your company"} who can use {BRAND.name}, and what their role lets them do. Only an owner can change
        roles, and every change is written to the ledger.
      </PageHead>

      {ws?.auth_mode === "open" && (
        <p className="mt-5 flex items-start gap-2 rounded-lg border border-flag/30 bg-flag/[0.07] px-3 py-2.5 text-[12.5px] leading-relaxed text-secondary">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-flag" />
          <span>
            Roles aren&apos;t enforced yet: this backend is open, so anyone who can reach it can control agents. Start it with{" "}
            <code className="font-mono text-[11.5px]">AGAXES_REQUIRE_LOGIN=1</code> to require a login and these roles.
          </span>
        </p>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0">
          <SectionHead title={members ? `People (${members.length})` : "People"} />
          <div className={cn(cardCls, "mt-3 overflow-hidden")}>
            {error ? (
              <EmptyState icon={Users} title="Log in to see your team">
                {/admin token|workspace user/i.test(error)
                  ? `Members belong to a company workspace. You're using ${BRAND.name} without a company login (open access or the admin token), so there's no team to show.`
                  : error}
              </EmptyState>
            ) : !members ? (
              <p className="flex items-center gap-2 px-4 py-6 text-[13px] text-faint"><Loader2 className="size-4 animate-spin" /> Loading</p>
            ) : !members.length ? (
              <EmptyState icon={Users} title="No one yet">People who sign up with your company&apos;s email domain join this workspace.</EmptyState>
            ) : (
              <ul className="divide-y divide-border">
                {members.map((m) => (
                  <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-full bg-elevated text-[11.5px] font-[590] text-muted-foreground">
                      {(m.full_name || m.email).split(/[\s@.]/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("")}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-[510]">{m.full_name || m.email}</span>
                      <span className="block truncate text-[12px] text-muted-foreground">
                        {m.email}{m.job_role ? ` · ${m.job_role}` : ""}{m.last_login_at ? ` · last in ${ago(m.last_login_at)}` : ""}
                      </span>
                    </span>
                    {owner ? (
                      <span className="flex items-center gap-2">
                        {busy === m.id && <Loader2 className="size-3.5 animate-spin text-faint" />}
                        <select
                          value={m.workspace_role}
                          disabled={!!busy}
                          onChange={(e) => change(m, e.target.value as WorkspaceRole)}
                          aria-label={`Role for ${m.email}`}
                          className="h-8 rounded-md border border-border-strong bg-panel px-2 text-[12.5px]"
                        >
                          {(Object.keys(ROLE_LABEL) as WorkspaceRole[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                        </select>
                      </span>
                    ) : (
                      <span className="rounded-full border border-border-strong px-2 py-0.5 text-[11.5px] text-secondary">{roleLabel(m.workspace_role)}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {note && (
            <p className={cn("mt-3 text-[12.5px]", note.tone === "ok" ? "text-verified" : "text-contradicted")}>{note.text}</p>
          )}
          {members && !owner && ws?.via === "session" && (
            <p className="mt-3 text-[12px] text-muted-foreground">You&apos;re {roleLabel(ws.role).toLowerCase()}. Ask an owner to change someone&apos;s role.</p>
          )}
        </section>

        <aside className="min-w-0">
          <SectionHead title="What each role can do" />
          <ol className={cn(cardCls, "mt-3 divide-y divide-border")}>
            {(ws?.roles ?? []).map((r) => (
              <li key={r.role} className="px-4 py-3">
                <p className="flex items-center gap-2 text-[13px] font-[590]">
                  {roleLabel(r.role)}
                  {ws?.via === "session" && ws.role === r.role && <span className="rounded-full bg-elevated px-1.5 py-px text-[10.5px] font-[510] text-muted-foreground">You</span>}
                </p>
                <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{r.can}</p>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </main>
  );
}
