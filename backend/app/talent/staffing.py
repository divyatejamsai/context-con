"""Staff a thousand shifts from applications, for whatever roles the company is hiring for at volume.

The pipeline a staffing team runs every week, with no one at the keyboard:

    0 roles      the company defines each role it is hiring for: title, cities, shift times, workers per shift,
                 minimum experience, required skills, certifications and languages (`Role`). Templates cover
                 quick-commerce and logistics, BPO, retail seasonal, hospital nursing, events and campus fresher drives
    1 ingest     applications arrive, from a CSV upload (`parse_csv`) or the recorded Crustdata pool: name, profile URL,
                 phone / email, the role and city applied for, what they claim (employer, title, start date, years of
                 experience, where they live, skills, certifications, languages) and when they can work
    2 dedupe     the same person applying twice (same profile, phone or email) is merged before any lookup is paid for;
                 one phone or email behind several different people is held for a recruiter
    3 screen     every application is checked against the person's Crustdata record:
                   identity   the profile exists, and the name on the application matches the record's name
                   claims     employer, title, tenure, experience (app/verify/verifier.py, the same verifier the
                              hiring agent and Send Guard use) and home city, each verified / contradicted / unverifiable
                              with the field that decides it
                   fit        the role's requirements: related work on the record, years of it, skills (record first,
                              self-reported second), certifications and languages (checked at onboarding)
                 outcome: cleared, flagged (false claim or identity problem: never staffed), not_qualified, duplicate,
                 or held (no record in the recorded data and live lookups are off)
    4 assign     cleared workers are matched to shifts: same city, same role, a day they said they're free, never two
                 shifts that overlap (or closer than the rest gap) for one person across all their roles, and their
                 weekly cap. Scarcest shifts are filled first, and work is spread to the least-loaded worker
    5 bench      for every shift, a share of standby workers who are free then and under their cap, so a no-show is
                 backfilled from the bench (`Rota.no_show`)
    6 report     fill rate (overall, by city and role, why the rest stayed open), duplicates, a double-booking audit,
                 bench coverage, and in test mode, against the answer key the seeding step kept aside, fake-catch
                 precision and recall, recall per lie type, fakes staffed, duplicates caught and a no-show drill

Test mode (`seed_applications`) is how we prove the screen works: real Crustdata people become applicants, most honest
(with the small mess real forms have: Bangalore vs Bengaluru, a start date a month off), a share carry one planted lie
that the record can disprove, and a few apply twice. The screener never sees the answer key.
"""
from __future__ import annotations

import asyncio
import copy
import csv
import io
import logging
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field, field_validator, model_validator

from ..schemas import Claim, Criteria, Source
from ..verify.profile import get_path, load_person, norm, same_company, seniority_rank
from ..verify.verifier import verify_candidate
from .pool import PoolGraph, all_of, city_filter, fetch_pool, title_filter

log = logging.getLogger(__name__)


def norm_url(u: str | None) -> str:
    from ..agents.graph import norm_url as _n

    return _n(u)


# ---- cities --------------------------------------------------------------------------------------------------------

