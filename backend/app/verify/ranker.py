"""WS3 ranker: score a verified candidate against the brief. Every reason cites claim ids.

Scoring is deterministic so the demo is stable and every point is traceable to a claim:
  role fit 30, skills 25, location 15, company preference 15, experience 15.
A factor the brief doesn't mention is dropped and the rest are rescaled to a base of 90.
Credit is graded (title closeness, seniority gap, how strongly each skill is evidenced, years vs need);
unverifiable earns half, contradicted none plus a penalty. Up to +10 bonus for strong evidence:
years in matching roles, domain experience in the current role and from several sources, stable tenure.
Set RANK_USE_LLM=1 to let the LLM rewrite reason text (claim ids are kept and validated).
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date

from pydantic import BaseModel

from ..schemas import Claim, Criteria, Reason

from .profile import domain_terms, load_person, norm, same_company, seniority_rank, title_similarity, tokens

log = logging.getLogger(__name__)

BASE_CAP = 90   # the factor score tops out here; bonuses for strong evidence add up to MAX_BONUS
MAX_BONUS = 10
CONTRADICTION_PENALTY = 12
MAX_PENALTY = 36
CREDIT = {"verified": 1.0, "unverifiable": 0.5, "contradicted": 0.0}

_STARTUP_WORDS = {"startup", "start up", "early stage", "early-stage", "seed", "series a", "series b", "ex startup", "ex-startup"}
_STAGE_PREF = {
    "seed": {"seed"}, "early": {"early", "seed"}, "growth": {"growth", "early"}, "late": {"late", "growth"},
    "public": {"public", "enterprise"}, "enterprise": {"enterprise", "public", "late"}, "big tech": {"enterprise", "public"},
    "mnc": {"enterprise", "public"}, "faang": {"enterprise", "public"},
}


def _kind(c: Claim) -> str:
    t = c.claim
    if t.startswith("Works at") or t == "Current employer":
        return "employer"
    if t.startswith("Title:"):
        return "title"
    if t.startswith("Skill:"):
        return "skill"
    if t.startswith("Skills not evidenced"):
        return "skills_missing"
    if t.startswith("Based in") or t == "Location":
        return "location"
    if t.endswith("of experience"):
        return "experience"
    if (t.startswith("At ") and " since " in t) or (" yrs at " in t) or t.startswith("Tenure at"):
        return "tenure"
    if c.source.endpoint.startswith("company") or "stage" in t or "employees" in t:
        return "company"
    return "other"


def _by_kind(claims: list[Claim]) -> dict[str, list[Claim]]:
    out: dict[str, list[Claim]] = {}
    for c in claims:
        out.setdefault(_kind(c), []).append(c)
    return out


def _years_in(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*yrs", text)
    return float(m.group(1)) if m else None


class _Factor:
    def __init__(self, name: str, weight: float):
        self.name, self.weight, self.earned, self.reasons = name, weight, 0.0, []

    def add(self, credit: float, text: str, claims: list[Claim]):
        self.earned = max(self.earned, self.weight * credit)
        ids = [c.id for c in claims]
        if ids:
            self.reasons.append((credit, Reason(text=text, claim_ids=ids)))


_LEVEL_WORDS = {"senior", "sr", "junior", "jr", "staff", "principal", "lead", "head", "vp", "vice", "president",
                "director", "chief", "associate", "intern", "trainee", "i", "ii", "iii", "iv", "1", "2", "3"}


def _core(title: str) -> str:
    core = " ".join(t for t in norm(re.sub(r"\([^)]*\)", " ", title)).split() if t not in _LEVEL_WORDS)
    return core or title


def _role_fit(k: dict[str, list[Claim]], criteria: Criteria) -> _Factor:
    f = _Factor("role", 30)
    titles = k.get("title", [])
    if not titles:
        return f
    c = titles[0]
    title = c.claim.removeprefix("Title:").strip()
    targets = [t for t in [criteria.role, *criteria.title_variants] if t]
    # Compare the function of the role ("backend engineer"); seniority is scored separately below.
    best = max((title_similarity(_core(title), _core(t)) for t in targets), default=0.0)
    best_t = max(targets, key=lambda t: title_similarity(_core(title), _core(t))) if targets else criteria.role
    # Graded: an exact title earns 1.0, a near title ~0.8, a loose one ~0.5.
    sim_credit = min(1.0, 0.3 + best * 0.85) if best > 0 else 0.0
    junior_for_brief = False
    if criteria.seniority:
        want, have = seniority_rank(criteria.seniority + " x"), seniority_rank(title)
        gap = have - want
        sim_credit *= {0: 1.0, 1: 0.95, 2: 0.85}.get(gap, 0.75) if gap >= 0 else {-1: 0.6}.get(gap, 0.35)
        junior_for_brief = gap < 0
    credit = sim_credit * CREDIT[c.status]
    if junior_for_brief and best >= 0.34 and c.status != "contradicted":
        f.add(credit, f"{title} fits the role but is below the {criteria.seniority} level asked for", [c])
        return f
    if c.status == "contradicted":
        f.add(0, f"Title claim '{title}' is contradicted by the record", [c])
    elif credit >= 0.95:
        f.add(credit, f"{title} is a strong match for the '{best_t}' role", [c])
    elif credit >= 0.7:
        f.add(credit, f"{title} matches the '{best_t}' role", [c])
    elif credit > 0:
        f.add(credit, f"{title} is a partial match for '{best_t}'", [c])
    else:
        f.add(0, f"{title} doesn't match the '{criteria.role}' role", [c])
    return f


def _skills(k: dict[str, list[Claim]], criteria: Criteria) -> _Factor | None:
    wanted = [s for s in criteria.skills + [m for m in criteria.must_haves if len(m.split()) <= 3] if s]
    if not wanted:
        return None
    f = _Factor("skills", 25)
    hits = [c for c in k.get("skill", []) if c.status == "verified"]
    hit_names = {norm(c.claim.removeprefix("Skill:")) for c in hits}
    n_hit = sum(1 for s in dict.fromkeys(norm(w) for w in wanted) if s in hit_names)
    total = len(set(norm(w) for w in wanted))
    strength = {norm(c.claim.removeprefix("Skill:")): evidence_strength(c) for c in hits}
    credit = sum(strength.get(s, 0) for s in dict.fromkeys(norm(w) for w in wanted)) / total if total else 0
    if hits:
        names = ", ".join(c.claim.removeprefix("Skill:").strip() for c in hits[:4])
        f.add(credit, f"Has {n_hit}/{total} required skills: {names}", hits)
    miss = k.get("skills_missing", [])
    if miss:
        f.add(credit, miss[0].claim.replace("Skills not evidenced", "No evidence for"), miss)
    f.earned = f.weight * credit
    return f


def _location(k: dict[str, list[Claim]], criteria: Criteria) -> _Factor | None:
    locs = [l for l in criteria.locations if l]
    if not locs:
        return None
    f = _Factor("location", 15)
    cl = k.get("location", [])
    if not cl:
        return f
    c = cl[0]
    if c.status == "unverifiable" and c.claim == "Location":
        f.add(0.5, "Location unknown in the graph", [c])
        return f
    if any("remote" in norm(l) for l in locs):
        f.add(CREDIT[c.status] if c.status != "contradicted" else 0.5, "Brief allows remote", [c])
        return f
    have = tokens(c.claim.removeprefix("Based in"))
    alias = {"bengaluru": "bangalore", "bangalore": "bengaluru", "gurgaon": "gurugram", "gurugram": "gurgaon",
             "bombay": "mumbai", "mumbai": "bombay", "sf": "san francisco", "nyc": "new york"}
    have |= {alias[t] for t in have if t in alias}
    match = next((l for l in locs if tokens(l) & have or tokens(l) <= have), None)
    if match and c.status != "contradicted":
        f.add(CREDIT[c.status], f"Located in {match}, as the brief asks", [c])
    elif c.status == "contradicted":
        f.add(0, f"Stated location is contradicted: {c.evidence}", [c])
    else:
        f.add(0, f"{c.claim}, outside {', '.join(locs)}", [c])
    return f


def _company(k: dict[str, list[Claim]], criteria: Criteria, person: dict) -> _Factor | None:
    prefs = [p for p in criteria.company_preferences if p]
    if not prefs:
        return None
    f = _Factor("company", 15)
    comp = k.get("company", [])
    emp = [c for c in k.get("employer", []) if c.status != "contradicted"]
    for p in prefs:
        pn = norm(p)
        # Named company preference, e.g. "ex-Razorpay": look at employer claim and employment history.
        named = re.sub(r"^(ex|former|from)\s+", "", pn)
        if named and named not in _STARTUP_WORDS and named not in _STAGE_PREF:
            for c in emp:
                if same_company(named, c.claim.removeprefix("Works at")):
                    f.add(CREDIT[c.status], f"Currently at {named.title()}, a preferred company", [c])
            names = [j.company for j in load_person(person).past]
            if any(same_company(named, n) for n in names if n) and emp:
                f.add(0.8, f"Previously worked at {named.title()}", emp[:1])
        for c in comp:
            m = re.search(r"\((\w+) stage\)", c.claim)
            bucket = m.group(1) if m else None
            text = norm(c.claim)
            if any(w in pn for w in _STARTUP_WORDS) and bucket in ("seed", "early", "growth"):
                f.add(CREDIT[c.status], f"Current company is a startup ({bucket} stage), matching '{p}'", [c])
            elif bucket and any(key in pn and bucket in ok for key, ok in _STAGE_PREF.items()):
                f.add(CREDIT[c.status], f"Company stage ({bucket}) fits '{p}'", [c])
            elif named and named in text:
                f.add(CREDIT[c.status], f"Company matches '{p}'", [c])
    if not f.reasons and comp:
        f.add(0, f"Company profile doesn't match preference: {', '.join(prefs)}", comp[:1])
    return f


def _experience(k: dict[str, list[Claim]], criteria: Criteria) -> _Factor | None:
    if not criteria.seniority:
        return None
    f = _Factor("experience", 15)
    ex = k.get("experience", [])
    if not ex:
        return f
    c = ex[0]
    yrs = _years_in(c.claim)
    if c.status == "contradicted":
        f.add(0, f"Experience claim is inflated: {c.evidence}", [c])
        return f
    if yrs is None:
        return f
    s = norm(criteria.seniority)
    need = 8 if any(w in s for w in ("staff", "principal", "lead", "head", "director")) else 5 if "senior" in s else 0 if any(
        w in s for w in ("junior", "entry", "intern", "fresher")) else 2
    if "junior" in s or "entry" in s or "fresher" in s:
        credit = 1.0 if yrs <= 3 else max(0.3, 1 - (yrs - 3) * 0.15)
    else:
        credit = min(1.0, 0.1 + 0.9 * yrs / need) if need else 1.0
    f.add(credit * CREDIT[c.status], f"{_fmt(yrs)} of experience for a {criteria.seniority} role", [c])
    return f


def _fmt(y: float) -> str:
    return f"{y:g} yrs"


def evidence_strength(c: Claim) -> float:
    """How strongly a verified skill claim is evidenced: listed skill > title > current employer > past employer."""
    fld, ev = c.source.field or "", c.evidence
    if "skills" in fld:
        base = 1.0
    elif fld.endswith(".title") or "headline" in fld:
        base = 0.9
    elif "taxonomy" in fld or (".current[" in fld) or ev.startswith("current employer"):
        base = 0.85
    elif fld.endswith(".name"):
        base = 0.7
    elif "description" in fld:
        base = 0.55
    else:
        base = 0.65  # past employer industry
    extra = ev.count("; ") if "; also:" in ev else 0
    return min(1.0, base + 0.05 * extra)


def _bonuses(k: dict[str, list[Claim]], criteria: Criteria, person: dict) -> list[tuple[float, Reason]]:
    """Up to +10 on top of a base capped at 90, for unusually strong evidence."""
    out: list[tuple[float, Reason]] = []
    pr = load_person(person)
    titles = [c for c in k.get("title", []) if c.status == "verified"]
    exp = [c for c in k.get("experience", []) if c.status == "verified"]
    tenure = [c for c in k.get("tenure", []) if c.status == "verified"]
    targets = [t for t in [criteria.role, *criteria.title_variants] if t]

    # Years in roles that match the brief, across current and past jobs.
    if targets and (titles or exp):
        today = date.today()
        spans = sorted((j.start, j.end or today) for j in pr.current + pr.past
                       if j.start and j.title and max(title_similarity(_core(j.title), _core(t)) for t in targets) >= 0.34)
        rel, cur_end = 0.0, None  # merge overlapping jobs so concurrent roles aren't double counted
        for a, b in spans:
            if cur_end and a < cur_end:
                a = cur_end
            if b > a:
                rel += (b - a).days / 365.25
                cur_end = b if not cur_end or b > cur_end else cur_end
        if rel >= 1:
            out.append((min(4.0, rel / 2), Reason(text=f"{rel:.0f} yrs in {_core(criteria.role) if criteria.role else 'matching'} roles", claim_ids=[c.id for c in (titles + exp)[:2]])))

    # Domain depth and recency, from verified domain-type skill claims.
    for c in k.get("skill", []):
        name = c.claim.removeprefix("Skill:").strip()
        if c.status != "verified" or not domain_terms(name):
            continue
        sources = 1 + c.evidence.count("; ") if "; also:" in c.evidence else 1
        current = "current employer" in c.evidence or ".current[" in (c.source.field or "")
        pts = (2.0 if current else 0.5) + min(2.0, sources - 1)
        where = "in the current role" if current else "from a past role only"
        out.append((pts, Reason(text=f"{name} experience {where}, backed by {sources} source{'s' if sources > 1 else ''}", claim_ids=[c.id])))
        break

    # Stage fit and stability.
    if tenure:
        y = _years_in(tenure[0].claim)
        if y is not None and 2 <= y <= 8:
            out.append((1.0, Reason(text=f"Stable tenure: {_fmt(round(y, 1))} in the current role", claim_ids=[tenure[0].id])))
    return out


class _LLMReasons(BaseModel):
    reasons: list[Reason]


async def _llm_polish(reasons: list[Reason], claims: list[Claim], criteria: Criteria) -> list[Reason]:
    from .. import llm  # local import keeps tests free of LLM deps

    valid = {c.id for c in claims}
    prompt = (
        "Rewrite these candidate ranking reasons for a recruiter: short, specific, no hype. "
        "Keep the same number of reasons, same order, and the exact same claim_ids for each. Do not add facts.\n"
        f"Role: {criteria.role}\nReasons: {[r.model_dump() for r in reasons]}\n"
        f"Claims: {[{'id': c.id, 'claim': c.claim, 'status': c.status} for c in claims]}"
    )
    try:
        res = await llm.generate_json(prompt, _LLMReasons, tier="smart")
    except Exception as e:
        log.warning("rank: llm polish failed, using rule text: %s", e)
        return reasons
    new = getattr(res, "reasons", None) or []
    if len(new) != len(reasons):
        return reasons
    out = []
    for old, r in zip(reasons, new):
        ids = [i for i in r.claim_ids if i in valid] or old.claim_ids
        out.append(Reason(text=r.text.strip() or old.text, claim_ids=ids))
    return out


async def rank_candidate(person: dict, claims: list[Claim], criteria: Criteria) -> tuple[int, list[Reason]]:
    """Return (score 0-100, reasons). Each reason cites at least one existing claim id."""
    person = person or {}
    k = _by_kind(claims)
    factors = [f for f in (
        _role_fit(k, criteria), _skills(k, criteria), _location(k, criteria),
        _company(k, criteria, person), _experience(k, criteria),
    ) if f is not None]
    total_w = sum(f.weight for f in factors) or 1
    base = sum(f.earned for f in factors) / total_w * BASE_CAP
    bonuses = _bonuses(k, criteria, person)
    bonus = min(MAX_BONUS, sum(p for p, _ in bonuses))

    contradicted = [c for c in claims if c.status == "contradicted"]
    # A stale headline is a freshness signal, not a lie: half penalty and softer wording.
    stale = {c.id for c in contradicted if c.evidence.startswith("profile headline")}
    penalty = min(MAX_PENALTY, sum(CONTRADICTION_PENALTY / (2 if c.id in stale else 1) for c in contradicted))
    score = int(round(max(0, min(100, base + bonus - penalty))))

    scored: list[tuple[float, Reason]] = []
    for c in contradicted:
        text = (f"Profile is stale: {c.evidence}" if c.id in stale
                else f"Red flag: '{c.claim}' is contradicted ({c.evidence})")
        scored.append((-2.0, Reason(text=text, claim_ids=[c.id])))
    for f in factors:
        for credit, r in f.reasons:
            impact = f.weight * (credit - 0.5)
            if any(r.claim_ids == s.claim_ids for i, s in scored if i == -2.0):
                continue
            scored.append((impact, r))
    for pts, r in bonuses:
        scored.append((pts, Reason(text=f"+{pts:.0f}: {r.text}" if pts >= 1 else r.text, claim_ids=r.claim_ids)))
    n_ver = sum(c.status == "verified" for c in claims)
    if claims:
        ver = [c.id for c in claims if c.status == "verified"]
        if ver:
            scored.append((-0.1, Reason(text=f"{n_ver} of {len(claims)} claims verified against Crustdata", claim_ids=ver)))

    # Red flags first, then strongest positives, then weaknesses.
    reds = [r for i, r in scored if i == -2.0]
    rest = sorted([(i, r) for i, r in scored if i != -2.0], key=lambda x: -x[0])
    reasons = reds + [r for _, r in rest]
    reasons = [r for r in reasons if r.claim_ids][:8]

    if os.getenv("RANK_USE_LLM") == "1" and reasons:
        reasons = await _llm_polish(reasons, claims, criteria)
    return score, reasons
