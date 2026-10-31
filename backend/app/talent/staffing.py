"""Staff a thousand shifts from applications seeded with fakes.

The pipeline a staffing agency runs every week, with no one at the keyboard:

    1 ingest     applications arrive: name, profile URL, the role and city applied for, what they claim
                 (employer, title, start date, years of experience, where they live) and when they can work
    2 screen     every application is checked against the person's Crustdata record:
                   identity   the profile exists, and the name on the application matches the record's name
                   claims     employer, title, tenure, experience (app/verify/verifier.py, the same verifier the
                              hiring agent and Send Guard use) and home city, each verified / contradicted / unverifiable
                              with the field that decides it
                   fit        the record shows a current or past role in the shift's line of work
                 outcome: cleared, flagged (false claim or identity problem: never staffed) or not_qualified
    3 assign     cleared workers are matched to shifts: same city, same line of work, a day they said they're free,
                 at most one shift a day and their weekly cap. Scarcest shifts are filled first, and work is spread
                 to the least-loaded worker
    4 report     fill rate (overall, by city and role, why the rest stayed open) and, against the answer key the
                 seeding step kept aside, fake-catch precision and recall, recall per lie type, and fakes staffed

Seeding (`seed_applications`) is how we test it: real Crustdata people become applicants, most honest (with the small
mess real forms have: Bangalore vs Bengaluru, a start date a month off), and a share carry one planted lie that the
record can disprove. The screener never sees the answer key.
"""
from __future__ import annotations

import logging
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from ..schemas import Claim, Criteria, Source
from ..verify.profile import load_person, norm, same_company, seniority_rank, title_similarity, tokens
from ..verify.verifier import verify_candidate
from .pool import PoolGraph, all_of, city_filter, fetch_pool, title_filter

log = logging.getLogger(__name__)

# Lines of shift work: search titles (Crustdata current title contains) and the words that make a role count as fit.
ROLE_FAMILIES: dict[str, dict] = {
    "delivery": {"label": "Delivery associate", "titles": ["delivery executive", "delivery associate", "delivery partner", "delivery boy", "rider"],
                 "words": {"delivery", "rider", "courier", "logistics", "dispatch", "last mile", "fleet"}, "hours": (7, 12, 17), "len": 6},
    "warehouse": {"label": "Warehouse associate", "titles": ["warehouse associate", "warehouse executive", "picker", "packer", "inventory associate"],
                  "words": {"warehouse", "picker", "packer", "inventory", "fulfilment", "fulfillment", "store keeper", "storekeeper", "logistics"}, "hours": (6, 14, 22), "len": 8},
    "support": {"label": "Customer support associate", "titles": ["customer support executive", "customer care executive", "customer service associate", "customer support associate"],
                "words": {"customer support", "customer care", "customer service", "call center", "call centre", "telecaller", "bpo", "voice process", "chat support"}, "hours": (9, 13, 18), "len": 8},
    "retail": {"label": "Retail associate", "titles": ["retail sales associate", "store associate", "cashier", "sales associate"],
               "words": {"retail", "store", "cashier", "sales associate", "floor", "showroom"}, "hours": (10, 15), "len": 6},
    "security": {"label": "Security officer", "titles": ["security guard", "security officer", "security supervisor"],
                 "words": {"security"}, "hours": (8, 20), "len": 12},
    "hospitality": {"label": "Hospitality associate", "titles": ["barista", "steward", "waiter", "housekeeping", "front office executive"],
                    "words": {"barista", "steward", "waiter", "housekeeping", "front office", "hospitality", "f&b", "food and beverage", "chef", "cook"}, "hours": (7, 15), "len": 8},
}