CITIES: dict[str, set[str]] = {
    "Bangalore": {"bangalore", "bengaluru"},
    "Mumbai": {"mumbai", "bombay", "navi mumbai", "thane"},
    "Delhi NCR": {"delhi", "new delhi", "gurgaon", "gurugram", "noida", "ghaziabad", "faridabad"},
    "Hyderabad": {"hyderabad", "secunderabad"},
    "Pune": {"pune"},
    "Chennai": {"chennai", "madras"},
}
MORE_CITIES: dict[str, set[str]] = {
    "Kolkata": {"kolkata", "calcutta", "howrah"}, "Ahmedabad": {"ahmedabad", "gandhinagar"}, "Jaipur": {"jaipur"},
    "Kochi": {"kochi", "cochin", "ernakulam"}, "Lucknow": {"lucknow"}, "Chandigarh": {"chandigarh", "mohali", "panchkula"},
    "Indore": {"indore"}, "Coimbatore": {"coimbatore"}, "Surat": {"surat"}, "Nagpur": {"nagpur"},
}
ALL_CITIES = {**CITIES, **MORE_CITIES}
SEARCH_CITIES = ["Bangalore", "Mumbai", "Delhi", "Gurgaon", "Noida", "Hyderabad", "Pune", "Chennai"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def aliases(city: str) -> set[str]:
    c = canon_city(city)
    return ALL_CITIES.get(c, {norm(c)})


def canon_city(text: Any) -> str:
    """'bengaluru' -> 'Bangalore', 'Gurugram' -> 'Delhi NCR'; a city we don't know keeps its own name."""
    t = f" {norm(text)} "
    for city, names in ALL_CITIES.items():
        if norm(city) == t.strip() or any(f" {n} " in t for n in names):
            return city
    return str(text or "").strip().title()


def city_of(text: Any, extra: list[str] | None = None) -> str | None:
    """The city a free-text location is in, among the cities we know (and any extra role cities)."""
    t = f" {norm(text)} "
    for city in [*(extra or []), *ALL_CITIES]:
        if any(f" {n} " in t for n in aliases(city)):
            return canon_city(city)
    return None


# ---- roles ---------------------------------------------------------------------------------------------------------

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_GENERIC = {"associate", "executive", "staff", "senior", "junior", "jr", "sr", "trainee", "officer", "assistant", "and",
            "the", "of", "for", "team", "member", "worker", "partner", "seasonal", "temporary", "temp", "part", "time"}


class Slot(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        m = _HHMM.match(v.strip())
        if not m:
            raise ValueError(f"shift time {v!r} must be HH:MM")
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"


def parse_slots(text: str) -> list[Slot]:
    """'07:00-13:00, 17:00-23:00' -> two slots."""
    return [Slot(start=a, end=b) for a, b in re.findall(r"(\d{1,2}:\d{2})\s*[-–to ]+\s*(\d{1,2}:\d{2})", text or "")]


class Role(BaseModel):
    """One role the company is hiring for at volume, with its own requirements."""
    id: str = ""
    title: str = Field(..., min_length=2, max_length=80)
    cities: list[str] = Field(..., min_length=1, max_length=40)
    slots: list[Slot] = Field(..., min_length=1, max_length=8)   # shift times; an end before the start runs overnight
    days: list[int] = Field(default_factory=lambda: list(range(7)))  # weekdays the role runs, 0 = Monday
    headcount: int = Field(1, ge=0, le=500)                          # workers per shift, per city, per day
    city_headcount: dict[str, int] = Field(default_factory=dict)     # per-city override of headcount
    min_years: float = Field(0, ge=0, le=40)
    max_years: float | None = Field(None, ge=0, le=40)               # e.g. a campus fresher drive
    related_experience: bool = True                                  # must have done this line of work before
    keywords: list[str] = Field(default_factory=list)                # job titles that count as this line of work
    search_titles: list[str] = Field(default_factory=list)           # current titles to search Crustdata for applicants
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill(self) -> "Role":
        self.title = self.title.strip()
        self.id = re.sub(r"[^a-z0-9]+", "-", (self.id or self.title).lower()).strip("-")[:40] or "role"
        self.cities = list(dict.fromkeys(canon_city(c) for c in self.cities if str(c).strip()))
        if not self.cities:
            raise ValueError("a role needs at least one city")
        self.city_headcount = {canon_city(k): max(0, int(v)) for k, v in self.city_headcount.items()}
        self.days = sorted({int(d) for d in self.days if 0 <= int(d) <= 6}) or list(range(7))
        clean = lambda xs: list(dict.fromkeys(x.strip() for x in xs if x and x.strip()))  # noqa: E731
        self.skills, self.certifications, self.languages = clean(self.skills), clean(self.certifications), clean(self.languages)
        self.keywords = clean([k.lower() for k in self.keywords]) or default_keywords(self.title)
        self.search_titles = clean([t.lower() for t in self.search_titles])
        return self

    def seats(self, city: str) -> int:
        return self.city_headcount.get(city, self.headcount)

    def needs(self) -> list[str]:
        out = []
        if self.related_experience:
            out.append(f"{_yrs(self.min_years)} of {self.title.lower()} work" if self.min_years else f"prior {self.title.lower()} work")
        elif self.min_years:
            out.append(f"{_yrs(self.min_years)} of work experience")
        if self.max_years is not None:
            out.append(f"at most {_yrs(self.max_years)} of experience")
        out += self.skills + self.certifications + [f"speaks {lang}" for lang in self.languages]
        return out


def _yrs(x: float) -> str:
    return f"{x:g} year" + ("" if x == 1 else "s")


def default_keywords(title: str) -> list[str]:
    toks = [t for t in norm(title).split() if t not in _GENERIC and len(t) > 2]
    phrase = " ".join(toks)
    return list(dict.fromkeys([p for p in [phrase, *toks] if p])) or [norm(title)]


def _hit(text: str, kw: str) -> bool:
    t, k = f" {norm(text)} ", norm(kw)
    return bool(k) and (f" {k} " in t or f" {k}s " in t or (" " in k and k in t))


def role_fit(title: str | None, role: Role) -> bool:
    return bool(title) and any(_hit(title, k) for k in role.keywords)


# The lines of shift work in the default template (quick-commerce and logistics), kept under their old ids so recorded
# pools (each record carries `_family`) and older reports still line up.
ROLE_FAMILIES: dict[str, dict] = {
    "delivery": {"label": "Delivery associate", "titles": ["delivery executive", "delivery associate", "delivery partner", "delivery boy", "rider"],
                 "words": ["delivery", "rider", "courier", "logistics", "dispatch", "last mile", "fleet"]},
    "warehouse": {"label": "Warehouse associate", "titles": ["warehouse associate", "warehouse executive", "picker", "packer", "inventory associate"],
                  "words": ["warehouse", "picker", "packer", "inventory", "fulfilment", "fulfillment", "store keeper", "storekeeper", "logistics"]},
    "support": {"label": "Customer support associate", "titles": ["customer support executive", "customer care executive", "customer service associate", "customer support associate"],
                "words": ["customer support", "customer care", "customer service", "call center", "call centre", "telecaller", "bpo", "voice process", "chat support"]},
    "retail": {"label": "Retail associate", "titles": ["retail sales associate", "store associate", "cashier", "sales associate"],
               "words": ["retail", "store", "cashier", "sales associate", "floor", "showroom"]},
    "security": {"label": "Security officer", "titles": ["security guard", "security officer", "security supervisor"], "words": ["security"]},
    "hospitality": {"label": "Hospitality associate", "titles": ["barista", "steward", "waiter", "housekeeping", "front office executive"],
                    "words": ["barista", "steward", "waiter", "housekeeping", "front office", "hospitality", "f&b", "food and beverage", "chef", "cook"]},
}
_BIG = {"Bangalore": 2, "Mumbai": 2, "Delhi NCR": 2}


def _r(id: str, slots: str, headcount: int = 1, big: int | None = None, **kw) -> dict:
    fam = ROLE_FAMILIES.get(id, {})
    d = {"id": id, "title": kw.pop("title", fam.get("label", id)), "cities": kw.pop("cities", list(CITIES)),
         "slots": [s.model_dump() for s in parse_slots(slots)], "headcount": headcount,
         "keywords": kw.pop("keywords", fam.get("words", []) + fam.get("titles", []))}
    if big is not None:
        d["city_headcount"] = {c: big for c in _BIG if c in d["cities"]}
    return {**d, **kw}


TEMPLATES: list[dict] = [
    {"id": "quick-commerce", "label": "Quick-commerce and logistics", "blurb": "Riders, warehouse, support, store, security and cafe staff across six metros.",
     "roles": [
         _r("delivery", "07:00-13:00, 12:00-18:00, 17:00-23:00", 2, big=3, certifications=["Two-wheeler driving licence"]),
         _r("warehouse", "06:00-14:00, 14:00-22:00, 22:00-06:00", 2, big=2),
         _r("support", "09:00-17:00, 13:00-21:00", 1, big=2, languages=["English", "Hindi"]),
         _r("retail", "10:00-16:00, 15:00-21:00", 1, big=2),
         _r("security", "08:00-20:00, 20:00-08:00", 1),
         _r("hospitality", "07:00-15:00, 15:00-23:00", 1),
     ]},
    {"id": "bpo", "label": "BPO and call centre", "blurb": "Voice and chat agents on rotating shifts, including the US night shift.",
     "roles": [
         _r("voice-agent", "09:00-18:00, 18:30-03:30", 3, search_titles=["customer service executive", "customer care executive", "telecaller", "voice process", "customer support associate", "call center executive", "tele sales"], title="Customer service voice agent", cities=["Bangalore", "Hyderabad", "Pune", "Delhi NCR", "Mumbai", "Chennai"],
            keywords=ROLE_FAMILIES["support"]["words"] + ROLE_FAMILIES["support"]["titles"] + ["telesales", "tele caller"], languages=["English", "Hindi"],
            skills=["Typing 30 wpm"]),
         _r("chat-agent", "10:00-19:00", 2, search_titles=["chat support", "chat process", "non voice", "email support", "customer support associate"], title="Chat support agent", cities=["Bangalore", "Hyderabad", "Pune", "Chennai"],
            keywords=["chat support", "customer support", "customer service", "email support", "non voice"], languages=["English"]),
         _r("team-lead", "09:00-18:00", 1, search_titles=["team leader bpo", "team lead customer", "process lead", "team leader customer", "operations team lead"], title="BPO team leader", cities=["Bangalore", "Hyderabad", "Pune"], min_years=2,
            keywords=["team leader", "team lead", "process lead", "supervisor"], languages=["English"]),
     ]},
    {"id": "retail-seasonal", "label": "Retail seasonal (festive sale)", "blurb": "Store, cashier and stockroom staff for the festive rush.",
     "roles": [
         _r("store-associate", "10:00-16:00, 15:00-22:00", 3, search_titles=["store associate", "retail associate", "sales associate", "customer service associate retail", "floor associate", "store executive"], title="Store associate", keywords=ROLE_FAMILIES["retail"]["words"] + ROLE_FAMILIES["retail"]["titles"]),
         _r("cashier", "10:00-16:00, 15:00-22:00", 1, search_titles=["cashier", "billing executive", "billing associate", "pos executive"], title="Cashier", keywords=["cashier", "billing", "pos", "checkout"], skills=["POS billing"]),
         _r("stockroom", "07:00-15:00", 1, search_titles=["inventory associate", "stock associate", "store keeper", "inventory executive", "stock controller"], title="Stockroom associate", keywords=["inventory", "stock", "warehouse", "picker", "packer", "store keeper"]),
     ]},
    {"id": "hospital", "label": "Hospital nursing", "blurb": "Staff nurses and ward assistants on three rotating shifts.",
     "roles": [
         _r("staff-nurse", "07:00-14:00, 14:00-21:00, 21:00-07:00", 4, search_titles=["staff nurse", "registered nurse", "nursing officer", "icu nurse", "senior staff nurse", "nurse"], title="Staff nurse", cities=["Bangalore", "Chennai", "Kochi", "Hyderabad"],
            keywords=["nurse", "nursing", "staff nurse", "icu", "ward"], min_years=1, certifications=["Registered nurse (state nursing council)", "BLS"],
            languages=["English"]),
         _r("ward-assistant", "07:00-15:00, 15:00-23:00, 23:00-07:00", 2, search_titles=["ward assistant", "patient care assistant", "nursing assistant", "general duty assistant", "patient attendant", "ward boy"], title="Ward assistant", cities=["Bangalore", "Chennai", "Kochi", "Hyderabad"],
            keywords=["ward boy", "ward assistant", "patient care", "nursing assistant", "attendant", "housekeeping"], related_experience=False),
     ]},
    {"id": "events", "label": "Events and stadiums", "blurb": "Ushers, crowd security and F&B staff for a weekend of events.",
     "roles": [
         _r("usher", "14:00-23:00", 15, search_titles=["event coordinator", "event executive", "event staff", "usher", "guest relations executive", "front office executive"], title="Event usher", cities=["Mumbai", "Bangalore", "Delhi NCR"], days=[5, 6], related_experience=False,
            keywords=["event", "usher", "hospitality", "front office", "steward"], languages=["English"]),
         _r("crowd-security", "13:00-01:00", 10, search_titles=["security guard", "security officer", "bouncer", "security supervisor"], title="Crowd security", cities=["Mumbai", "Bangalore", "Delhi NCR"], days=[5, 6],
            keywords=["security"], certifications=["PSARA training certificate"]),
         _r("fnb", "15:00-23:00", 8, search_titles=["f&b associate", "food and beverage", "steward", "waiter", "barista", "commis chef"], title="F&B counter staff", cities=["Mumbai", "Bangalore", "Delhi NCR"], days=[5, 6],
            keywords=ROLE_FAMILIES["hospitality"]["words"], certifications=["FSSAI food handler"]),
     ]},
    {"id": "campus", "label": "Campus fresher drive", "blurb": "Graduate trainees for IT services, with no prior experience needed.",
     "roles": [
         _r("graduate-trainee", "09:00-18:00", 10, search_titles=["graduate engineer trainee", "trainee software engineer", "associate software engineer", "software engineer trainee", "trainee engineer"], title="Graduate engineer trainee", cities=["Bangalore", "Pune", "Hyderabad", "Chennai"], days=[0, 1, 2, 3, 4],
            related_experience=False, max_years=1, keywords=["trainee", "intern", "graduate"], skills=["Java or Python"], languages=["English"]),
     ]},
]
DEFAULT_TEMPLATE = "quick-commerce"


def template(tid: str = DEFAULT_TEMPLATE) -> list[Role]:
    t = next((t for t in TEMPLATES if t["id"] == tid), None)
    if t is None:
        raise KeyError(tid)
    return [Role(**r) for r in t["roles"]]


def default_roles() -> list[Role]:
    return template(DEFAULT_TEMPLATE)


def resolve_role(text: Any, roles: list[Role]) -> Role | None:
    """An application's 'role' column -> the role it means: by id, by title, or by the best keyword match."""
    t = norm(text)
    if not t:
        return roles[0] if len(roles) == 1 else None
    for r in roles:
        if t in (r.id, norm(r.title), norm(r.id.replace("-", " "))):
            return r
    hits = [(sum(_hit(t, k) for k in r.keywords) + (norm(r.title) in t) * 2, i) for i, r in enumerate(roles)]
    best = max(hits, default=(0, 0))
    return roles[best[1]] if best[0] > 0 else None


# ---- shifts --------------------------------------------------------------------------------------------------------

def _at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m)


def _seat(i: int, role: Role, city: str, day: date, slot: Slot) -> dict:
    st, en = _at(day, slot.start), _at(day, slot.end)
    if en <= st:
        en += timedelta(days=1)
    return {"id": f"s{i:05d}", "role": role.id, "role_label": role.title, "city": city, "date": day.isoformat(),
            "weekday": WEEKDAYS[day.weekday()], "slot": slot.label, "start": st.isoformat(timespec="minutes"),
            "end": en.isoformat(timespec="minutes"), "start_hour": st.hour, "hours": round((en - st).seconds / 3600, 2)}


def build_shifts(roles: list[Role], *, start: date, days: int = 7) -> list[dict]:
    """Every role x city x day it runs x shift time x headcount, one single-worker seat each."""
    out: list[dict] = []
    for d in range(days):
        day = start + timedelta(days=d)
        for role in roles:
            if day.weekday() not in role.days:
                continue
            for city in role.cities:
                for slot in role.slots:
                    for _ in range(role.seats(city)):
                        out.append(_seat(len(out) + 1, role, city, day, slot))
    return out


def make_shifts(n: int, *, start: date, days: int = 7, seed: int = 7, cities: list[str] | None = None,
                demand: dict[str, float] | None = None, roles: list[Role] | None = None) -> list[dict]:
    """n single-worker shifts drawn at random from the roles (the old 'shifts=N' order book)."""
    rng = random.Random(seed * 31 + n)
    roles = roles or default_roles()
    by_id = {r.id: r for r in roles}
    demand = demand or {"delivery": 0.3, "warehouse": 0.25, "support": 0.15, "retail": 0.15, "security": 0.08, "hospitality": 0.07}
    demand = {k: v for k, v in demand.items() if k in by_id} or {r.id: 1.0 for r in roles}
    ids, weights = zip(*demand.items())
    out = []
    for i in range(n):
        role = by_id[rng.choices(ids, weights)[0]]
        cs = cities or role.cities
        city = rng.choices(cs, [1.6 if c in _BIG else 1.0 for c in cs])[0]
        day = start + timedelta(days=rng.randrange(days))
        out.append(_seat(i + 1, role, canon_city(city), day, rng.choice(role.slots)))
    return out


def _interval(s: dict) -> tuple[datetime, datetime]:
    if s.get("start") and "T" in str(s["start"]):
        return datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
    st = datetime.fromisoformat(f"{s['date']}T{int(s.get('start_hour', 9)):02d}:00")
    return st, st + timedelta(hours=float(s.get("hours", 8)))


# ---- reading records -----------------------------------------------------------------------------------------------

def family_of(title: str | None) -> str | None:
    for r in default_roles():
        if role_fit(title, r):
            return r.id
    return None


def related_jobs(rec: dict, role: Role, today: date) -> tuple[list, float, float]:
    """(jobs in this line of work, years of it, years of any work) from the record."""
    pr = load_person(rec)
    jobs = [j for j in pr.current + pr.past if j.title and role_fit(j.title, role)]

    def yrs(js) -> float:
        return sum(max(0.0, ((j.end or today) - j.start).days / 365.25) for j in js if j.start)
    starts = [j.start for j in pr.current + pr.past if j.start]
    total = (today - min(starts)).days / 365.25 if starts else 0.0
    return jobs, round(yrs(jobs), 1), round(total, 1)


def fits(rec: dict, role: Role | str) -> tuple[bool, str | None, str | None]:
    """Does the record show a current or past role in this line of work? (fit, title, field path)"""
    if isinstance(role, str):
        role = next((r for r in default_roles() if r.id == role), None) or Role(title=role, cities=["Bangalore"], slots=[Slot(start="09:00", end="17:00")])
    pr = load_person(rec)
    for j in pr.current + pr.past:
        if j.title and role_fit(j.title, role):
            return True, f"{j.title} at {j.company}", f"{j.path}.title"
    return False, None, None


def _record_text(rec: dict) -> str:
    """Everything on the record a skill could show up in: skills, headline, titles, job descriptions."""
    pr = load_person(rec)
    parts = [*pr.skills, pr.headline or "", *(j.title or "" for j in pr.current + pr.past)]
    for side in ("current", "past"):
        for j in get_path(rec, f"experience.employment_details.{side}") or []:
            if isinstance(j, dict):
                parts.append(str(j.get("description") or ""))
    return " | ".join(p for p in parts if p)


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


# ---- applications: CSV in ------------------------------------------------------------------------------------------

CSV_COLUMNS = ["name", "profile_url", "email", "phone", "role", "city", "current_employer", "current_title", "start_date",
               "years_experience", "lives_in", "skills", "certifications", "languages", "availability", "max_shifts_per_week"]
_ALIASES = {
    "name": ["name", "full name", "full_name", "applicant", "candidate"],
    "profile_url": ["profile_url", "profile url", "linkedin", "linkedin url", "linkedin_url", "profile"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "mobile", "phone number", "contact", "whatsapp"],
    "role": ["role", "position", "applied for", "applied_for", "job", "role applied"],
    "city": ["city", "work city", "shift city", "location applied"],
    "current_employer": ["current_employer", "employer", "company", "current company"],
    "current_title": ["current_title", "title", "designation", "job title"],
    "start_date": ["start_date", "joined", "start date", "since"],
    "years_experience": ["years_experience", "experience", "years", "total experience", "experience years"],
    "lives_in": ["lives_in", "home city", "home_city", "current location", "residence"],
    "skills": ["skills"],
    "certifications": ["certifications", "certificates", "licences", "licenses", "documents"],
    "languages": ["languages", "language", "languages spoken"],
    "availability": ["availability", "days", "available days", "days available"],
    "max_shifts_per_week": ["max_shifts_per_week", "max shifts", "max_shifts", "shifts per week"],
}
MAX_ROWS = 10000


def _split(v: Any) -> list[str]:
    return [x.strip() for x in re.split(r"[;|,/]", str(v or "")) if x.strip()]


def parse_days(v: Any) -> list[int]:
    t = norm(v)
    if not t or t in ("all", "any", "anytime", "all days", "everyday", "every day", "7 days"):
        return list(range(7))
    if "weekend" in t and "weekday" not in t:
        return [5, 6]
    if t in ("weekdays", "mon fri", "monday friday"):
        return [0, 1, 2, 3, 4]
    names = {d.lower(): i for i, d in enumerate(WEEKDAYS)}
    found: set[int] = set()
    for a, b in re.findall(r"([a-z]{3})[a-z]*\s*(?:-|to)\s*([a-z]{3})[a-z]*", str(v).lower()):
        if a in names and b in names:
            i, j = names[a], names[b]
            found |= set(range(i, j + 1)) if i <= j else set(range(i, 7)) | set(range(0, j + 1))
    for w in re.findall(r"[a-z]{3}", t):
        if w in names:
            found.add(names[w])
    if "weekday" in t:
        found |= {0, 1, 2, 3, 4}
    return sorted(found) or list(range(7))


def _num(v: Any) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group()) if m else None


