"""Send Guard eval: many real recipients x many drafts, each labelled allow/block from the recipient's own record.

    cd backend
    LLM_MODE=mock CRUSTDATA_MODE=replay python -m evals.guard_eval              # offline: every person in the fixtures
    LLM_MODE=live CRUSTDATA_MODE=cache  python -m evals.guard_eval --live 120   # Sai's Mac: +120 people via person_search
    ... --out ../evals_out_guard.md   (gitignored: the report names real people)

Cases per recipient (only those the record supports):
  true      employer, exact title, rounded tenure, start year, city (incl. Bangalore/Gurgaon aliases), experience, no claims
  false     tenure +3y, a different company, inflated title, another city, experience +6y
  stale     past employer named as current (in the claim, or as the recipient's company), past title at past employer
  subtle    tenure +1.5y, "Senior" added, start year 2 years early, nearby-but-wrong city
  sender    facts about the sender (founded in 2019, 40-person team, Senior Engineer pitch) that must not block
  paraphrase  held-out wordings the offline rule extractor was not tuned on (number words, "since you joined",
            "Director of Engineering"); with LLM_MODE=live Gemini extracts them, offline they show the regex's limits
Plus tampering/authority cases (altered body, whitespace, another agent's signature, edited passport, expired, revoked,
scope not granted, sponsor who left, unknown recipient, no company). Labels come from the record, so a mismatch
between guard and label is a guard bug (or a mislabel, which the report makes easy to spot).
Reports false-allow rate (should-block cases that were allowed) and false-block rate, per category and per template.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import tempfile  # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="guard_eval_"))
os.environ.setdefault("LEDGER_PATH", str(_tmp / "ledger.jsonl"))
os.environ.setdefault("ISSUER_KEY_PATH", str(_tmp / "issuer.key"))
os.environ.setdefault("OUTBOX_PATH", str(_tmp / "outbox.jsonl"))

from app.agents.graph import Graph, norm_url  # noqa: E402
from app.agents.guard import check_send  # noqa: E402
from app.agents.models import Sponsor  # noqa: E402
from app.agents.passport import issue_passport, revoke, sign_message  # noqa: E402
from app.crustdata.client import extract_list  # noqa: E402
from app.verify.profile import Profile, load_person, seniority_rank, unwrap_record  # noqa: E402

SPONSORS = {s["id"]: s for s in json.loads((ROOT / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}
CITY_ALIASES = {"bengaluru": "Bangalore", "gurugram": "Gurgaon", "mumbai": "Bombay", "chennai": "Madras"}
CITIES = ["Bengaluru", "Mumbai", "Hyderabad", "Pune", "Chennai", "New Delhi", "Gurugram", "Kochi", "Surat", "Kolkata",
          "Noida", "Ahmedabad", "Jaipur", "Singapore", "London", "San Francisco"]
NEARBY = {"bengaluru": "Mysuru", "mumbai": "Pune", "pune": "Mumbai", "hyderabad": "Secunderabad", "new delhi": "Noida",
          "delhi": "Noida", "gurugram": "New Delhi", "noida": "New Delhi", "chennai": "Coimbatore", "kochi": "Thiruvananthapuram",
          "surat": "Ahmedabad", "ahmedabad": "Surat", "kolkata": "Howrah", "jaipur": "Udaipur"}
LIVE_TITLES = [
    ["Backend Engineer", "Software Engineer"], ["Product Manager"], ["Talent Acquisition", "Recruiter"],
    ["Sales Manager", "Account Executive"], ["Founder", "Co-Founder"], ["Data Scientist"], ["Engineering Manager"],
    ["Marketing Manager"], ["Designer", "Product Designer"], ["Finance Manager", "Chartered Accountant"],
]
LIVE_CITIES = ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Pune", "Chennai", "Gurugram"]


@dataclass
class Case:
    id: str
    category: str      # true | sender | false | stale | subtle | tamper | paraphrase
    template: str
    person: str        # profile url
    name: str
    to: dict
    body: str
    expect: str        # allow | block
    why: str
    tamper: str | None = None
    scope: str = "outreach.hiring"
    sponsor: str = "authorised_founder"
    got: str | None = None
    failing: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    ms: int = 0


# ---- people -----------------------------------------------------------------

def _rows(path: str) -> list[dict]:
    d = json.loads(Path(path).read_text())
    if isinstance(d, dict) and d.get("endpoint") == "person/enrich":
        return [m.get("person_data") for e in d.get("response") or [] for m in (e.get("matches") or []) if m.get("person_data")]
    if isinstance(d, dict) and d.get("endpoint") == "person/search":
        return extract_list(d.get("response"))
    return [unwrap_record(d)]


def fixture_people() -> dict[str, dict]:
    """Every distinct person in the committed fixtures (and local cache/). Enrich records win over search rows."""
    out: dict[str, dict] = {}
    pats = [("fixtures/crustdata/person_search/*.json", 0), ("cache/crustdata/person_search/*.json", 0),
            ("fixtures/crustdata/person_enrich_*.json", 1), ("fixtures/crustdata/person_enrich/*.json", 1),
            ("cache/crustdata/person_enrich/*.json", 1)]
    for pat, _ in pats:
        for f in sorted(glob.glob(str(ROOT / pat))):
            try:
                rows = _rows(f)
            except (OSError, json.JSONDecodeError):
                continue
            for r in rows:
                url = load_person(r).profile_url
                if url:
                    out[norm_url(url)] = r
    return out


async def live_people(client, n: int) -> dict[str, dict]:
    """person_search across varied titles/cities, then batch-enrich so labels and the guard read the same record."""
    urls: list[str] = []
    per = max(5, math.ceil(n / len(LIVE_TITLES)))
    for i, titles in enumerate(LIVE_TITLES):
        city = LIVE_CITIES[i % len(LIVE_CITIES)]
        try:
            rows = await client.person_search({"titles": titles, "locations": [city]}, limit=per)
        except Exception as e:  # noqa: BLE001
            print(f"  search {titles} {city} failed: {e}")
            continue
        urls += [u for u in (load_person(r).profile_url for r in rows) if u]
    urls = list(dict.fromkeys(urls))[:n]
    recs = await client.person_enrich_many(urls)
    return {norm_url(u): r for u, r in recs.items() if r}


# ---- case generation --------------------------------------------------------

def _yrs(a: date, b: date) -> float:
    return (b - a).days / 365.25


def _city(pr: Profile) -> str | None:
    if not pr.location:
        return None
    c = pr.location.split(",")[0].strip()
    return c if c and c.lower() not in ("india", "united states", "united kingdom") else None


def _fmt(y: float) -> str:
    return f"{y:g}"


def make_cases(people: dict[str, dict], today: date, rng: random.Random) -> list[Case]:
    cases: list[Case] = []
    companies = sorted({j.company for r in people.values() for j in load_person(r).current + load_person(r).past if j.company})

    for url, rec in people.items():
        pr = load_person(rec)
        if not pr.current or not pr.name:
            continue
        cur = pr.current[0]
        first = (pr.name.split() or ["there"])[0].title()
        to = {"name": pr.name, "profile_url": pr.profile_url, "company": cur.company}
        co = cur.company
        n = 0

        def add(cat: str, tpl: str, body: str, expect: str, why: str, **kw) -> None:
            nonlocal n
            n += 1
            cases.append(Case(id=f"{norm_url(url).rsplit('/', 1)[-1]}-{n}", category=cat, template=tpl, person=url, name=pr.name,
                              to=kw.pop("to", to), body=body, expect=expect, why=why, **kw))

        others = [c for c in companies if not any(c.lower() in j.company.lower() or j.company.lower() in c.lower()
                                                     for j in pr.current + pr.past if j.company)]
        other = rng.choice(others) if others else "Globex"
        concurrent = {j.company for j in pr.current}
        past = next((j for j in pr.past if j.company and not any(j.company.lower() == c.lower() for c in concurrent)), None)
        wrong_city = None

        # true
        add("true", "plain", f"Hi {first}, we're hiring for a role you might like. Open to a quick chat?", "allow", "no claims")
        add("true", "employer", f"Hi {first}, your work at {co} caught our eye. Open to a chat?", "allow", f"current employer {co}")
        add("true", "employer_alt", f"Hi {first}, loved what you've been building at {co}. Got 15 minutes this week?", "allow", f"current employer {co}")
        if cur.title:
            add("true", "title", f"Hi {first}, as a {cur.title} at {co} you'd find this role interesting.", "allow", f"title {cur.title}")
        if cur.start:
            t = _yrs(cur.start, today)
            if t >= 1:
                r = round(t)
                if abs(r - t) <= 0.45:
                    add("true", "tenure", f"Hi {first}, {r} years at {co} is a great run. Open to a chat?", "allow", f"tenure {t:.2f}y")
                    add("true", "tenure_alt", f"Hi {first}, you've been at {co} for {r} years now, impressive.", "allow", f"tenure {t:.2f}y")
            add("true", "since_year", f"Hi {first}, you've been with {co} since {cur.start.year}, so you know the space.", "allow",
                f"start {cur.start.isoformat()}")
            # subtle / false tenure
            add("false", "tenure_plus3", f"Hi {first}, congrats on {_fmt(round(t) + 3)} years at {co}!", "block", f"tenure {t:.2f}y")
            add("subtle", "tenure_plus1_5", f"Hi {first}, congrats on {_fmt(round(t + 1.5, 1))} years at {co}!", "block", f"tenure {t:.2f}y")
            add("subtle", "tenure_alt_plus2", f"Hi {first}, you've been at {co} for {_fmt(round(t) + 2)} years now, impressive.", "block",
                f"tenure {t:.2f}y")
            add("subtle", "since_year_minus2", f"Hi {first}, you've been with {co} since {cur.start.year - 2}, so you know the space.",
                "block", f"start {cur.start.isoformat()}")
        city = _city(pr)
        if city:
            add("true", "city", f"Hi {first}, you're based in {city}, right? We have an office there.", "allow", f"location {pr.location}")
            alias = CITY_ALIASES.get(city.lower())
            if alias:
                add("true", "city_alias", f"Hi {first}, you're based in {alias}, right? We have an office there.", "allow",
                    f"location {pr.location} (alias)")
            wrong = next(c for c in rng.sample(CITIES, len(CITIES)) if c.lower() not in pr.location.lower()
                         and CITY_ALIASES.get(c.lower(), "").lower() not in pr.location.lower())
            wrong_city = wrong
            add("false", "city_wrong", f"Hi {first}, you're based in {wrong}, right? We have an office there.", "block",
                f"location {pr.location}")
            near = NEARBY.get(city.lower())
            if near and near.lower() not in pr.location.lower():
                add("subtle", "city_nearby", f"Hi {first}, you're based in {near}, right? We have an office there.", "block",
                    f"location {pr.location}")
        starts = [j.start for j in pr.current + pr.past if j.start]
        if starts:
            e = _yrs(min(starts), today)
            if e >= 2:
                add("true", "experience", f"Hi {first}, with {math.floor(e)} years of experience you'd be a great fit.", "allow",
                    f"experience {e:.1f}y")
            add("false", "experience_plus6", f"Hi {first}, with {math.floor(e) + 6} years of experience you'd be a great fit.", "block",
                f"experience {e:.1f}y")

        # paraphrase: held-out wording the rule extractor was NOT tuned on (Gemini's job; offline gaps show here)
        if cur.start:
            t = _yrs(cur.start, today)
            words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
            wrong = round(t) + 3
            if wrong < len(words):
                add("paraphrase", "tenure_words_false", f"Hi {first}, {words[wrong].title()} years at {co}, what a journey!", "block",
                    f"tenure {t:.2f}y")
            add("paraphrase", "tenure_phrase_false", f"Hi {first}, it's been over {round(t) + 3} years since you joined {co}, right?",
                "block", f"tenure {t:.2f}y")
            add("paraphrase", "joined_year_false", f"Hi {first}, ever since you joined {co} back in {cur.start.year - 3}, the team has grown a lot.",
                "block", f"start {cur.start.isoformat()}")
            add("paraphrase", "joined_year_true", f"Hi {first}, ever since you joined {co} back in {cur.start.year}, the team has grown a lot.",
                "allow", f"start {cur.start.isoformat()}")
        if cur.title and seniority_rank(cur.title) < 4 and seniority_rank(cur.seniority_level or "") < 4:
            add("paraphrase", "title_phrase_false", f"Hi {first}, leading engineering as {co}'s Director of Engineering must keep you busy.",
                "block", f"title {cur.title}")
        if cur.title:
            add("paraphrase", "title_phrase_true", f"Hi {first}, your role as {cur.title} at {co} lines up well with what we need.",
                "allow", f"title {cur.title}")
        if past:
            add("paraphrase", "stale_phrase", f"Hi {first}, hope things are going well over at {past.company}!", "block",
                f"left {past.company} {past.end}")
        if city:
            add("paraphrase", "city_phrase_false", f"Hi {first}, since you live in {wrong_city}, the commute to our office is short.",
                "block", f"location {pr.location}")

        # sender facts: claims about the SENDER, not the recipient; must not block
        add("sender", "sender_intro", f"Hi {first}, I'm the Head of Talent at Grewon, founded in 2019. We're hiring senior engineers.",
            "allow", "facts about the sender")
        add("sender", "sender_team_you", f"Hi {first}, you'd be joining a 40-person team that has grown 3x in 2 years.", "allow",
            "facts about the sender's team")
        add("sender", "sender_role_you", f"Hi {first}, we think you'd make a great Senior Engineer on our platform team.", "allow",
            "a pitch, not a claim")
        add("sender", "sender_office_you", f"Hi {first}, our office is in Bengaluru, and you could work from there or remotely.", "allow",
            "facts about the sender")

        # false employer / title
        add("false", "employer_other", f"Hi {first}, your work at {other} caught our eye. Open to a chat?", "block",
            f"works at {', '.join(concurrent)}, not {other}")
        if cur.title and seniority_rank(cur.title) < 4 and seniority_rank(cur.seniority_level or "") < 4:
            add("false", "title_head", f"Hi {first}, as the Head of Engineering at {co} you'd find this interesting.", "block",
                f"title {cur.title}")
        if cur.title and seniority_rank(cur.title) < 2 and seniority_rank(cur.seniority_level or "") < 2:
            add("subtle", "title_senior", f"Hi {first}, as a Senior {cur.title} at {co} you'd find this interesting.", "block",
                f"title {cur.title}")

        # stale
        if past:
            add("stale", "past_employer_claim", f"Hi {first}, your work at {past.company} caught our eye. Open to a chat?", "block",
                f"left {past.company} {past.end}")
            add("stale", "past_employer_recipient", f"Hi {first}, open to a quick chat about a new role?", "block",
                f"left {past.company} {past.end}", to={**to, "company": past.company})
            if past.title:
                add("stale", "past_title", f"Hi {first}, as a {past.title} at {past.company} you'd find this interesting.", "block",
                    f"was {past.title} at {past.company}, ended {past.end}")
    return cases


def tamper_cases(people: dict[str, dict]) -> list[Case]:
    out = []
    picks = list(people.items())[:4]
    kinds = [
        ("altered_body", "outreach.hiring", "authorised_founder"), ("whitespace", "outreach.hiring", "authorised_founder"),
        ("other_agent_sig", "outreach.hiring", "authorised_founder"), ("edited_passport", "outreach.hiring", "authorised_founder"),
        ("expired", "outreach.hiring", "authorised_founder"), ("revoked", "outreach.hiring", "authorised_founder"),
        ("scope_missing", "outreach.sales", "authorised_founder"), ("sponsor_left", "outreach.hiring", "sponsor_left"),
        ("junior_sponsor_contract", "contract.sign", "junior_sponsor"), ("empty_signature", "outreach.hiring", "authorised_founder"),
    ]
    for url, rec in picks:
        pr = load_person(rec)
        if not pr.current:
            continue
        to = {"name": pr.name, "profile_url": pr.profile_url, "company": pr.current[0].company}
        body = f"Hi {pr.name.split()[0]}, your work at {pr.current[0].company} caught our eye."
        for k, scope, sp in kinds:
            out.append(Case(id=f"tamper-{k}-{norm_url(url).rsplit('/', 1)[-1]}", category="tamper", template=k, person=url, name=pr.name,
                            to=to, body=body, expect="block", why=k, tamper=k, scope=scope, sponsor=sp))
        out.append(Case(id=f"tamper-unknown-{norm_url(url).rsplit('/', 1)[-1]}", category="tamper", template="unknown_recipient",
                        person=url, name=pr.name, to={**to, "profile_url": "https://www.linkedin.com/in/no-such-person-xyz"},
                        body=body, expect="block", why="no record"))
        out.append(Case(id=f"tamper-nocompany-{norm_url(url).rsplit('/', 1)[-1]}", category="tamper", template="no_company",
                        person=url, name=pr.name, to={**to, "company": ""}, body=body, expect="block", why="no company"))
    return out


# ---- run --------------------------------------------------------------------

class EvalGraph(Graph):
    """Serves the eval's records by URL (so labels and the guard read the same data), else the normal path."""

    def __init__(self, people: dict[str, dict], client=None, mode: str | None = None):
        super().__init__(client, mode=mode)
        self.people = people

    async def person(self, profile_url: str):
        return self.people.get(norm_url(profile_url)) or await super().person(profile_url)


