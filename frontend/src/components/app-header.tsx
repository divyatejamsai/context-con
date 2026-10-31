"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BadgeCheck, Check, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { BrandMark } from "@/components/brand-mark";

/** Sourced's three jobs, in the order a recruiter would meet them. The tab names say what each page is for. */
export const PRODUCT_TABS = [
  { href: "/sourced", label: "Shortlist", title: "Paste a brief and get a ranked shortlist where every claim is checked against Crustdata" },
  { href: "/campaigns", label: "Campaigns", title: "Take one brief all the way to a signed offer: Sourced runs about 100 conversations at once" },
  { href: "/staffing", label: "Shift staffing", title: "Fill 1,000 shifts from applicants and catch the ones who lie on their application" },
] as const;

export function Logo() {
  return (
    <span className="grid size-6 place-items-center rounded-[5px] bg-foreground">
      <Check className="size-3.5 text-background" strokeWidth={3} />
    </span>
  );
}

export function ProductNav({ active }: { active: (typeof PRODUCT_TABS)[number]["href"] }) {
  return (
    <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto" aria-label="Sourced">
      {PRODUCT_TABS.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          prefetch={false}
          title={t.title}
          aria-current={active === t.href ? "page" : undefined}
          className={cn(
            "inline-flex h-7 shrink-0 items-center rounded-md px-2.5 text-[13px] transition",
            active === t.href ? "bg-elevated font-[510] text-foreground" : "text-muted-foreground hover:bg-hover hover:text-foreground",
          )}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

export function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.dataset.theme === "dark"), []);
  const flip = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {}
    setDark(!dark);
  };
  return (
    <button onClick={flip} className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground" aria-label={dark ? "Light theme" : "Dark theme"}>
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

/** Sourced is one agent inside Agaxes: this crumb takes you back to the console where all agents live. */
export function AgaxesCrumb() {
  return (
    <>
      <Link
        href="/console"
        prefetch={false}
        className="flex shrink-0 items-center gap-2 rounded-md py-1 pr-1 transition hover:opacity-80"
        title={`Back to ${BRAND.name}, where all your agents are`}
      >
        <BrandMark className="size-6 rounded-[6px]" />
        <span className="hidden text-[13.5px] font-[590] tracking-[-0.01em] md:inline">{BRAND.name}</span>
      </Link>
      <span className="text-[14px] text-border-strong">/</span>
    </>
  );
}

/** Opens this agent's page in Agaxes: its passport, Send Guard verdicts, work and history. */
export function ConsoleLink() {
  return (
    <Link
      href={`/console?agent=${encodeURIComponent(BRAND.agent)}`}
      prefetch={false}
      className="hidden h-7 items-center gap-1.5 rounded-md border border-border px-2.5 text-[12px] font-[510] text-secondary transition hover:bg-hover hover:text-foreground sm:inline-flex"
      title={`${BRAND.agent}'s page in ${BRAND.name}: its passport, the Send Guard verdicts on its messages, and its history`}
    >
      <BadgeCheck className="size-3.5" /> Passport and history
    </Link>
  );
}

/** Header for the campaign and staffing pages: logo, the three product tabs, then page-specific controls. */
export function AppHeader({ active, children }: { active: (typeof PRODUCT_TABS)[number]["href"]; children?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-12 max-w-[1680px] items-center gap-3 px-4">
        <AgaxesCrumb />
        <Link href="/sourced" prefetch={false} className="flex shrink-0 items-center gap-2" title="Sourced home">
          <Logo />
          <span className="hidden text-[14px] font-semibold tracking-[-0.01em] sm:inline">Sourced</span>
        </Link>
        <span className="hidden text-[14px] text-border-strong sm:inline">/</span>
        <ProductNav active={active} />
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {children}
          <ConsoleLink />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