CITIES: dict[str, set[str]] = {
    "Bangalore": {"bangalore", "bengaluru"},
    "Mumbai": {"mumbai", "bombay", "navi mumbai", "thane"},
    "Delhi NCR": {"delhi", "new delhi", "gurgaon", "gurugram", "noida", "ghaziabad", "faridabad"},
    "Hyderabad": {"hyderabad", "secunderabad"},
    "Pune": {"pune"},
    "Chennai": {"chennai", "madras"},
}
SEARCH_CITIES = ["Bangalore", "Mumbai", "Delhi", "Gurgaon", "Noida", "Hyderabad", "Pune", "Chennai"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LIE_TYPES = ("stale_current_job", "fake_employer", "inflated_title", "stretched_tenure", "inflated_experience",
             "wrong_location", "identity_mismatch", "ghost_profile")
FAMOUS = ["Amazon", "Flipkart", "Swiggy", "Zomato", "Reliance Retail", "Taj Hotels", "Starbucks", "DMart", "Blinkit", "Zepto"]
OTHER_NAMES = ["Rohit Kumar", "Pooja Sharma", "Amit Singh", "Neha Gupta", "Suresh Reddy", "Kavya Nair", "Imran Khan",
               "Deepa Iyer", "Vikram Patel", "Sneha Joshi", "Arjun Das", "Fatima Shaikh"]


# ---- reading records -----------------------------------------------------------------------------------------------

def city_of(text: Any) -> str | None:
    t = f" {norm(text)} "
    for city, names in CITIES.items():
        if any(f" {n} " in t for n in names):
            return city
    return None


def _role_text(title: str | None) -> str:
    return f" {norm(title)} " if title else ""


def family_of(title: str | None) -> str | None:
    t = _role_text(title)
    for fam, spec in ROLE_FAMILIES.items():
        if any(f" {norm(w)} " in t or (" " in w and norm(w) in t) for w in spec["words"]):
            return fam
    return None


def fits(rec: dict, fam: str) -> tuple[bool, str | None, str | None]:
    """Does the record show a current or past role in this line of work? (fit, title, field path)"""
    pr = load_person(rec)
    for j in pr.current + pr.past:
        if j.title and family_of(j.title) == fam:
            return True, f"{j.title} at {j.company}", f"{j.path}.title"
    return False, None, None


def _plain(s: str | None) -> str:
    """Fold styled letters people put in profile names (small capitals, fullwidth, accents) to plain ASCII."""
    import unicodedata

    out = []
    for ch in unicodedata.normalize("NFKC", s or ""):
        name = unicodedata.name(ch, "")
        m = re.match(r"LATIN (?:LETTER SMALL CAPITAL|SMALL LETTER|CAPITAL LETTER) ([A-Z])\b", name)
        out.append(m.group(1).lower() if m and not ch.isascii() else ch)
    return unicodedata.normalize("NFKD", "".join(out)).encode("ascii", "ignore").decode()


def names_match(applied: str | None, record: str | None) -> bool:
    """First and last name tokens must agree (initials and middle names are allowed to differ)."""
    a = [t for t in norm(_plain(applied)).split() if len(t) > 1]
    r = [t for t in norm(_plain(record)).split() if len(t) > 1]
    if not a or not r:
        return False
    return a[0] == r[0] and (len(a) == 1 or len(r) == 1 or a[-1] == r[-1] or a[-1] in r)


# ---- seeding applications (the test harness: real people, planted lies, an answer key kept aside) -----------------

def _inflate(title: str, record_rank: int) -> str | None:
    base = re.sub(r"\b(senior|sr\.?|junior|jr\.?|lead|trainee|associate)\b", "", title, flags=re.I).strip(" ,-") or title
    if record_rank < 2:
        return f"Senior {base} Team Lead"
    if record_rank < 4:
        return f"Head of {base}"
    return None


def _plant(kind: str, rec: dict, app: dict, rng: random.Random, today: date) -> str | None:
    """Mutate app with one lie of this kind. Returns what the record really says, or None if it can't carry it."""
    pr = load_person(rec)
    cur = pr.current[0] if pr.current else None
    c = app["claimed"]
    if kind == "stale_current_job" and cur and pr.past and not same_company(pr.past[0].company, cur.company):
        c["employer"] = pr.past[0].company
        return f"current employer is {cur.company}"
    if kind == "fake_employer" and cur:
        known = [j.company for j in pr.current + pr.past]
        fake = next((f for f in rng.sample(FAMOUS, len(FAMOUS)) if not any(same_company(f, k) for k in known)), None)
        if fake:
            c["employer"] = fake
            return f"{fake} is not in the employment record"
    if kind == "inflated_title" and cur and cur.title:
        rank = max(seniority_rank(cur.title), seniority_rank(cur.seniority_level) if cur.seniority_level else 0)
        t = _inflate(cur.title, rank)
        if t:
            c["title"] = t
            return f"record title is '{cur.title}'"
    if kind == "stretched_tenure" and cur and cur.start and cur.start.year > 1990:
        c["start_date"] = cur.start.replace(year=cur.start.year - rng.choice((2, 3)), day=1).isoformat()
        return f"record start date is {cur.start.isoformat()}"
    if kind == "inflated_experience":
        starts = [j.start for j in pr.current + pr.past if j.start]
        if starts:
            total = (today - min(starts)).days / 365.25
            c["years_experience"] = int(total) + rng.choice((4, 5, 6))
            return f"earliest role starts {min(starts).isoformat()} (~{total:.1f} yrs)"
    if kind == "wrong_location":
        home = city_of(pr.location)
        if home:
            other = rng.choice([x for x in CITIES if x != home])
            app["city"] = other
            c["location"] = other
            return f"record location is {pr.location}"
    if kind == "identity_mismatch" and pr.name:
        other = next((n for n in rng.sample(OTHER_NAMES, len(OTHER_NAMES)) if not names_match(n, pr.name)), None)
        if other:
            app["name"] = other
            return f"profile belongs to {pr.name}"
    if kind == "ghost_profile":
        slug = re.sub(r"[^a-z]+", "-", (app["name"] or "applicant").lower()).strip("-")
        app["profile_url"] = f"https://www.linkedin.com/in/{slug}-{rng.getrandbits(32):08x}"
        return "no such profile in Crustdata"
    return None


def _honest_claims(rec: dict, rng: random.Random, today: date) -> dict:
    """What a truthful applicant writes, with the small mess real forms have."""
    pr = load_person(rec)
    cur = pr.current[0] if pr.current else None
    c: dict[str, Any] = {}
    if cur:
        c["employer"] = cur.company
        if cur.title:
            c["title"] = cur.title if rng.random() < 0.7 else cur.title.lower()
        if cur.start:
            jitter = rng.choice((0, 0, 0, 31, -30, 62))  # "joined around March" vs the record's 1 April
            c["start_date"] = (cur.start + timedelta(days=jitter)).isoformat()
    starts = [j.start for j in pr.current + pr.past if j.start]
    if starts:
        c["years_experience"] = int((today - min(starts)).days / 365.25)
    home = city_of(pr.location)
    if home:
        alias = sorted(CITIES[home])
        c["location"] = rng.choice(alias).title() if rng.random() < 0.5 else home
    return c


def seed_applications(pool: list[dict], *, fake_rate: float = 0.15, seed: int = 7, today: date | None = None,
                      limit: int | None = None) -> tuple[list[dict], dict[str, dict]]:
    """Applications from real records, a `fake_rate` share with one planted lie. Returns (applications, answer_key)."""
    today = today or date.today()
    rng = random.Random(seed)
    usable = []
    for rec in pool:
        pr = load_person(rec)
        fam = family_of(pr.current[0].title if pr.current else None) or rec.get("_family")
        if pr.profile_url and pr.name and pr.current and fam in ROLE_FAMILIES and city_of(pr.location):
            usable.append((rec, pr, fam))
    rng.shuffle(usable)
    if limit:
        usable = usable[:limit]
    n_fake = round(len(usable) * fake_rate)
    fake_idx = set(rng.sample(range(len(usable)), n_fake)) if usable else set()
    apps, key = [], {}
    kinds = list(LIE_TYPES)
    for i, (rec, pr, fam) in enumerate(usable):
        app = {"id": f"app{i + 1:04d}", "name": pr.name, "profile_url": pr.profile_url, "role": fam,
               "city": city_of(pr.location), "claimed": _honest_claims(rec, rng, today),
               "availability": sorted(rng.sample(range(7), rng.randint(3, 6))), "max_shifts_per_week": rng.randint(2, 5)}
        entry = {"fake": False}
        if i in fake_idx:
            for kind in rng.sample(kinds, len(kinds)):
                truth = _plant(kind, rec, app, rng, today)
                if truth:
                    entry = {"fake": True, "lie": kind, "truth": truth, "real_name": pr.name}
                    break
        apps.append(app)
        key[app["id"]] = entry
    return apps, key


def make_shifts(n: int, *, start: date, days: int = 7, seed: int = 7, cities: list[str] | None = None,
                demand: dict[str, float] | None = None) -> list[dict]:
    """n single-worker shifts over `days` days. Demand by role is the agency's order book, not the applicant mix."""
    rng = random.Random(seed * 31 + n)
    cities = cities or list(CITIES)
    demand = demand or {"delivery": 0.3, "warehouse": 0.25, "support": 0.15, "retail": 0.15, "security": 0.08, "hospitality": 0.07}
    fams, weights = zip(*demand.items())
    city_w = [1.6 if c in ("Bangalore", "Mumbai", "Delhi NCR") else 1.0 for c in cities]
    out = []
    for i in range(n):
        fam = rng.choices(fams, weights)[0]
        spec = ROLE_FAMILIES[fam]
        day = start + timedelta(days=rng.randrange(days))
        out.append({"id": f"s{i + 1:04d}", "role": fam, "role_label": spec["label"], "city": rng.choices(cities, city_w)[0],
                    "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "start_hour": rng.choice(spec["hours"]),
                    "hours": spec["len"]})
    return out


# ---- screening -----------------------------------------------------------------------------------------------------

@dataclass
class Screening:
    app_id: str
    name: str
    profile_url: str
    role: str
    city: str | None
    outcome: str                     # cleared | flagged | not_qualified
    reason: str
    kind: str | None = None          # identity_unverifiable | identity_mismatch | false_claim | role_mismatch
    claims: list[Claim] = field(default_factory=list)
    record_name: str | None = None
    home_city: str | None = None

    def dump(self) -> dict:
        return {"app_id": self.app_id, "name": self.name, "profile_url": self.profile_url, "role": self.role,
                "city": self.city, "outcome": self.outcome, "reason": self.reason, "kind": self.kind,
                "record_name": self.record_name, "home_city": self.home_city,
                "claims": [c.model_dump() for c in self.claims]}


async def screen(app: dict, graph: PoolGraph, today: date) -> Screening:
    s = Screening(app["id"], app.get("name") or "", app.get("profile_url") or "", app.get("role") or "", app.get("city"),
                  "flagged", "", None)
    url = s.profile_url
    try:
        rec = await graph.person(url) if url else None
    except Exception as e:  # noqa: BLE001 - a lookup failure holds the application, it never clears it
        log.warning("staffing: lookup failed for %s: %s", url, e)
        rec = None
    if rec is None:
        s.kind, s.reason = "identity_unverifiable", f"No Crustdata record for {url or 'a missing profile URL'}; identity can't be confirmed"
        s.claims = [Claim(id="k1", claim=f"Profile {url}", status="unverifiable", evidence="no Person record for this URL",
                          source=Source(endpoint="person/enrich", url=url or None))]
        return s
    pr = load_person(rec)
    ep = pr.endpoint
    s.record_name, s.home_city = pr.name, city_of(pr.location)
    if not names_match(s.name, pr.name):
        s.kind, s.reason = "identity_mismatch", f"Applied as {s.name}, but this profile belongs to {pr.name}"
        s.claims = [Claim(id="k1", claim=f"Name: {s.name}", status="contradicted", evidence=f"record name is {pr.name}",
                          source=Source(endpoint=ep, field=pr.name_field, url=url))]
        return s
    claimed = {k: v for k, v in (app.get("claimed") or {}).items() if k != "location"}
    claimed["_source"] = f"application {app['id']}"
    spec = ROLE_FAMILIES.get(s.role, {})
    claims, _flags = await verify_candidate({**rec, "claimed": claimed}, None, Criteria(role=spec.get("label", s.role)), None, today=today)
    claims = [c for c in claims if not c.claim.startswith(("Career:", "Progression", "Based in"))]
    # Home city: the shift is staffed locally, so the city on the application must be the record's city.
    want = city_of(app.get("claimed", {}).get("location") or s.city)
    loc_field = pr.location_field
    if not s.home_city:
        claims.append(Claim(id=f"k{len(claims) + 1}", claim=f"Lives in {want}", status="unverifiable",
                            evidence=f"record location '{pr.location or 'none'}' isn't a city we staff", source=Source(endpoint=ep, field=loc_field, url=url)))
    elif want and want != s.home_city:
        claims.append(Claim(id=f"k{len(claims) + 1}", claim=f"Lives in {want}", status="contradicted",
                            evidence=f"record says {pr.location}", source=Source(endpoint=ep, field=loc_field, url=url)))
    else:
        claims.append(Claim(id=f"k{len(claims) + 1}", claim=f"Lives in {s.home_city}", status="verified",
                            evidence=f"record says {pr.location}", source=Source(endpoint=ep, field=loc_field, url=url)))
    s.claims = claims
    bad = [c for c in claims if c.status == "contradicted"]
    if bad:
        s.kind, s.reason = "false_claim", "; ".join(f"{c.claim} ({c.evidence})" for c in bad[:3])
        return s
    ok, what, fld = fits(rec, s.role)
    s.claims.append(Claim(id=f"k{len(s.claims) + 1}", claim=f"Has done {spec.get('label', s.role).lower()} work",
                          status="verified" if ok else "unverifiable",
                          evidence=what or "no current or past role in this line of work",
                          source=Source(endpoint=ep, field=fld or "experience.employment_details", url=url)))
    if not ok:
        s.outcome, s.kind, s.reason = "not_qualified", "role_mismatch", f"No {spec.get('label', s.role).lower()} role on the record"
        return s
    s.outcome, s.reason = "cleared", f"Identity and claims check out; {what}"
    return s


# ---- assignment ----------------------------------------------------------------------------------------------------

def assign(shifts: list[dict], workers: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Greedy, scarcest shift first. workers: {id, role, city, availability [weekday ints], max_shifts_per_week}.
    Returns (shift_id -> worker_id, shift_id -> why it stayed open)."""
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for w in workers:
        by_key[(w["role"], w["city"])].append(w)
    load: Counter = Counter()
    week_load: Counter = Counter()
    busy: set[tuple[str, str]] = set()

    def eligible(s: dict) -> list[dict]:
        wd = date.fromisoformat(s["date"]).weekday()
        return [w for w in by_key.get((s["role"], s["city"]), []) if wd in w["availability"]]

    pool = {s["id"]: eligible(s) for s in shifts}
    order = sorted(shifts, key=lambda s: (len(pool[s["id"]]), s["date"], s["id"]))
    filled, why = {}, {}
    for s in order:
        cands = pool[s["id"]]
        if not by_key.get((s["role"], s["city"])):
            why[s["id"]] = f"no cleared {ROLE_FAMILIES[s['role']]['label'].lower()} in {s['city']}"
            continue
        if not cands:
            why[s["id"]] = f"no cleared worker free on {s['weekday']}s"
            continue
        d = date.fromisoformat(s["date"])
        wk = d.isocalendar()[:2]
        free = [w for w in cands if (w["id"], s["date"]) not in busy and week_load[(w["id"], wk)] < w["max_shifts_per_week"]]
        if not free:
            why[s["id"]] = "every eligible worker already booked that day or at their weekly cap"
            continue
        w = min(free, key=lambda w: (load[w["id"]], w["id"]))
        filled[s["id"]] = w["id"]
        load[w["id"]] += 1
        week_load[(w["id"], wk)] += 1
        busy.add((w["id"], s["date"]))
    return filled, why


# ---- the run -------------------------------------------------------------------------------------------------------

Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    return None


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def score(screens: list[Screening], key: dict[str, dict], filled: dict[str, str]) -> dict:
    """Fake-catch metrics against the answer key. Positive = flagged (never staffed)."""
    flagged = {s.app_id for s in screens if s.outcome == "flagged"}
    fakes = {a for a, k in key.items() if k.get("fake")}
    tp, fp, fn = len(flagged & fakes), len(flagged - fakes), len(fakes - flagged)
    per: dict[str, dict] = {}
    for a in fakes:
        lie = key[a]["lie"]
        d = per.setdefault(lie, {"planted": 0, "caught": 0})
        d["planted"] += 1
        d["caught"] += a in flagged
    for d in per.values():
        d["recall"] = _ratio(d["caught"], d["planted"])
    staffed_workers = set(filled.values())
    by_id = {s.app_id: s for s in screens}
    return {
        "applications": len(screens), "fakes_planted": len(fakes), "flagged": len(flagged),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
        "by_lie_type": dict(sorted(per.items())),
        "fakes_staffed": sorted(a for a in staffed_workers if a in fakes),
        "missed": [{"app_id": a, **key[a], "outcome": by_id[a].outcome} for a in sorted(fakes - flagged) if a in by_id],
        "false_alarms": [{"app_id": a, "reason": by_id[a].reason} for a in sorted(flagged - fakes) if a in by_id],
    }


async def run_staffing(applications: list[dict], shifts: list[dict], graph: PoolGraph, *, today: date | None = None,
                       answer_key: dict[str, dict] | None = None, emit: Emit = _noop) -> dict:
    today = today or date.today()
    await emit({"type": "step", "step": "ingest", "message": f"{len(applications)} applications for {len(shifts)} shifts",
                "data": {"applications": len(applications), "shifts": len(shifts)}})
    screens: list[Screening] = []
    seen: dict[str, str] = {}
    for i, app in enumerate(applications):
        s = await screen(app, graph, today)
        from ..agents.graph import norm_url
        u = norm_url(app.get("profile_url"))
        if s.outcome == "cleared" and u in seen:
            s.outcome, s.kind, s.reason = "flagged", "duplicate", f"Same profile already applied as {seen[u]}"
        if s.outcome == "cleared":
            seen[u] = app["id"]
        screens.append(s)
        if (i + 1) % 100 == 0 or i + 1 == len(applications):
            c = Counter(x.outcome for x in screens)
            await emit({"type": "step", "step": "screen", "message": f"Screened {i + 1}/{len(applications)}: "
                        f"{c['cleared']} cleared, {c['flagged']} flagged, {c['not_qualified']} not qualified",
                        "data": dict(c, done=i + 1)})
        if s.outcome == "flagged":
            await emit({"type": "flagged", "screening": s.dump()})
    by_app = {a["id"]: a for a in applications}
    workers = [{"id": s.app_id, "role": s.role, "city": s.home_city, "availability": by_app[s.app_id].get("availability") or list(range(7)),
                "max_shifts_per_week": by_app[s.app_id].get("max_shifts_per_week") or 3}
               for s in screens if s.outcome == "cleared"]
    filled, why = assign(shifts, workers)
    fill = len(filled) / len(shifts) if shifts else 0.0
    await emit({"type": "step", "step": "assign", "message": f"Filled {len(filled)}/{len(shifts)} shifts ({fill:.1%}) with {len(set(filled.values()))} cleared workers",
                "data": {"filled": len(filled), "shifts": len(shifts)}})
    by_city: dict[str, Counter] = defaultdict(Counter)
    by_role: dict[str, Counter] = defaultdict(Counter)
    for s in shifts:
        k = "filled" if s["id"] in filled else "open"
        by_city[s["city"]][k] += 1
        by_role[s["role"]][k] += 1
    report = {
        "today": today.isoformat(),
        "screening": dict(Counter(s.outcome for s in screens)),
        "flag_kinds": dict(Counter(s.kind for s in screens if s.outcome == "flagged")),
        "shifts": len(shifts), "filled": len(filled), "fill_rate": round(fill, 4),
        "workers_used": len(set(filled.values())), "workers_cleared": len(workers),
        "by_city": {c: dict(v, fill_rate=_ratio(v["filled"], v["filled"] + v["open"])) for c, v in sorted(by_city.items())},
        "by_role": {r: dict(v, fill_rate=_ratio(v["filled"], v["filled"] + v["open"])) for r, v in sorted(by_role.items())},
        "open_reasons": dict(Counter(why.values()).most_common()),
    }
    if answer_key is not None:
        report["fake_catch"] = score(screens, answer_key, filled)
    roster = [{**s, "worker": filled.get(s["id"]), "worker_name": by_app[filled[s["id"]]]["name"] if s["id"] in filled else None,
               "open_reason": why.get(s["id"])} for s in shifts]
    await emit({"type": "done", "report": report})
    return {"report": report, "roster": roster, "screenings": [s.dump() for s in screens]}


async def fetch_shift_pool(client: Any, per_role: int = 200, roles: list[str] | None = None) -> list[dict]:
    """Real shift workers from Crustdata: one paged Person Search per line of work, across the cities we staff."""
    out: list[dict] = []
    seen: set[str] = set()
    from ..agents.graph import norm_url

    for fam in roles or list(ROLE_FAMILIES):
        f = all_of(title_filter(ROLE_FAMILIES[fam]["titles"]), city_filter(SEARCH_CITIES))
        try:
            rows = await fetch_pool(client, f, per_role)
        except Exception as e:  # noqa: BLE001 - one role failing leaves the others
            log.warning("staffing pool: %s search failed: %s", fam, e)
            continue
        for r in rows:
            u = norm_url(load_person(r).profile_url)
            if u and u not in seen:
                seen.add(u)
                out.append({**r, "_family": fam})
    return out
