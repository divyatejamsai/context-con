"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, LogOut, Plus } from "lucide-react";
import type { AuthCompany, AuthUser } from "@/lib/auth";

/** Avatar button in the app header: who's signed in, which workspace, and log out. */
/** `up`: in a sidebar footer, open upward and anchor to the nearest positioned parent (the footer row) so it stays on screen. */
export function AccountMenu({ up }: { up?: boolean } = {}) {
  const router = useRouter();
  const [me, setMe] = useState<{ user: AuthUser; company: AuthCompany } | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then(setMe).catch(() => {});
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!me) return null;
  const initials = me.user.full_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();

  async function logout(to = "/login?reason=logout") {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    router.replace(to);
    router.refresh();
  }

  return (
    <div ref={ref} className={up ? undefined : "relative"}>
      <button onClick={() => setOpen((o) => !o)} aria-label="Account" aria-expanded={open}
        className="grid size-7 place-items-center rounded-full border border-border-strong bg-elevated text-[11px] font-semibold hover:bg-hover">
        {initials}
      </button>
      {open && (
        <div className={`${up ? "absolute inset-x-0 bottom-9" : "absolute right-0 top-9 w-64"} z-50 rounded-lg border border-border bg-panel p-1 shadow-[var(--shadow)] animate-fade`}>
          <div className="px-2.5 py-2">
            <p className="truncate text-[13px] font-medium">{me.user.full_name}</p>
            <p className="truncate text-[12px] text-muted-foreground">{me.user.email}</p>
          </div>
          <div className="mx-1 rounded-md bg-elevated px-2 py-1.5">
            <p className="flex items-center gap-1 truncate text-[12.5px] font-medium">
              {me.company.name}
              {me.company.verified_via === "crustdata" && <BadgeCheck className="size-3 shrink-0 text-verified" aria-label="Verified on Crustdata" />}
            </p>
            <p className="truncate text-[11.5px] text-muted-foreground">
              {me.company.domain} · {me.user.workspace_role === "owner" ? "Owner" : "Member"}
              {me.company.verified_via === "demo" && " · demo"}
            </p>
          </div>
          <button onClick={() => logout("/signup")} className="mt-1 flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] text-muted-foreground hover:bg-hover hover:text-foreground">
            <Plus className="size-3.5" /> Create a new workspace
          </button>
          <button onClick={() => logout()} className=" flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] text-muted-foreground hover:bg-hover hover:text-foreground">
            <LogOut className="size-3.5" /> Log out
          </button>
        </div>
      )}
    </div>
  );
}
