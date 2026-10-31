"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, BadgeCheck, Building2, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { AuthShell, Button, Field, Input, Notice, PasswordInput, Select, postJSON, type ApiError } from "@/components/auth/ui";

// Kept in step with backend/app/accounts/api.py (the backend validates them again).
const SIZE_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5001+"];
const JOB_ROLES = ["Recruiter", "Sourcer", "Head of Talent", "Hiring manager", "Founder or executive", "HR or People ops", "Agency recruiter", "Other"];
const HIRING_VOLUMES = ["1-5", "6-20", "21-50", "51-200", "200+"];
const HIRING_FOR = ["Engineering", "Product", "Design", "Data", "Sales", "Marketing", "Operations", "Leadership"];
const ATS = ["None yet", "Greenhouse", "Lever", "Ashby", "Workable", "Workday", "Spreadsheet", "Other"];

interface LookupCompany {
  name: string;
  size_band: string | null;
  employee_count_range: string | null;
  industry: string | null;
  logo_url: string | null;
  year_founded: number | null;
}
interface Lookup {
  domain: string;
  existing_workspace: { name: string; members: number } | null;
  company: LookupCompany | null;
}

function passwordHint(p: string): { label: string; tone: string } | null {
  if (!p) return null;
  if (p.length < 10) return { label: `${10 - p.length} more characters`, tone: "text-contradicted" };
  const variety = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length;
  if (p.length >= 14 || variety >= 3) return { label: "Strong", tone: "text-verified" };
  return { label: "Fine. Longer is stronger.", tone: "text-muted-foreground" };
}