async def run_case(c: Case, graph: Graph, today: date, sem: asyncio.Semaphore) -> None:
    sc = SPONSORS[c.sponsor]
    scopes = [c.scope] if c.tamper not in ("scope_missing",) else ["outreach.hiring"]
    p, key = issue_passport("Sourced", "AI recruiter", Sponsor(**sc["sponsor"]), scopes, days=-1 if c.tamper == "expired" else 30)
    signed_body, sig = c.body, None
    if c.tamper == "altered_body":
        signed_body = c.body.replace("caught our eye", "is great")
    elif c.tamper == "whitespace":
        signed_body = c.body + " "
    elif c.tamper == "other_agent_sig":
        p2, k2 = issue_passport("Other", "AI SDR", Sponsor(**sc["sponsor"]), scopes)
        sig = sign_message(p2, k2, c.body)
    elif c.tamper == "edited_passport":
        p.scopes = list(p.scopes) + ["payment.send"]
    elif c.tamper == "revoked":
        revoke(p.agent_id, "eval")
    elif c.tamper == "empty_signature":
        sig = ""
    if sig is None:
        sig = sign_message(p, key, signed_body)
    async with sem:
        t0 = time.perf_counter()
        v = await check_send(p, sig, c.to, c.body, c.scope, today=today, graph=graph)
        c.ms = int((time.perf_counter() - t0) * 1000)
    c.got = v.decision
    c.failing = [f"{k.name}:{k.status}" for k in v.checks if k.status != "pass"]
    c.checks = [{"name": k.name, "status": k.status, "detail": k.detail} for k in v.checks if k.id.startswith("g")]