def parse_csv(text: str) -> tuple[list[dict], list[dict]]:
    """A CSV of applications -> (applications, row errors). Column names are matched loosely (LinkedIn, Mobile, ...)."""
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = csv.DictReader(io.StringIO(text), dialect=dialect)
    cols: dict[str, str] = {}
    for h in rows.fieldnames or []:
        k = norm(h).replace("_", " ")
        for want, names in _ALIASES.items():
            if want not in cols and k in [norm(n).replace("_", " ") for n in names]:
                cols[want] = h
    apps, errors = [], []
    if "name" not in cols:
        return [], [{"row": 1, "error": "no 'name' column (expected columns: " + ", ".join(CSV_COLUMNS) + ")"}]
    for i, row in enumerate(rows, start=2):
        if len(apps) >= MAX_ROWS:
            errors.append({"row": i, "error": f"only the first {MAX_ROWS} applications are read"})
            break
        g = lambda k: (row.get(cols[k]) or "").strip() if k in cols else ""  # noqa: E731
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue
        if not g("name"):
            errors.append({"row": i, "error": "no name"})
            continue
        claimed: dict[str, Any] = {}
        for k, src in (("employer", "current_employer"), ("title", "current_title"), ("start_date", "start_date"), ("location", "lives_in")):
            if g(src):
                claimed[k] = g(src)
        if claimed.get("start_date"):
            from ..verify.profile import parse_date
            d = parse_date(claimed["start_date"])
            claimed["start_date"] = d.isoformat() if d else claimed["start_date"]
        if _num(g("years_experience")) is not None:
            claimed["years_experience"] = _num(g("years_experience"))
        cap = _num(g("max_shifts_per_week"))
        apps.append({
            "id": f"app{len(apps) + 1:04d}", "row": i, "name": g("name"), "profile_url": g("profile_url"),
            "email": g("email"), "phone": g("phone"), "role": g("role"), "city": canon_city(g("city") or g("lives_in")) if (g("city") or g("lives_in")) else "",
            "claimed": claimed, "skills": _split(g("skills")), "certifications": _split(g("certifications")),
            "languages": _split(g("languages")), "availability": parse_days(g("availability")),
            "max_shifts_per_week": int(min(7, max(1, cap))) if cap else 5,
        })
    return apps, errors