function SignupForm() {
  const router = useRouter();
  const [step, setStep] = useState<"email" | "details">("email");
  const [email, setEmail] = useState("");
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);

  const [form, setForm] = useState({
    full_name: "", job_role: "", password: "", company_name: "", size_band: "", hiring_volume: "",
    hiring_for: [] as string[], current_ats: "", hq_country: "", accept_terms: false,
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));
  const joining = !!lookup?.existing_workspace;

  async function checkEmail(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    const r = await postJSON<Lookup>("/api/auth/lookup", { email });
    setBusy(false);
    if (!r.ok) return setErr(r.err);
    setLookup(r.data);
    const c = r.data.company;
    setForm((f) => ({
      ...f,
      company_name: c?.name || f.company_name || guessName(r.data.domain),
      size_band: c?.size_band || f.size_band,
    }));
    setStep("details");
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    const r = await postJSON("/api/auth/signup", {
      email, ...form,
      job_role: form.job_role || null, size_band: form.size_band || null, hiring_volume: form.hiring_volume || null,
      current_ats: form.current_ats || null, hq_country: form.hq_country || null, industry: lookup?.company?.industry || null,
    });
    if (r.ok) {
      router.replace("/");
      router.refresh();
    } else {
      setErr(r.err);
      setBusy(false);
      if (r.err.field === "email") setStep("email");
    }
  }

  const fieldErr = (f: string) => (err?.field === f ? err.message : null);
  const pw = passwordHint(form.password);

  if (step === "email") {
    return (
      <>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Create your company workspace</h1>
        <p className="mt-1 text-[14px] text-muted-foreground">
          Free to start, no sales call. Already have an account? <Link href="/login" className="font-medium text-foreground underline-offset-4 hover:underline">Log in</Link>
        </p>
        <form onSubmit={checkEmail} className="mt-6 space-y-4" noValidate>
          {err && !err.field && <Notice tone="error">{err.message}</Notice>}
          <Field label="Work email" htmlFor="email" error={fieldErr("email")}
            hint="We use your company domain to set up the workspace and look up your company on Crustdata.">
            <Input id="email" type="email" autoComplete="email" autoFocus value={email} placeholder="you@company.com"
              aria-invalid={!!fieldErr("email")} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Button type="submit" loading={busy} disabled={!email || busy}>Continue</Button>
          {err?.error === "email_taken" && (
            <Link href={`/login?email=${encodeURIComponent(email)}`} className="block text-center text-[13px] font-medium text-primary hover:underline">
              Log in as {email}
            </Link>
          )}
        </form>
        <ol className="mt-8 flex items-center gap-2 text-[12px] text-faint">
          <li className="font-medium text-foreground">1 Email</li><li>·</li><li>2 You and your company</li>
        </ol>
      </>
    );
  }

  return (
    <>
      <button onClick={() => { setStep("email"); setErr(null); }} className="mb-4 inline-flex items-center gap-1 self-start text-[13px] text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-3.5" /> {email}
      </button>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">{joining ? `Join ${lookup!.existing_workspace!.name}` : "Tell us about your team"}</h1>
      <p className="mt-1 text-[14px] text-muted-foreground">Required fields only take a minute. You can change everything later.</p>

      <form onSubmit={create} className="mt-6 space-y-5" noValidate>
        {err && !["full_name", "password", "company_name", "accept_terms", "size_band", "hiring_volume"].includes(err.field || "") && (
          <Notice tone="error">{err.message}</Notice>
        )}

        {joining ? (
          <Notice tone="info">
            <span className="flex items-start gap-2">
              <Users className="mt-0.5 size-4 shrink-0 text-primary" />
              <span>
                <strong className="font-medium">{lookup!.existing_workspace!.name}</strong> already has a workspace for {lookup!.domain}
                {" "}({lookup!.existing_workspace!.members} {lookup!.existing_workspace!.members === 1 ? "member" : "members"}). You&apos;ll join it, so shortlists and agents are shared instead of split across duplicate accounts.
              </span>
            </span>
          </Notice>
        ) : (
          <CompanyCard lookup={lookup!} />
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Full name" htmlFor="full_name" error={fieldErr("full_name")}>
            <Input id="full_name" autoComplete="name" autoFocus value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
          </Field>
          <Field label="Your role" htmlFor="job_role">
            <Select id="job_role" value={form.job_role} onChange={(e) => set("job_role", e.target.value)} options={JOB_ROLES} placeholder="Choose…" />
          </Field>
        </div>

        <Field label="Password" htmlFor="password" error={fieldErr("password")}
          hint={pw ? undefined : "At least 10 characters. A short phrase works well."}>
          <PasswordInput id="password" autoComplete="new-password" value={form.password} aria-invalid={!!fieldErr("password")}
            onChange={(e) => set("password", e.target.value)} />
          {pw && !fieldErr("password") && <p className={cn("text-[12.5px]", pw.tone)}>{pw.label}</p>}
        </Field>

        {!joining && (
          <>
            <div className="h-px bg-border" />
            <Field label="Company name" htmlFor="company_name" error={fieldErr("company_name")}>
              <Input id="company_name" autoComplete="organization" value={form.company_name} onChange={(e) => set("company_name", e.target.value)} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Company size" htmlFor="size_band" error={fieldErr("size_band")}
                hint={lookup?.company?.employee_count_range ? `Crustdata lists ${lookup.company.employee_count_range} employees` : undefined}>
                <Select id="size_band" value={form.size_band} onChange={(e) => set("size_band", e.target.value)} options={SIZE_BANDS} placeholder="Employees…" />
              </Field>
              <Field label="Hires in the next 12 months" htmlFor="hiring_volume" error={fieldErr("hiring_volume")}>
                <Select id="hiring_volume" value={form.hiring_volume} onChange={(e) => set("hiring_volume", e.target.value)} options={HIRING_VOLUMES} placeholder="Roughly…" />
              </Field>
            </div>
            <Field label="Teams you hire for" optional hint="Sourced uses this to suggest title variants for your briefs.">
              <div className="flex flex-wrap gap-1.5">
                {HIRING_FOR.map((t) => {
                  const on = form.hiring_for.includes(t);
                  return (
                    <button key={t} type="button" aria-pressed={on}
                      onClick={() => set("hiring_for", on ? form.hiring_for.filter((x) => x !== t) : [...form.hiring_for, t])}
                      className={cn("h-7 rounded-full border px-2.5 text-[12.5px] transition",
                        on ? "border-primary bg-sky text-foreground" : "border-border-strong text-muted-foreground hover:bg-hover")}>
                      {t}
                    </button>
                  );
                })}
              </div>
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Current ATS" htmlFor="current_ats" optional>
                <Select id="current_ats" value={form.current_ats} onChange={(e) => set("current_ats", e.target.value)} options={ATS} placeholder="Choose…" />
              </Field>
              <Field label="HQ country" htmlFor="hq_country" optional>
                <Input id="hq_country" autoComplete="country-name" value={form.hq_country} onChange={(e) => set("hq_country", e.target.value)} placeholder="India" />
              </Field>
            </div>
          </>
        )}

        <Field label="" error={fieldErr("accept_terms")}>
          <label className="flex items-start gap-2 text-[13px] text-secondary">
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={form.accept_terms}
              onChange={(e) => set("accept_terms", e.target.checked)} />
            <span>I agree to the terms and confirm Sourced may look up public professional data about candidates on my behalf. Agents draft outreach but never send it without a check.</span>
          </label>
        </Field>

        <Button type="submit" loading={busy}
          disabled={busy || !form.full_name.trim() || form.password.length < 10 || !form.accept_terms || (!joining && !form.company_name.trim())}>
          {joining ? "Join workspace" : "Create workspace"}
        </Button>
      </form>
    </>
  );
}

function CompanyCard({ lookup }: { lookup: Lookup }) {
  const c = lookup.company;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-elevated p-3">
      {c?.logo_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={c.logo_url} alt="" className="size-9 rounded-md border border-border bg-panel object-cover" />
      ) : (
        <span className="grid size-9 place-items-center rounded-md border border-border bg-panel"><Building2 className="size-4 text-faint" /></span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium">{c?.name || lookup.domain}</p>
        <p className="truncate text-[12.5px] text-muted-foreground">
          {c ? [c.industry, c.employee_count_range && `${c.employee_count_range} employees`, c.year_founded && `founded ${c.year_founded}`].filter(Boolean).join(" · ")
            : "We couldn't match this domain on Crustdata. Fill in the details below."}
        </p>
      </div>
      {c && (
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border bg-panel px-2 py-0.5 text-[11.5px] text-verified" title="Matched on Crustdata Company Identify (company/identify, basic_info)">
          <BadgeCheck className="size-3" /> Crustdata
        </span>
      )}
    </div>
  );
}

function guessName(domain: string) {
  const base = domain.split(".")[0] || "";
  return base.charAt(0).toUpperCase() + base.slice(1);
}

export default function SignupPage() {
  return (
    <AuthShell>
      <Suspense>
        <SignupForm />
      </Suspense>
    </AuthShell>
  );
}