def report(cases: list[Case], meta: dict) -> str:
    def rate(xs: list[Case], want: str) -> str:
        pool = [c for c in xs if c.expect == want]
        bad = [c for c in pool if c.got != want]
        return f"{len(bad)}/{len(pool)} ({100 * len(bad) / len(pool):.1f}%)" if pool else "-"

    lines = [f"# Send Guard eval ({meta['when']})", "",
             f"People: {meta['people']}  Cases: {len(cases)}  LLM_MODE={meta['llm']}  CRUSTDATA_MODE={meta['crust']}  "
             f"median {sorted(c.ms for c in cases)[len(cases) // 2]} ms/case", "",
             f"**False-allow** (should block, allowed): {rate(cases, 'block')}  ",
             f"**False-block** (should allow, blocked): {rate(cases, 'allow')}", "",
             "| Category | Cases | False-allow | False-block |", "|---|---|---|---|"]
    for cat in ("true", "sender", "false", "stale", "subtle", "tamper", "paraphrase"):
        xs = [c for c in cases if c.category == cat]
        if xs:
            lines.append(f"| {cat} | {len(xs)} | {rate(xs, 'block')} | {rate(xs, 'allow')} |")
    lines += ["", "| Template | Expect | Cases | Wrong |", "|---|---|---|---|"]
    by_t = defaultdict(list)
    for c in cases:
        by_t[(c.template, c.expect)].append(c)
    for (t, e), xs in sorted(by_t.items()):
        wrong = sum(c.got != c.expect for c in xs)
        lines.append(f"| {t} | {e} | {len(xs)} | {wrong}{' ⚠' if wrong else ''} |")
    wrong = [c for c in cases if c.got != c.expect]
    lines += ["", f"## Mismatches ({len(wrong)})", ""]
    for c in wrong:
        lines.append(f"- **{c.id}** [{c.category}/{c.template}] expect {c.expect}, got {c.got}. Label: {c.why}  ")
        lines.append(f"  Draft: \"{c.body}\" to {c.to.get('company')!r}  ")
        lines.append(f"  Not passing: {', '.join(c.failing) or 'none'}  ")
        for k in c.checks:
            lines.append(f"  - {k['name']} {k['status']}: {k['detail']}")
    return "\n".join(lines) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", type=int, default=0, help="also pull N people live via person_search + enrich")
    ap.add_argument("--max-people", type=int, default=0)
    ap.add_argument("--today", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "evals_out_guard.md"))
    ap.add_argument("--json", default=None, help="also dump every case as JSON")
    a = ap.parse_args()

    today = date.fromisoformat(a.today) if a.today else date.today()
    mode = os.getenv("CRUSTDATA_MODE", "replay")
    client = None
    if mode != "replay" or a.live:
        from app.crustdata.client import CrustdataClient
        client = CrustdataClient(mode=mode if mode != "replay" else "cache")
    people = fixture_people()
    if a.live and client:
        got = await live_people(client, a.live)
        print(f"live: {len(got)} people enriched")
        people.update(got)
    if a.max_people:
        people = dict(list(people.items())[: a.max_people])

    rng = random.Random(a.seed)
    cases = make_cases(people, today, rng) + tamper_cases(people)
    graph = EvalGraph(people, client, mode="replay" if client is None else None)
    sem = asyncio.Semaphore(a.concurrency)
    t0 = time.perf_counter()
    await asyncio.gather(*(run_case(c, graph, today, sem) for c in cases))
    print(f"{len(cases)} cases over {len(people)} people in {time.perf_counter() - t0:.1f}s")

    md = report(cases, {"when": time.strftime("%Y-%m-%d %H:%M"), "people": len(people), "llm": os.getenv("LLM_MODE", "live"), "crust": mode})
    Path(a.out).write_text(md)
    if a.json:
        Path(a.json).write_text(json.dumps([c.__dict__ for c in cases], indent=1, default=str))
    head = md.split("| Template")[0]
    print(head)
    print(f"Full report: {a.out}")
    if client:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
