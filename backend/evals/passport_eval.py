"""Live accuracy eval for the Agent Passport (docs/COUNTERSIGN.md part 1).

Finds real sponsors through Crustdata Person Search across role buckets (talent, eng leaders, founders,
finance, sales, individual contributors), enriches them once, then generates labelled cases from each
real record:

    genuine            exact current employer/title/domain, a scope the role clearly can grant -> allow
    company_variant    same, but the company written differently ("Acme" vs "Acme Pvt Ltd")      -> allow
    left               a past employer they no longer work at                                     -> block (sponsor_still_employed)
    stale_title        an old title at their current company (internal move)                      -> block (sponsor_title_current)
    inflated_title     "Chief Executive Officer" at their current company                         -> block (sponsor_title_current)
    lookalike_domain   acme-hr.com / acrne.com / acme.co instead of acme.com                     -> block (domain_matches_company)
    wrong_person       another sponsor's name on this profile URL                                 -> block (sponsor_exists)
    overreach          a scope the role clearly can't grant (IC signing contracts)                -> block (sponsor_can_grant_scope)
    + fake_url, tampered, expired (a few each)

Labels come from the search bucket and the record itself, not from the passport's rule table.

    cd backend
    python -m evals.passport_eval                       # live (CRUSTDATA_MODE=cache, reruns hit cache/)
    python -m evals.passport_eval --per-query 3 --out ../eval_live_passport.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
_tmp = tempfile.mkdtemp(prefix="passport_eval_")
os.environ.setdefault("LEDGER_PATH", str(Path(_tmp) / "ledger.jsonl"))
os.environ.setdefault("ISSUER_KEY_PATH", str(Path(_tmp) / "issuer.key"))

from app.agents.graph import Graph, norm_url  # noqa: E402
from app.agents.models import Sponsor  # noqa: E402
from app.agents.passport import issue_passport, title_terms, verify_passport  # noqa: E402
from app.crustdata.client import TITLE_FIELD, CrustdataClient  # noqa: E402
from app.verify.profile import Job, load_person, norm, same_company  # noqa: E402

# bucket -> (search titles, scopes it clearly CAN grant, scopes it clearly CANNOT grant)
BUCKETS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "talent": (["Head of Talent Acquisition", "Talent Acquisition Manager", "Technical Recruiter", "HR Business Partner"],
               ["outreach.hiring", "data.read"], ["payment.send"]),
    "eng_leader": (["Engineering Manager", "VP Engineering", "Chief Technology Officer", "Director of Engineering"],
                   ["outreach.hiring", "data.read"], ["payment.send"]),
    "founder": (["Founder", "Co-Founder", "Chief Executive Officer"], ["contract.sign", "outreach.hiring", "data.read"], []),
    "finance": (["Chief Financial Officer", "Finance Controller", "Head of Finance"], ["payment.send", "data.read"], ["outreach.hiring"]),
    "sales": (["Head of Sales", "Business Development Manager", "Account Executive", "Sales Director"],
              ["outreach.sales", "data.read"], ["payment.send", "outreach.hiring"]),
    "ic": (["Software Engineer", "Data Analyst", "Product Designer", "QA Engineer", "Software Engineering Intern"],
           ["data.read"], ["contract.sign", "payment.send", "outreach.hiring"]),
}
# Titles in a bucket that override the bucket's CANNOT list (e.g. an "Account Executive" can't hire, a "Sales Director" arguably can).
SENIOR = re.compile(r"\b(head|director|vp|vice president|chief|founder|cxo|cto|ceo|cfo|coo|president|partner|owner)\b", re.I)


@dataclass
class Case:
    id: str
    category: str
    bucket: str
    sponsor: dict
    scope: str
    expect: str
    expect_check: str | None = None
    tamper: str | None = None  # "edit" | "expired"
    note: str = ""


@dataclass
class Result:
    case: Case
    decision: str
    checks: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        if self.decision != self.case.expect:
            return False
        if self.case.expect == "block" and self.case.expect_check:
            return any(c["name"] == self.case.expect_check and c["status"] != "pass" for c in self.checks)
        return True


def strip_suffix(name: str) -> str:
    return re.sub(r"[\s,]*(pvt\.?|private|ltd\.?|limited|inc\.?|llc|llp|corp\.?|corporation|gmbh|plc)\b\.?",
                  "", name, flags=re.I).strip(" ,.") or name


def company_variant(name: str) -> str:
    s = strip_suffix(name)
    return s if s != name else f"{name} Pvt Ltd"


def lookalikes(domain: str) -> list[str]:
    base, _, tld = domain.partition(".")
    out = [f"{base}-hr.{tld}", f"{base}.co" if tld != "co" else f"{base}.io", f"{base}careers.com"]
    for a, b in (("m", "rn"), ("o", "0"), ("l", "1"), ("i", "1"), ("e", "3")):
        if a in base:
            out.append(f"{base.replace(a, b, 1)}.{tld}")
            break
    else:
        out.append(f"{base}{base[-1]}.{tld}")
    return out


def matched_job(pr, query: str) -> Job | None:
    q = set(norm(query).split()) - {"of", "and", "the"}
    best = None
    for j in pr.current:
        t = set(norm(j.title).split())
        if q & t and (best is None or len(q & t) > len(q & set(norm(best.title).split()))):
            best = j
    return best or (pr.current[0] if pr.current else None)


def build_cases(people: list[tuple[str, str, dict]], rng: random.Random) -> list[Case]:
    cases: list[Case] = []
    names = [load_person(r).name for _, _, r in people]
    for idx, (bucket, query, rec) in enumerate(people):
        pr = load_person(rec)
        job = matched_job(pr, query)
        if not (pr.name and pr.profile_url and job and job.company and job.title):
            continue
        can, cannot = BUCKETS[bucket][1], BUCKETS[bucket][2]
        if SENIOR.search(job.title or ""):
            cannot = [s for s in cannot if s == "payment.send" and not re.search(r"cfo|financ|founder|ceo|owner|president|partner|managing director", job.title, re.I)]
        pid = f"{bucket}{idx:03d}"
        base = {"name": pr.name, "profile_url": pr.profile_url, "company": job.company, "company_domain": job.domain, "title": job.title}
        scope = can[0]
        cases.append(Case(f"{pid}-genuine", "genuine", bucket, base, scope, "allow", note=f"{job.title} @ {job.company}"))
        cases.append(Case(f"{pid}-variant", "company_variant", bucket, {**base, "company": company_variant(job.company)}, scope, "allow",
                          note=f"{job.company!r} -> {company_variant(job.company)!r}"))
        for sc in cannot[:1]:
            cases.append(Case(f"{pid}-overreach", "overreach", bucket, base, sc, "block", "sponsor_can_grant_scope", note=f"{job.title} -> {sc}"))
        if job.domain:
            fake = rng.choice(lookalikes(job.domain))
            cases.append(Case(f"{pid}-lookalike", "lookalike_domain", bucket, {**base, "company_domain": fake}, scope, "block",
                              "domain_matches_company", note=f"{job.domain} -> {fake}"))
        here = [c for c in pr.current if same_company(c.company, job.company)]  # all their current roles at this employer
        cur_domains = {c.domain for c in pr.current if c.domain}
        # a past employer that shares a current domain is a rename (Nexxbase -> Noise), not a departure
        left = [p for p in pr.past if p.company and not any(same_company(p.company, c.company) for c in pr.current)
                and p.domain not in cur_domains]
        if left:
            p = left[0]
            cases.append(Case(f"{pid}-left", "left", bucket,
                              {**base, "company": p.company, "company_domain": p.domain, "title": p.title}, scope, "block",
                              "sponsor_still_employed", note=f"left {p.company} {p.end}"))
        # an old title that isn't just a subset of a current one ("Director" -> "Senior Director" is understating, not stale)
        moved = [p for p in pr.past if same_company(p.company, job.company) and p.title
                 and not any(title_terms(p.title) <= title_terms(c.title) for c in here)]
        if moved:
            cases.append(Case(f"{pid}-stale", "stale_title", bucket, {**base, "title": moved[0].title}, scope, "block",
                              "sponsor_title_current", note=f"was {moved[0].title!r}, now {job.title!r}"))
        if not any(re.search(r"\b(ceo|chief executive)\b", c.title or "", re.I) for c in here):
            cases.append(Case(f"{pid}-inflated", "inflated_title", bucket, {**base, "title": "Chief Executive Officer"}, scope, "block",
                              "sponsor_title_current", note=f"really {job.title!r}"))
        other = names[(idx + 7) % len(names)]
        if other and norm(other) != norm(pr.name):
            cases.append(Case(f"{pid}-wrongname", "wrong_person", bucket, {**base, "name": other}, scope, "block", "sponsor_exists",
                              note=f"{other!r} on {pr.name!r}'s profile"))
        if idx % 10 == 0:
            cases.append(Case(f"{pid}-tampered", "tampered", bucket, base, scope, "block", "signature_valid", tamper="edit"))
            cases.append(Case(f"{pid}-expired", "expired", bucket, base, scope, "block", "not_expired", tamper="expired"))
    for i in range(3):
        cases.append(Case(f"fake{i}", "fake_url", "none",
                          {"name": "Priya Sharma", "profile_url": f"https://www.linkedin.com/in/priya-sharma-hr-{rng.randint(10**8, 10**9)}",
                           "company": "Razorpay", "company_domain": "razorpay.com", "title": "Head of Talent"},
                          "outreach.hiring", "block", "sponsor_exists"))
    return cases


class PrefetchedGraph(Graph):
    def __init__(self, client, records: dict[str, dict]):
        super().__init__(client)
        self.records = records

    async def person(self, profile_url: str):
        rec = self.records.get(norm_url(profile_url))
        return rec if rec is not None else await super().person(profile_url)


async def find_people(client: CrustdataClient, per_query: int, buckets: list[str]) -> list[tuple[str, str, str]]:
    jobs = [(b, q) for b in buckets for q in BUCKETS[b][0]]
    res = await asyncio.gather(*(client.person_search({"field": TITLE_FIELD, "type": "(.)", "value": q}, limit=per_query) for _, q in jobs),
                               return_exceptions=True)
    seen, out = set(), []
    for (b, q), rows in zip(jobs, res):
        if isinstance(rows, Exception):
            print(f"  search failed for {q!r}: {rows}")
            continue
        for r in rows:
            url = load_person(r).profile_url
            if url and norm_url(url) not in seen:
                seen.add(norm_url(url))
                out.append((b, q, url))
    return out


async def run_case(c: Case, graph: Graph, sem: asyncio.Semaphore) -> Result:
    async with sem:
        days = -1 if c.tamper == "expired" else 30
        now = datetime.now(timezone.utc) - (timedelta(days=5) if c.tamper == "expired" else timedelta())
        p, _ = issue_passport("EvalAgent", "eval", Sponsor(**c.sponsor), [c.scope], days, now=now, record=False)
        if c.tamper == "edit":
            p.scopes.append("payment.send")
        v = await verify_passport(p, scope=c.scope, graph=graph, record=False)
        return Result(c, v.decision, [ch.model_dump() for ch in v.checks])


def report(results: list[Result], stats: dict, secs: float) -> str:
    by = defaultdict(list)
    for r in results:
        by[r.case.category].append(r)
    total_ok = sum(r.ok for r in results)
    allow = [r for r in results if r.case.expect == "allow"]
    block = [r for r in results if r.case.expect == "block"]
    lines = [f"# Passport live eval ({datetime.now().strftime('%H:%M')})", "",
             f"**{total_ok}/{len(results)} correct ({100 * total_ok / max(1, len(results)):.1f}%)**  "
             f"false blocks {sum(not r.ok for r in allow)}/{len(allow)}, missed blocks {sum(r.decision == 'allow' for r in block)}/{len(block)}, "
             f"blocked-for-wrong-reason {sum(r.decision == 'block' and not r.ok for r in block)}  "
             f"| crustdata {stats} | {secs:.0f}s", "",
             "| category | correct | total |", "|---|---|---|"]
    for cat, rs in sorted(by.items()):
        lines.append(f"| {cat} | {sum(r.ok for r in rs)} | {len(rs)} |")
    lines += ["", "## Failures", ""]
    for r in results:
        if r.ok:
            continue
        c = r.case
        lines.append(f"- **{c.id}** [{c.category}] expect {c.expect}"
                     f"{' via ' + c.expect_check if c.expect_check else ''}, got **{r.decision}**. {c.note}")
        for ch in r.checks:
            if ch["status"] != "pass" or c.expect == "block":
                lines.append(f"    - {ch['status']} {ch['name']}: {ch['detail']}")
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-query", type=int, default=4)
    ap.add_argument("--buckets", default=",".join(BUCKETS))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "eval_live_passport.md"))
    ap.add_argument("--cases-out", default=str(ROOT / "backend" / "data" / "passport_eval_cases.json"))
    a = ap.parse_args()
    t0 = time.time()
    client = CrustdataClient(mode=os.getenv("CRUSTDATA_MODE", "cache"))
    found = await find_people(client, a.per_query, a.buckets.split(","))
    print(f"found {len(found)} sponsors")
    urls = sorted({u for _, _, u in found})
    recs = await client.person_enrich_many(urls)  # one deterministic batch set, so reruns hit cache
    records = {norm_url(u): r for u, r in recs.items() if r}
    people = [(b, q, records[norm_url(u)]) for b, q, u in found if norm_url(u) in records]
    cases = build_cases(people, random.Random(a.seed))
    print(f"enriched {len(people)}, {len(cases)} cases")
    graph = PrefetchedGraph(client, records)
    sem = asyncio.Semaphore(10)
    results = await asyncio.gather(*(run_case(c, graph, sem) for c in cases))
    md = report(results, dict(client.stats), time.time() - t0)
    Path(a.out).write_text(md)
    Path(a.cases_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.cases_out).write_text(json.dumps([{**r.case.__dict__, "decision": r.decision, "ok": r.ok, "checks": r.checks} for r in results],
                                            indent=1, default=str))
    print(md.split("## Failures")[0])
    print(f"full report: {a.out}\ncases: {a.cases_out}")
    print("failure categories:", Counter(r.case.category for r in results if not r.ok))


if __name__ == "__main__":
    asyncio.run(main())
