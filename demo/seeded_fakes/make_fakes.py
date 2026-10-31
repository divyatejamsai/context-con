"""Build seeded-fake resumes from real Crustdata Person Enrich fixtures.

Each output is the real enrich record plus a person["claimed"] block (what the "candidate" says
on their resume), which is exactly what WS3's verify_candidate() checks. Most claimed facts are
true; 1-2 are planted lies that the graph can disprove. answer_key.json says which.

Usage (from repo root):
  python demo/seeded_fakes/make_fakes.py fixtures/crustdata/person_enrich_*.json \
      [--companies fixtures/crustdata/companies.json] --out demo/seeded_fakes/out
  python demo/seeded_fakes/check_fakes.py demo/seeded_fakes/out     # did the verifier catch them?

--companies is optional: a JSON map {company_id: company_enrich_response} (or a list of responses).
Without it the company_stage lie is never planted, since we can't know the true stage.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_profile_module():
    # Reuse WS3's parser so the fakes are built from the same fields the verifier reads.
    for p in (ROOT / "backend/app/verify/profile.py",
              Path("/mnt/project-files/yc-hackathon/ws3-verify/backend/app/verify/profile.py")):
        if p.exists():
            spec = importlib.util.spec_from_file_location("ws3_profile", p)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["ws3_profile"] = mod  # dataclasses need the module registered
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("backend/app/verify/profile.py not found (WS3)")


P = _load_profile_module()

FAMOUS = ["Stripe", "Google", "Netflix", "OpenAI", "Meta", "Airbnb"]
FAR_CITIES = ["London, United Kingdom", "Singapore", "San Francisco, USA", "Berlin, Germany", "Dubai, UAE"]
# Planting order: the first profile (the demo one) gets the freshness lie + an inflated title.
LIE_ORDER = ["stale_current_job", "inflated_title", "stretched_tenure", "inflated_experience",
             "fake_employer", "wrong_location", "company_stage"]
EMPLOYER_LIES = {"stale_current_job", "fake_employer"}


def unwrap(raw):
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    for key in ("data", "person", "profile", "result", "results"):
        if isinstance(raw, dict) and isinstance(raw.get(key), (dict, list)) and not raw.get("name"):
            return unwrap(raw[key])
    return raw


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "person"


def inflate(title: str) -> str:
    base = re.sub(r"\b(senior|sr\.?|junior|jr\.?|lead|staff|principal)\b", "", title, flags=re.I).strip() or title
    rank = P.seniority_rank(title)
    if rank < 3:
        return f"Principal {base}"
    return "VP Engineering" if rank < 4 else "Chief Technology Officer"


def load_companies(path: str | None) -> dict[str, dict]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, list):
        out = {}
        for c in raw:
            cid, _ = P.first(c, "company_id", "id", "crustdata_company_id")
            if cid is not None:
                out[str(cid)] = c
        return out
    return {str(k): v for k, v in raw.items()}


def build(person: dict, companies: dict[str, dict], offset: int, today: date):
    pr = P.load_person(person)
    cur = pr.current[0] if pr.current else None
    starts = [j.start for j in pr.current + pr.past if j.start]
    total_yrs = (today - min(starts)).days / 365.25 if starts else None
    cf = P.load_company(companies.get(str(cur.company_id))) if cur and cur.company_id is not None else None
    bucket = P.stage_bucket(cf)
    known = {P.company_key(j.company) for j in pr.current + pr.past}

    # True resume first: everything matches the graph.
    claimed: dict = {}
    if cur:
        claimed["employer"] = cur.company
        if cur.title:
            claimed["title"] = cur.title
        if cur.start:
            claimed["start_date"] = cur.start.isoformat()
    if pr.location:
        claimed["location"] = pr.location
    if total_yrs is not None:
        claimed["years_experience"] = math.floor(total_yrs)
    if pr.skills:
        claimed["skills"] = pr.skills[:3]
    if cf and cf.stage:
        claimed["company_stage"] = cf.stage

    def plan(kind):  # -> (key, lie_value, truth) or None if this profile can't carry the lie
        if kind == "stale_current_job" and cur and pr.past:
            return "employer", pr.past[0].company, f"current employer is {cur.company} ({cur.path})"
        if kind == "fake_employer" and cur:
            fake = next((c for c in FAMOUS if P.company_key(c) not in known), None)
            return fake and ("employer", fake, f"{fake} is not in the employment record")
        if kind == "inflated_title" and cur and cur.title:
            return "title", inflate(cur.title), f"record title is '{cur.title}' ({cur.path}.title)"
        if kind == "stretched_tenure" and cur and cur.start:
            fake = cur.start.replace(year=cur.start.year - 2).isoformat()
            return "start_date", fake, f"record start date is {cur.start.isoformat()} ({cur.path}.start_date)"
        if kind == "inflated_experience" and total_yrs is not None:
            return "years_experience", math.floor(total_yrs) + 5, f"earliest role starts {min(starts).isoformat()} (~{total_yrs:.1f} yrs)"
        if kind == "wrong_location" and pr.location:
            city = next(c for c in FAR_CITIES if not (P.tokens(c) & P.tokens(pr.location)))
            return "location", city, f"record location is {pr.location}"
        if kind == "company_stage" and bucket in ("growth", "late", "public", "enterprise"):
            return "company_stage", "Seed-stage startup", f"company record says {cf.stage or bucket}"
        return None

    order = LIE_ORDER[offset % len(LIE_ORDER):] + LIE_ORDER[:offset % len(LIE_ORDER)]
    lies = []
    for kind in order:
        if len(lies) == 2:
            break
        kinds = {l["type"] for l in lies}
        if kind in EMPLOYER_LIES and kinds & EMPLOYER_LIES:
            continue
        if {kind} | kinds >= {"stretched_tenure"} and (kinds | {kind}) & EMPLOYER_LIES:
            continue  # tenure lie reads oddly against a different employer
        p = plan(kind)
        if p:
            key, value, truth = p
            lies.append({"type": kind, "key": key, "claimed": value, "truth": truth})
            claimed[key] = value
    claimed["_source"] = "seeded resume (demo/seeded_fakes)"
    return pr, claimed, lies


def render(name: str, url: str | None, claimed: dict) -> str:
    lines = [name, url or "", ""]
    if claimed.get("title") or claimed.get("employer"):
        lines.append(f"{claimed.get('title', '')} at {claimed.get('employer', '')}".strip())
    if claimed.get("start_date"):
        lines.append(f"In current role since {claimed['start_date']}")
    if claimed.get("years_experience") is not None:
        lines.append(f"{claimed['years_experience']} years of experience")
    if claimed.get("location"):
        lines.append(f"Based in {claimed['location']}")
    if claimed.get("company_stage"):
        lines.append(f"Current company: {claimed['company_stage']}")
    if claimed.get("skills"):
        lines.append("Skills: " + ", ".join(claimed["skills"]))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixtures", nargs="+")
    ap.add_argument("--companies")
    ap.add_argument("--out", default=str(ROOT / "demo/seeded_fakes/out"))
    ap.add_argument("--today", help="YYYY-MM-DD, defaults to today")
    args = ap.parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    companies = load_companies(args.companies)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key, n = [], 0
    for path in args.fixtures:
        person = unwrap(json.loads(Path(path).read_text()))
        if not isinstance(person, dict) or not P.first(person, "name", "basic_profile.name", "full_name")[0]:
            print(f"skip {path}: no person found")
            continue
        pr, claimed, lies = build(person, companies, n * 2, today)
        if not lies:
            print(f"skip {path}: not enough graph data to plant a checkable lie")
            continue
        n += 1
        slug = slugify(pr.name or Path(path).stem)
        fake = {k: v for k, v in person.items() if k != "claimed"} | {"claimed": claimed}
        (out / f"{slug}.person.json").write_text(json.dumps(fake, indent=2, default=str))
        (out / f"{slug}.resume.txt").write_text(render(pr.name, pr.profile_url, claimed))
        key.append({"name": pr.name, "file": f"{slug}.person.json", "lies": lies})
        print(f"{slug}: planted {', '.join(l['type'] for l in lies)}")
    (out / "answer_key.json").write_text(json.dumps(key, indent=2))
    print(f"{n} fakes -> {out}")


if __name__ == "__main__":
    main()