def to_csv(apps: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for a in apps:
        c = a.get("claimed") or {}
        w.writerow([a.get("name"), a.get("profile_url"), a.get("email", ""), a.get("phone", ""), a.get("role_title") or a.get("role"),
                    a.get("city"), c.get("employer", ""), c.get("title", ""), c.get("start_date", ""), c.get("years_experience", ""),
                    c.get("location", ""), "; ".join(a.get("skills") or []), "; ".join(a.get("certifications") or []),
                    "; ".join(a.get("languages") or []), " ".join(WEEKDAYS[d] for d in a.get("availability") or []),
                    a.get("max_shifts_per_week", "")])
    return buf.getvalue()


# ---- test mode: seeding applications (real people, planted lies and repeats, an answer key kept aside) -------------

LIE_TYPES = ("stale_current_job", "fake_employer", "inflated_title", "stretched_tenure", "inflated_experience",
             "wrong_location", "identity_mismatch", "ghost_profile")
FAMOUS = ["Amazon", "Flipkart", "Swiggy", "Zomato", "Reliance Retail", "Taj Hotels", "Starbucks", "DMart", "Blinkit", "Zepto"]
OTHER_NAMES = ["Rohit Kumar", "Pooja Sharma", "Amit Singh", "Neha Gupta", "Suresh Reddy", "Kavya Nair", "Imran Khan",
               "Deepa Iyer", "Vikram Patel", "Sneha Joshi", "Arjun Das", "Fatima Shaikh"]


def _inflate(title: str, record_rank: int) -> str | None:
    base = re.sub(r"\b(senior|sr\.?|junior|jr\.?|lead|trainee|associate)\b", "", title, flags=re.I).strip(" ,-") or title
    if record_rank < 2:
        return f"Senior {base} Team Lead"
    if record_rank < 4:
        return f"Head of {base}"
    return None


def _plant(kind: str, rec: dict, app: dict, rng: random.Random, today: date, cities: list[str]) -> str | None:
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
        others = [x for x in cities if x != home]
        if home and others:
            other = rng.choice(others)
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
        alias = sorted(ALL_CITIES.get(home, {home.lower()}))
        c["location"] = rng.choice(alias).title() if rng.random() < 0.5 else home
    return c


def _contact(name: str, rng: random.Random) -> tuple[str, str]:
    slug = re.sub(r"[^a-z]+", ".", _plain(name).lower()).strip(".") or "applicant"
    return f"{slug}{rng.randint(10, 9999)}@example.com", f"9{rng.randint(0, 999_999_999):09d}"


def _repeat(app: dict, rng: random.Random, new_id: str) -> dict:
    """The same person applying again: same profile written differently, phone and email formatted differently."""
    a = copy.deepcopy(app)
    a["id"] = new_id
    u = a["profile_url"] or ""
    a["profile_url"] = rng.choice([u.replace("https://www.", "http://") + "/", u.upper().replace("HTTPS://", "https://"), u + "?utm_source=jobboard"])
    a["email"] = (a.get("email") or "").upper() if rng.random() < 0.5 else a.get("email")
    p = a.get("phone") or ""
    a["phone"] = f"+91 {p[:5]} {p[5:]}" if p else p
    a["availability"] = sorted(set(a["availability"]) | {rng.randrange(7)})
    return a


def _pick_role(rec: dict, roles: list[Role], rng: random.Random) -> Role | None:
    pr = load_person(rec)
    home = city_of(pr.location, [c for r in roles for c in r.cities])
    if not home:
        return None
    here = [r for r in roles if home in r.cities]
    title = pr.current[0].title if pr.current else None
    fam = rec.get("_family")
    fit = [r for r in here if role_fit(title, r) or (fam and r.id == fam)]
    if fit:
        return rng.choice(fit)
    open_to_all = [r for r in here if not r.related_experience]
    return rng.choice(open_to_all) if open_to_all and rng.random() < 0.3 else None


def seed_applications(pool: list[dict], *, roles: list[Role] | None = None, fake_rate: float = 0.15, seed: int = 7,
                      today: date | None = None, limit: int | None = None, duplicate_rate: float = 0.0
                      ) -> tuple[list[dict], dict[str, dict]]:
    """Applications from real records for these roles: a `fake_rate` share with one planted lie, and a
    `duplicate_rate` share of honest applicants who apply twice. Returns (applications, answer_key)."""
    today = today or date.today()
    roles = roles or default_roles()
    staffed = list(dict.fromkeys(c for r in roles for c in r.cities))
    rng = random.Random(seed)
    usable = []
    for rec in pool:
        pr = load_person(rec)
        if not (pr.profile_url and pr.name and pr.current):
            continue
        role = _pick_role(rec, roles, rng)
        if role:
            usable.append((rec, pr, role))
    rng.shuffle(usable)
    if limit:
        usable = usable[:limit]
    n_fake = round(len(usable) * fake_rate)
    fake_idx = set(rng.sample(range(len(usable)), n_fake)) if usable else set()
    apps, key = [], {}
    kinds = list(LIE_TYPES)
    for i, (rec, pr, role) in enumerate(usable):
        email, phone = _contact(pr.name, rng)
        app = {"id": f"app{i + 1:04d}", "name": pr.name, "profile_url": pr.profile_url, "email": email, "phone": phone,
               "role": role.id, "role_title": role.title, "city": city_of(pr.location, staffed), "claimed": _honest_claims(rec, rng, today),
               # an honest applicant has the papers and languages the role asks for, most of the time
               "certifications": [c for c in role.certifications if rng.random() < 0.94],
               "languages": [lang for lang in role.languages if rng.random() < 0.96],
               "skills": [s for s in role.skills if rng.random() < 0.95],
               "availability": sorted(rng.sample(range(7), rng.randint(3, 6))), "max_shifts_per_week": rng.randint(2, 5)}
        entry: dict[str, Any] = {"fake": False}
        if i in fake_idx:
            for kind in rng.sample(kinds, len(kinds)):
                truth = _plant(kind, rec, app, rng, today, staffed)
                if truth:
                    entry = {"fake": True, "lie": kind, "truth": truth, "real_name": pr.name}
                    break
        apps.append(app)
        key[app["id"]] = entry
    honest = [a for a in apps if not key[a["id"]]["fake"]]
    for orig in rng.sample(honest, min(len(honest), round(len(apps) * duplicate_rate))):
        dup = _repeat(orig, rng, f"app{len(apps) + 1:04d}")
        apps.insert(rng.randrange(apps.index(orig) + 1, len(apps) + 1), dup)
        key[dup["id"]] = {"fake": False, "duplicate_of": orig["id"]}
    return apps, key


# ---- dedupe --------------------------------------------------------------------------------------------------------

def _phone(p: Any) -> str:
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


def find_duplicates(apps: list[dict]) -> tuple[dict[str, str], dict[str, tuple[str, str, str]]]:
    """Group applications by person (same profile URL, phone or email). Returns
    (app_id -> person id, app_id -> (outcome, kind, reason) for the ones not to screen)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owner: dict[str, str] = {}
    via_contact: set[str] = set()
    for a in apps:
        parent.setdefault(a["id"], a["id"])
        keys = [("u", norm_url(a.get("profile_url")))] + [("e", (a.get("email") or "").strip().lower()), ("p", _phone(a.get("phone")))]
        for kind, k in keys:
            if not k:
                continue
            if (kind, k) in owner:
                o = owner[(kind, k)]
                if kind != "u":
                    via_contact.add(find(o))
                    via_contact.add(find(a["id"]))
                parent[find(a["id"])] = find(o)
            else:
                owner[(kind, k)] = a["id"]
    clusters: dict[str, list[dict]] = defaultdict(list)
    for a in apps:
        clusters[find(a["id"])].append(a)
    person: dict[str, str] = {}
    skip: dict[str, tuple[str, str, str]] = {}
    for root, group in clusters.items():
        pid = group[0]["id"]
        for a in group:
            person[a["id"]] = pid
        if len(group) == 1:
            continue
        # different people behind one phone or email: hold every one of them for a recruiter
        people: list[list[dict]] = []
        for a in group:
            for p in people:
                if names_match(a.get("name"), p[0].get("name")) or norm_url(a.get("profile_url")) == norm_url(p[0].get("profile_url")):
                    p.append(a)
                    break
            else:
                people.append([a])
        contact_linked = any(find(a["id"]) in via_contact for a in group)
        if len(people) > 1 and contact_linked and any(
                norm_url(p[0].get("profile_url")) != norm_url(q[0].get("profile_url")) for p in people for q in people):
            names = ", ".join(f"{p[0]['name']} ({p[0]['id']})" for p in people[:4])
            for a in group:
                skip[a["id"]] = ("flagged", "shared_contact", f"One phone or email behind {len(people)} different applicants: {names}")
            continue
        for p in people:
            seen_roles: dict[str, str] = {}
            for a in p:
                r = norm(a.get("role"))
                if r in seen_roles:
                    skip[a["id"]] = ("duplicate", "repeat_application", f"Already applied as {seen_roles[r]} for the same role")
                else:
                    seen_roles[r] = a["id"]
    return person, skip


# ---- screening -----------------------------------------------------------------------------------------------------

@dataclass
class Screening:
    app_id: str
    name: str
    profile_url: str
    role: str
    city: str | None
    outcome: str                     # cleared | flagged | not_qualified | duplicate | held
    reason: str
    kind: str | None = None          # identity_unverifiable | identity_mismatch | false_claim | shared_contact |
                                     # role_mismatch | under_experience | over_experience | missing_requirement |
                                     # role_not_open | wrong_city | repeat_application | needs_lookup | lookup_failed
    claims: list[Claim] = field(default_factory=list)
    record_name: str | None = None
    home_city: str | None = None
    checks: list[str] = field(default_factory=list)   # what to confirm at onboarding (self-reported papers, languages)
    person: str | None = None

    def dump(self) -> dict:
        return {"app_id": self.app_id, "name": self.name, "profile_url": self.profile_url, "role": self.role,
                "city": self.city, "outcome": self.outcome, "reason": self.reason, "kind": self.kind,
                "record_name": self.record_name, "home_city": self.home_city, "checks": self.checks, "person": self.person,
                "claims": [c.model_dump() for c in self.claims]}


def _claim(s: Screening, text: str, status: str, evidence: str, ep: str, fld: str | None, url: str | None) -> None:
    s.claims.append(Claim(id=f"k{len(s.claims) + 1}", claim=text, status=status, evidence=evidence,
                          source=Source(endpoint=ep, field=fld, url=url or None)))


async def screen(app: dict, graph: PoolGraph, today: date, role: Role | None = None, *, missing_is_final: bool = True,
                 cities: list[str] | None = None) -> Screening:
    if role is None:
        role = resolve_role(app.get("role"), default_roles())
    s = Screening(app["id"], app.get("name") or "", app.get("profile_url") or "", role.id if role else (app.get("role") or ""),
                  canon_city(app["city"]) if app.get("city") else None, "flagged", "", None)
    if role is None:
        s.outcome, s.kind, s.reason = "not_qualified", "role_not_open", f"Applied for '{app.get('role') or 'no role'}', which isn't one of the open roles"
        return s
    url = s.profile_url
    if not url:
        s.outcome, s.kind, s.reason = "held", "needs_lookup", "No profile URL on the application, so identity can't be checked yet"
        return s
    try:
        rec = await graph.person(url)
    except Exception as e:  # noqa: BLE001 - a lookup failure holds the application, it never clears it
        log.warning("staffing: lookup failed for %s: %s", url, e)
        s.outcome, s.kind, s.reason = "held", "lookup_failed", f"Crustdata lookup failed ({type(e).__name__}); try again"
        return s
    if rec is None:
        if not missing_is_final:
            s.outcome, s.kind, s.reason = "held", "needs_lookup", "Not in the recorded Crustdata data; turn on live lookups to check this profile"
            return s
        s.kind, s.reason = "identity_unverifiable", f"No Crustdata record for {url}; identity can't be confirmed"
        _claim(s, f"Profile {url}", "unverifiable", "no Person record for this URL", "person/enrich", None, url)
        return s
    pr = load_person(rec)
    ep = pr.endpoint
    known = list(dict.fromkeys([*(cities or []), *role.cities]))
    s.record_name, s.home_city = pr.name, city_of(pr.location, known)
    if not names_match(s.name, pr.name):
        s.kind, s.reason = "identity_mismatch", f"Applied as {s.name}, but this profile belongs to {pr.name}"
        _claim(s, f"Name: {s.name}", "contradicted", f"record name is {pr.name}", ep, pr.name_field, url)
        return s
    claimed = {k: v for k, v in (app.get("claimed") or {}).items() if k != "location"}
    claimed["_source"] = f"application {app['id']}"
    claims, _flags = await verify_candidate({**rec, "claimed": claimed}, None, Criteria(role=role.title), None, today=today)
    s.claims = [c for c in claims if not c.claim.startswith(("Career:", "Progression", "Based in"))]
    # Shift workers count internships and student jobs in their years of experience; the verifier doesn't. Only a
    # claim beyond the record even counting those is a lie.
    starts = [j.start for j in pr.current + pr.past if j.start]
    for c in s.claims:
        m = re.match(r"(\d+(?:\.\d+)?) yrs of experience", c.claim)
        if m and c.status == "contradicted" and starts and "internship" in (c.evidence or ""):
            all_yrs = (today - min(starts)).days / 365.25
            if float(m.group(1)) <= all_yrs + 1:
                c.status, c.evidence = "verified", f"{c.evidence}; counting those, the record shows {all_yrs:.1f} yrs"
    # Home city: shifts are staffed locally, so the city on the application must be the record's city.
    want = canon_city(app.get("claimed", {}).get("location") or s.city) if (app.get("claimed", {}).get("location") or s.city) else None
    if not s.home_city:
        _claim(s, f"Lives in {want or 'an unstated city'}", "unverifiable", f"record location '{pr.location or 'none'}' doesn't name a city we staff",
               ep, pr.location_field, url)
    elif want and want != s.home_city:
        _claim(s, f"Lives in {want}", "contradicted", f"record says {pr.location}", ep, pr.location_field, url)
    else:
        _claim(s, f"Lives in {s.home_city}", "verified", f"record says {pr.location}", ep, pr.location_field, url)
    bad = [c for c in s.claims if c.status == "contradicted"]
    if bad:
        s.kind, s.reason = "false_claim", "; ".join(f"{c.claim} ({c.evidence})" for c in bad[:3])
        return s
    s.outcome = "not_qualified"
    if not s.city:
        s.city = s.home_city
    if s.city not in role.cities:
        s.kind, s.reason = "role_not_open", f"{role.title} isn't open in {s.city or 'an unstated city'} (open in {', '.join(role.cities)})"
        return s
    if s.home_city and s.home_city != s.city:
        s.kind, s.reason = "wrong_city", f"Lives in {s.home_city} but applied for shifts in {s.city}"
        return s
    # Fit: the role's own requirements.
    jobs, rel_yrs, total_yrs = related_jobs(rec, role, today)
    what = f"{jobs[0].title} at {jobs[0].company}" if jobs else None
    fld = f"{jobs[0].path}.title" if jobs else "experience.employment_details"
    if role.related_experience:
        _claim(s, f"Has done {role.title.lower()} work", "verified" if jobs else "unverifiable",
               (what + (f" ({rel_yrs:g} yrs of it)" if rel_yrs else "")) if jobs else "no current or past role in this line of work", ep, fld, url)
        if not jobs:
            s.kind, s.reason = "role_mismatch", f"No {role.title.lower()} role on the record"
            return s
    have = rel_yrs if role.related_experience else total_yrs
    if role.min_years and have < role.min_years:
        s.kind, s.reason = "under_experience", f"{have:g} yrs of {'related ' if role.related_experience else ''}work on the record; {role.title} needs {role.min_years:g}"
        return s
    if role.max_years is not None and total_yrs > role.max_years:
        s.kind, s.reason = "over_experience", f"{total_yrs:g} yrs of work on the record; {role.title} is for at most {role.max_years:g}"
        return s
    text = _record_text(rec)
    missing = []
    for skill in role.skills:
        alts = [x.strip() for x in re.split(r"\bor\b|/", skill) if x.strip()]
        if any(_hit(text, x) for x in alts):
            _claim(s, f"Skill: {skill}", "verified", "on the record", ep, pr.skills_field or pr.headline_field, url)
        elif any(norm(x) in norm(" ".join(app.get("skills") or [])) for x in alts):
            _claim(s, f"Skill: {skill}", "unverifiable", "the applicant says so; not on the record", "application", None, None)
            s.checks.append(f"Test {skill.lower()} at onboarding")
        else:
            missing.append(skill)
    for cert in role.certifications:
        if any(norm(cert) == norm(x) or norm(x) in norm(cert) or norm(cert) in norm(x) for x in app.get("certifications") or []):
            s.checks.append(f"See the {cert} document at onboarding")
        else:
            missing.append(cert)
    for lang in role.languages:
        if any(norm(lang) == norm(x) for x in app.get("languages") or []):
            s.checks.append(f"Confirm {lang} at the interview") if len(role.languages) <= 2 else None
        else:
            missing.append(f"speaks {lang}")
    if missing:
        s.kind, s.reason = "missing_requirement", "Missing: " + ", ".join(missing)
        return s
    s.outcome, s.reason = "cleared", "Identity and claims check out" + (f"; {what}" if what else "")
    return s


# ---- assignment: no double-booking, a backup bench -----------------------------------------------------------------

class Rota:
    """Shifts, cleared workers, who works what, and who is on standby.

    workers: {id (application), person, role, city, availability [weekday ints], max_shifts_per_week, name}
    One person can hold several applications (different roles) but is never booked on two shifts that overlap or are
    closer than `rest_hours`, and never past their weekly cap, across all their roles."""

    def __init__(self, shifts: list[dict], workers: list[dict], rest_hours: float = 10):
        self.shifts = {s["id"]: s for s in shifts}
        self.order = [s["id"] for s in shifts]
        self.workers = {w["id"]: {**w, "person": w.get("person") or w["id"]} for w in workers}
        self.rest = timedelta(hours=rest_hours)
        self.iv = {sid: _interval(s) for sid, s in self.shifts.items()}
        self.by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
        for w in self.workers.values():
            self.by_key[(w["role"], w["city"])].append(w["id"])
        caps: dict[str, int] = {}
        for w in self.workers.values():
            caps[w["person"]] = min(caps.get(w["person"], 99), int(w.get("max_shifts_per_week") or 3))
        self.cap = caps
        self.filled: dict[str, str] = {}
        self.why: dict[str, str] = {}
        self.busy: dict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
        self.week: Counter = Counter()
        self.load: Counter = Counter()
        self.bench: dict[str, list[str]] = {}
        self.standby: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        self.no_shows: dict[str, str] = {}
        self.backfills: list[dict] = []

    @staticmethod
    def group(s: dict) -> str:
        return f"{s['role']}|{s['city']}|{s.get('start') or s['date']}"

    def _wk(self, sid: str) -> tuple[int, int]:
        return tuple(self.iv[sid][0].isocalendar()[:2])  # type: ignore[return-value]

    def _clash(self, spans, st: datetime, en: datetime) -> bool:
        return any(st < e + self.rest and b < en + self.rest for b, e, *_ in spans)

    def free(self, wid: str, sid: str) -> bool:
        p = self.workers[wid]["person"]
        st, en = self.iv[sid]
        return not self._clash(self.busy[p], st, en) and self.week[(p, self._wk(sid))] < self.cap[p]

    def eligible(self, sid: str) -> list[str]:
        s = self.shifts[sid]
        wd = self.iv[sid][0].weekday()
        return [w for w in self.by_key.get((s["role"], s["city"]), []) if wd in (self.workers[w].get("availability") or range(7))]

    def book(self, sid: str, wid: str) -> None:
        p = self.workers[wid]["person"]
        st, en = self.iv[sid]
        self.filled[sid] = wid
        self.why.pop(sid, None)
        self.busy[p].append((st, en, sid))
        self.week[(p, self._wk(sid))] += 1
        self.load[p] += 1

    def unbook(self, sid: str) -> str | None:
        wid = self.filled.pop(sid, None)
        if wid:
            p = self.workers[wid]["person"]
            self.busy[p] = [b for b in self.busy[p] if b[2] != sid]
            self.week[(p, self._wk(sid))] -= 1
            self.load[p] -= 1
        return wid

    def assign(self) -> None:
        """Greedy, scarcest shift first, least-loaded person first."""
        pool = {sid: self.eligible(sid) for sid in self.order}
        for sid in sorted(self.order, key=lambda i: (len(pool[i]), self.iv[i][0], i)):
            s = self.shifts[sid]
            if not self.by_key.get((s["role"], s["city"])):
                self.why[sid] = f"no cleared {s.get('role_label', s['role']).lower()} in {s['city']}"
                continue
            if not pool[sid]:
                self.why[sid] = f"no cleared worker free on {s['weekday']}s"
                continue
            free = [w for w in pool[sid] if self.free(w, sid)]
            if not free:
                self.why[sid] = "every eligible worker already booked at that time or at their weekly cap"
                continue
            self.book(sid, min(free, key=lambda w: (self.load[self.workers[w]["person"]], w)))

    def fill_bench(self, rate: float) -> dict:
        """Standby workers for each shift time: ceil(rate x seats), each free then, under their cap, and not on standby
        for another shift that overlaps."""
        self.bench = {}
        self.standby = defaultdict(list)
        if rate <= 0:
            return self.bench_summary(rate)
        groups: dict[str, list[str]] = defaultdict(list)
        for sid in self.order:
            groups[self.group(self.shifts[sid])].append(sid)
        for g, sids in sorted(groups.items(), key=lambda kv: self.iv[kv[1][0]][0]):
            want = math.ceil(len(sids) * rate)
            sid = sids[0]
            st, en = self.iv[sid]
            booked_here = {self.workers[self.filled[x]]["person"] for x in sids if x in self.filled}
            cands = [w for w in self.eligible(sid) if self.workers[w]["person"] not in booked_here and self.free(w, sid)
                     and not self._clash([(b, e) for b, e in self.standby[self.workers[w]["person"]]], st, en)]
            picked: list[str] = []
            for w in sorted(cands, key=lambda w: (self.load[self.workers[w]["person"]], len(self.standby[self.workers[w]["person"]]), w)):
                p = self.workers[w]["person"]
                if len(picked) >= want:
                    break
                if any(self.workers[x]["person"] == p for x in picked):
                    continue
                picked.append(w)
                self.standby[p].append((st, en))
            self.bench[g] = picked
        return self.bench_summary(rate)

    def bench_summary(self, rate: float) -> dict:
        groups: dict[str, int] = Counter(self.group(self.shifts[sid]) for sid in self.order)
        wanted = sum(math.ceil(n * rate) for n in groups.values()) if rate > 0 else 0
        found = sum(len(v) for v in self.bench.values())
        covered = sum(1 for g in groups if self.bench.get(g))
        return {"rate": rate, "shift_times": len(groups), "standby_wanted": wanted, "standby_found": found,
                "shift_times_covered": covered, "coverage": round(found / wanted, 4) if wanted else None,
                "people_on_standby": len({self.workers[w]["person"] for v in self.bench.values() for w in v})}

    def no_show(self, sid: str) -> dict:
        """The booked worker didn't turn up: take the first free standby for that shift time, else anyone eligible."""
        s = self.shifts[sid]
        gone = self.unbook(sid)
        if gone:
            self.no_shows[sid] = gone
        g = self.group(s)
        out = {"shift": sid, "no_show": gone, "backup": None, "from": None}
        for w in list(self.bench.get(g, [])):
            if self.free(w, sid) and (not gone or self.workers[w]["person"] != self.workers[gone]["person"]):
                self.bench[g].remove(w)
                self.book(sid, w)
                out.update(backup=w, **{"from": "bench"})
                break
        else:
            free = [w for w in self.eligible(sid) if self.free(w, sid) and (not gone or self.workers[w]["person"] != self.workers[gone]["person"])]
            if free:
                w = min(free, key=lambda w: (self.load[self.workers[w]["person"]], w))
                self.book(sid, w)
                out.update(backup=w, **{"from": "pool"})
            else:
                self.why[sid] = "no-show, and nobody on the bench or in the pool is free"
        self.backfills.append(out)
        return out

    def double_bookings(self) -> list[dict]:
        """An independent audit of the final roster: any person on two shifts that overlap (or closer than the rest gap)."""
        by_person: dict[str, list[str]] = defaultdict(list)
        for sid, wid in self.filled.items():
            by_person[self.workers[wid]["person"]].append(sid)
        bad = []
        for p, sids in by_person.items():
            sids.sort(key=lambda x: self.iv[x][0])
            for a, b in zip(sids, sids[1:]):
                if self.iv[b][0] < self.iv[a][1] + self.rest:
                    bad.append({"person": p, "shifts": [a, b]})
        return bad

    def roster(self) -> list[dict]:
        out = []
        for sid in self.order:
            s = self.shifts[sid]
            wid = self.filled.get(sid)
            out.append({**s, "worker": wid, "worker_name": self.workers[wid].get("name") if wid else None,
                        "person": self.workers[wid]["person"] if wid else None, "open_reason": self.why.get(sid),
                        "no_show": self.no_shows.get(sid),
                        "bench": [{"worker": w, "name": self.workers[w].get("name")} for w in self.bench.get(self.group(s), [])]})
        return out


def assign(shifts: list[dict], workers: list[dict], rest_hours: float = 10) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (shift_id -> worker_id, shift_id -> why it stayed open)."""
    r = Rota(shifts, workers, rest_hours)
    r.assign()
    return r.filled, r.why


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
    dups = {a: k["duplicate_of"] for a, k in key.items() if k.get("duplicate_of")}
    dup_caught = [a for a, o in dups.items() if "duplicate" in (by_id.get(a, Screening(a, "", "", "", None, "", "")).outcome,
                                                               by_id.get(o, Screening(o, "", "", "", None, "", "")).outcome)]
    return {
        "applications": len(screens), "fakes_planted": len(fakes), "flagged": len(flagged),
        "true_positives": tp, "false_positives": fp, "false_negatives": fn,
        "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
        "by_lie_type": dict(sorted(per.items())),
        "fakes_staffed": sorted(a for a in staffed_workers if a in fakes),
        "missed": [{"app_id": a, **key[a], "outcome": by_id[a].outcome} for a in sorted(fakes - flagged) if a in by_id],
        "false_alarms": [{"app_id": a, "reason": by_id[a].reason} for a in sorted(flagged - fakes) if a in by_id],
        "duplicates_planted": len(dups), "duplicates_caught": len(dup_caught),
        "duplicates_missed": sorted(set(dups) - set(dup_caught)),
    }


async def _prefetch(apps: list[dict], graph: PoolGraph, client: Any, limit: int, emit: Emit) -> tuple[set[str], int]:
    """Look up, live and in parallel (the client batches them), the profiles the recorded data doesn't have. Capped."""
    if client is None or limit <= 0:
        return set(), 0
    todo = list(dict.fromkeys(norm_url(a["profile_url"]) for a in apps if a.get("profile_url")
                              and norm_url(a["profile_url"]) not in graph.records))[:limit]
    if not todo:
        return set(), 0
    await emit({"type": "step", "step": "lookup", "message": f"Looking up {len(todo)} profiles on Crustdata (not in the recorded data)",
                "data": {"lookups": len(todo)}})
    live = PoolGraph(graph.records, client)
    failed: set[str] = set()

    async def one(u: str) -> None:
        try:
            rec = await live.person(u if u.startswith("http") else f"https://{u}")
            if rec is not None:
                graph.add(rec)
                graph.records[u] = graph.records.get(u) or rec
        except Exception as e:  # noqa: BLE001
            log.warning("staffing: live lookup failed for %s: %s", u, e)
            failed.add(u)
    await asyncio.gather(*(one(u) for u in todo))
    return set(todo) - failed, len(todo)


async def run_staffing(applications: list[dict], shifts: list[dict], graph: PoolGraph, *, roles: list[Role] | None = None,
                       today: date | None = None, answer_key: dict[str, dict] | None = None, emit: Emit = _noop,
                       closed_world: bool = True, client: Any = None, max_live_lookups: int = 0, bench_rate: float = 0.1,
                       rest_hours: float = 10, no_show_rate: float | None = None, seed: int = 7) -> dict:
    """closed_world: the recorded data is the whole world, so a profile missing from it has no Crustdata record (test
    mode). Otherwise a missing profile is held, or looked up live when `client` and `max_live_lookups` allow."""
    today = today or date.today()
    roles = roles or default_roles()
    by_role = {r.id: r for r in roles}
    cities = list(dict.fromkeys(c for r in roles for c in r.cities))
    await emit({"type": "step", "step": "ingest", "message": f"{len(applications)} applications for {len(shifts)} shifts across {len(roles)} roles",
                "data": {"applications": len(applications), "shifts": len(shifts), "roles": len(roles)}})
    person, skip = find_duplicates(applications)
    n_dup = sum(1 for v in skip.values() if v[0] == "duplicate")
    n_shared = sum(1 for v in skip.values() if v[1] == "shared_contact")
    await emit({"type": "step", "step": "dedupe", "message": f"{len(set(person.values()))} people: {n_dup} repeat applications merged"
                + (f", {n_shared} sharing one phone or email held" if n_shared else ""),
                "data": {"people": len(set(person.values())), "duplicates": n_dup, "shared_contact": n_shared}})
    looked_up, n_live = set(), 0
    if not closed_world:
        looked_up, n_live = await _prefetch([a for a in applications if a["id"] not in skip], graph, client, max_live_lookups, emit)
    offline = PoolGraph(graph.records, None)
    screens: list[Screening] = []
    for i, app in enumerate(applications):
        role = by_role.get(app.get("role")) or resolve_role(app.get("role"), roles)
        if app["id"] in skip:
            outcome, kind, reason = skip[app["id"]]
            s = Screening(app["id"], app.get("name") or "", app.get("profile_url") or "", role.id if role else (app.get("role") or ""),
                          app.get("city"), outcome, reason, kind)
        else:
            final = closed_world or norm_url(app.get("profile_url")) in looked_up
            s = await screen(app, offline, today, role, missing_is_final=final, cities=cities)
        s.person = person.get(app["id"])
        screens.append(s)
        if (i + 1) % 100 == 0 or i + 1 == len(applications):
            c = Counter(x.outcome for x in screens)
            await emit({"type": "step", "step": "screen", "message": f"Screened {i + 1}/{len(applications)}: "
                        f"{c['cleared']} cleared, {c['flagged']} flagged, {c['not_qualified']} not qualified"
                        + (f", {c['duplicate']} duplicates" if c["duplicate"] else "") + (f", {c['held']} held" if c["held"] else ""),
                        "data": dict(c, done=i + 1)})
        if s.outcome == "flagged":
            await emit({"type": "flagged", "screening": s.dump()})
    by_app = {a["id"]: a for a in applications}
    workers = [{"id": s.app_id, "person": s.person, "role": s.role, "city": s.city, "name": by_app[s.app_id].get("name"),
                "availability": by_app[s.app_id].get("availability") or list(range(7)),
                "max_shifts_per_week": by_app[s.app_id].get("max_shifts_per_week") or 3}
               for s in screens if s.outcome == "cleared"]
    rota = Rota(shifts, workers, rest_hours)
    rota.assign()
    filled = dict(rota.filled)
    fill = len(filled) / len(shifts) if shifts else 0.0
    await emit({"type": "step", "step": "assign", "message": f"Filled {len(filled)}/{len(shifts)} shifts ({fill:.1%}) with {len({rota.workers[w]['person'] for w in filled.values()})} people",
                "data": {"filled": len(filled), "shifts": len(shifts)}})
    bench = rota.fill_bench(bench_rate)
    if bench_rate > 0:
        await emit({"type": "step", "step": "bench", "message": f"{bench['standby_found']} standby slots for no-shows ({bench['people_on_standby']} people), "
                    f"{bench['shift_times_covered']}/{bench['shift_times']} shift times covered", "data": {k: v for k, v in bench.items() if isinstance(v, (int, float))}})
    clashes = rota.double_bookings()
    agg_city: dict[str, Counter] = defaultdict(Counter)
    agg_role: dict[str, Counter] = defaultdict(Counter)
    for s in shifts:
        k = "filled" if s["id"] in filled else "open"
        agg_city[s["city"]][k] += 1
        agg_role[s["role"]][k] += 1
    applied = Counter(s.role for s in screens)
    cleared = Counter(s.role for s in screens if s.outcome == "cleared")
    checks = Counter(c for s in screens if s.outcome == "cleared" for c in s.checks)
    report = {
        "today": today.isoformat(),
        "screening": {k: Counter(s.outcome for s in screens).get(k, 0) for k in ("cleared", "flagged", "not_qualified", "duplicate", "held")},
        "flag_kinds": dict(Counter(s.kind for s in screens if s.outcome == "flagged")),
        "not_qualified_kinds": dict(Counter(s.kind for s in screens if s.outcome == "not_qualified")),
        "held_kinds": dict(Counter(s.kind for s in screens if s.outcome == "held")),
        "shifts": len(shifts), "filled": len(filled), "fill_rate": round(fill, 4),
        "workers_used": len({rota.workers[w]["person"] for w in filled.values()}), "workers_cleared": len({w["person"] for w in workers}),
        "people": len(set(person.values())),
        "duplicates": {"repeat_applications": n_dup, "shared_contact": n_shared},
        "double_bookings": len(clashes), "rest_hours": rest_hours,
        "bench": bench,
        "lookups": {"recorded": len(graph.records), "live": n_live},
        "onboarding_checks": {"workers": sum(1 for s in screens if s.outcome == "cleared" and s.checks), "top": dict(checks.most_common(6))},
        "roles": {r.id: {"title": r.title, "cities": r.cities, "slots": [x.label for x in r.slots], "needs": r.needs(),
                         "seats": agg_role[r.id]["filled"] + agg_role[r.id]["open"], "filled": agg_role[r.id]["filled"],
                         "applied": applied[r.id], "cleared": cleared[r.id]} for r in roles},
        "by_city": {c: dict(v, fill_rate=_ratio(v["filled"], v["filled"] + v["open"])) for c, v in sorted(agg_city.items())},
        "by_role": {r: dict(v, fill_rate=_ratio(v["filled"], v["filled"] + v["open"])) for r, v in sorted(agg_role.items())},
        "open_reasons": dict(Counter(rota.why.values()).most_common()),
    }
    if answer_key is not None:
        report["fake_catch"] = score(screens, answer_key, filled)
    if no_show_rate:
        drill = copy.deepcopy(rota)
        rng = random.Random(seed * 17 + 3)
        booked = sorted(drill.filled)
        out = [drill.no_show(sid) for sid in sorted(rng.sample(booked, round(len(booked) * no_show_rate)), key=lambda x: drill.iv[x][0])]
        report["no_show_drill"] = {"rate": no_show_rate, "no_shows": len(out), "from_bench": sum(o["from"] == "bench" for o in out),
                                   "from_pool": sum(o["from"] == "pool" for o in out), "uncovered": sum(o["backup"] is None for o in out),
                                   "double_bookings_after": len(drill.double_bookings())}
    await emit({"type": "done", "report": report})
    return {"report": report, "roster": rota.roster(), "screenings": [s.dump() for s in screens], "rota": rota}


def search_cities(cities: list[str]) -> list[str]:
    """Role cities -> the spellings Crustdata's location.city filter matches ('Delhi NCR' -> Delhi, Gurgaon, Noida)."""
    out: list[str] = []
    for c in cities:
        c = canon_city(c)
        out += {"Delhi NCR": ["Delhi", "Gurgaon", "Noida"], "Kochi": ["Kochi", "Cochin", "Ernakulam"],
                "Chennai": ["Chennai"], "Kolkata": ["Kolkata"], "Chandigarh": ["Chandigarh", "Mohali"]}.get(c, [c])
    return list(dict.fromkeys(out))


def search_titles(role: Role) -> list[str]:
    return role.search_titles or ROLE_FAMILIES.get(role.id, {}).get("titles") or [k for k in role.keywords if len(k) > 3][:8]


async def fetch_shift_pool(client: Any, per_role: int = 200, roles: list[str] | list[Role] | None = None,
                           progress: Callable[[str, int], Awaitable[None]] | None = None) -> list[dict]:
    """Real applicants from Crustdata: one paged Person Search per role (its search titles, in its cities)."""
    out: list[dict] = []
    seen: set[str] = set()
    rs = [r if isinstance(r, Role) else next(x for x in default_roles() if x.id == r) for r in (roles or default_roles())]
    for role in rs:
        f = all_of(title_filter(search_titles(role)), city_filter(search_cities(role.cities)))
        try:
            rows = await fetch_pool(client, f, per_role)
        except Exception as e:  # noqa: BLE001 - one role failing leaves the others
            log.warning("staffing pool: %s search failed: %s", role.id, e)
            rows = []
        n = 0
        for r in rows:
            u = norm_url(load_person(r).profile_url)
            if u and u not in seen:
                seen.add(u)
                out.append({**r, "_family": role.id})
                n += 1
        if progress:
            await progress(role.id, n)
    return out
