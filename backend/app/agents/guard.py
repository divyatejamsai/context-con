"""Send Guard (WS7): the pre-send firewall an agent calls before any outbound message leaves.

    verdict = await check_send(passport, signature, to, body, scope, client)

Checks (Check.name), each citing its source:
  p*  verify_passport(scope)        WS6: issuer signature, expiry, revocation, scope_in_passport, sponsor_exists,
                                    sponsor_still_employed, domain_matches_company, sponsor_title_current, sponsor_can_grant_scope
  g1  message_signature_valid       the body was signed by the key on the passport (Ed25519, passport.sign_message)
  g2  recipient_still_at_company    Person Enrich on the recipient: a current employer matches to["company"]
  g3+ claims_in_body_true (1 each)  facts the draft states about the recipient (employer, title, tenure, start date,
                                    experience, location, company stage) checked by verify/verifier.py
Decision is "allow" only when every check passes. Unverifiable means block (fail closed).
Nothing is ever sent from here; send_if_allowed() only appends to the outbox file.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from .. import llm
from ..schemas import Claim, Criteria, Source
from ..verify.profile import Job, Profile, company_key, load_person, norm, parse_date, same_company, seniority_rank, title_similarity
from ..verify.verifier import verify_candidate
from . import ledger
from .graph import Graph
from .models import Check, Passport, Scope, Verdict
from .passport import verify_message_signature, verify_passport

if TYPE_CHECKING:
    from ..crustdata.client import CrustdataClient

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = float(os.getenv("GUARD_CALL_TIMEOUT", "8"))
TENURE_TOLERANCE_YEARS = 0.5  # "2 years at X" passes for 1.5 to 2.5 years
REPO_ROOT = Path(__file__).resolve().parents[3]


def outbox_path() -> Path:
    return Path(os.getenv("OUTBOX_PATH", REPO_ROOT / "backend" / "data" / "outbox.jsonl"))


# ---- claim extraction ---------------------------------------------------------

class PastRole(BaseModel):
    employer: str
    title: str | None = None


class BodyClaims(BaseModel):
    """Facts a draft states about its recipient. Scalar keys mirror verify_candidate's person["claimed"]."""
    employer: str | None = None
    title: str | None = None
    start_date: str | None = None
    tenure_years: float | None = None
    years_experience: float | None = None
    location: str | None = None
    company_stage: str | None = None
    skills: list[str] = []          # skills, technologies or domains they're said to have or work in
    past_roles: list[PastRole] = []  # roles described as past ("you were Tech Lead at TransFi")
    other: list[str] = []  # LLM only: other factual claims about the recipient that fit no field (checked as unverifiable)

    def facts(self) -> list[str]:
        return [k for k, v in self.model_dump(exclude={"other"}).items() if v not in (None, "", [])]


# A capitalised or camelCase ("dataZen") word; a trailing "." only on abbreviations ("Pvt.", "Inc."), not sentence ends.
_WORD = r"(?:[A-Z0-9]|[a-z]+[A-Z])[\w&\-]*(?:(?<=Pvt)\.|(?<=Ltd)\.|(?<=Inc)\.|(?<=Co)\.|(?<=Jr)\.|(?<=Sr)\.|(?<=Corp)\.)?"
_CO_GREEDY = rf"({_WORD}(?:\s+(?:{_WORD}|&)){{0,4}})"
_NUM = r"(\d+(?:\.\d+)?)\+?\s*(?i:years?|yrs?)"
_TITLE = r"([A-Z][\w.&/()\-]*(?:\s+[\w.&/()\-|]+){0,7}?)"
def _build_patterns(co: str, title: str) -> tuple[list[tuple[str, tuple[str, ...]]], str]:
    """Regexes for second-person facts. co / title are capturing groups for a company name and a job title."""
    _CO_GREEDY, _TITLE = co, title  # noqa: N806 - names kept so the patterns read as before
    patterns: list[tuple[str, tuple[str, ...]]] = [
        (rf"{_NUM}\s+(?i:at|with)\s+{_CO_GREEDY}", ("tenure_years", "employer")),
        (rf"\b(?i:at|with)\s+{_CO_GREEDY}\s+(?i:for)\s+(?i:(?:almost|nearly|over|about|around)\s+)?{_NUM}", ("employer", "tenure_years")),
        (rf"{_NUM}\s+(?:of\s+)?(?:experience|exp\b|in the industry)", ("years_experience",)),
        (rf"\b(?i:you(?:'re| are)|your role as|as)\s+(?i:an?\s+|the\s+)?{_TITLE}\s+at\s+{_CO_GREEDY}", ("title", "employer")),
        (rf"\b(?i:at|with|joined)\s+{_CO_GREEDY}\s+(?i:since|in)\s+((?:19|20)\d\d(?:-\d\d)?)", ("employer", "start_date")),
        (rf"\b(?i:your\s+(?:work|time|role|team|journey|tenure)\s+at)\s+{_CO_GREEDY}", ("employer",)),
        (rf"\b(?i:you(?:'ve| have)\s+been\s+(?:building|working)\s+at)\s+{_CO_GREEDY}", ("employer",)),
        (rf"\b(?i:you(?:'re| are)\s+(?:now\s+)?(?:at|with))\s+{_CO_GREEDY}", ("employer",)),
        (rf"\b(?i:you(?:'re| are)\s+(?:based\s+)?in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", ("location",)),
        (rf"\b{_CO_GREEDY}\s+(?:is|being)\s+(?:a\s+|an\s+)?((?i:(?:pre-?)?seed|series [a-j]|public|ipo'?d))\b", ("employer", "company_stage")),
    ]
    past_role = (rf"\b(?i:you were|you'd been|you worked as|you served as|previously|formerly|back when you were|"
                 rf"your (?:time|stint|days|years) as|your (?:earlier|previous|past|former) (?:work|time|stint|role|days|experience))"
                 rf"\s+(?i:an?\s+|the\s+)?(?:(?P<title>(?:{_TITLE[1:-1]}))\s+)?(?i:at|with)\s+(?P<co>(?:{_CO_GREEDY[1:-1]}))")
    return patterns, past_role


def _known(names, generic: str) -> str:
    """A capturing group that tries the record's own names first (any case, any punctuation), then the generic shape."""
    alts = sorted({n.strip() for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True)
    if not alts:
        return generic
    return "((?i:" + "|".join(re.escape(n) for n in alts) + r")(?![\w'])|" + generic[1:-1] + ")"


_PATTERNS, _PAST_ROLE_RE = _build_patterns(_CO_GREEDY, _TITLE)

_SKILL_RE = (r"\b(?:(?i:experience (?:with|in)|expertise in|background in|skilled in|depth in|knowledge of)\s+"
             r"(?!(?:a|an|the|this|that|our|your|their|building|working|leading)\b)([A-Za-z][\w+#./\-]*(?:\s+[A-Z][\w+#./\-]*){0,2})"
             r"|(?i:work(?:ing)? (?:with|on|in))\s+([A-Z][\w+#./\-]*(?:\s+[A-Z][\w+#./\-]*){0,2}))")
# Same city, different spelling: the claim is rewritten to the record's spelling before checking.
CITY_ALIASES = [
    {"bengaluru", "bangalore", "blr"}, {"mumbai", "bombay"}, {"gurugram", "gurgaon"}, {"chennai", "madras"},
    {"kolkata", "calcutta"}, {"new delhi", "delhi"}, {"thiruvananthapuram", "trivandrum"}, {"kochi", "cochin"},
    {"mysuru", "mysore"}, {"pune", "poona"}, {"vadodara", "baroda"}, {"puducherry", "pondicherry"},
]


def _canon_city(claimed: str, record: str | None) -> str:
    c = claimed.strip().lower()
    for group in CITY_ALIASES:
        if c in group:
            for alt in group:
                if record and re.search(rf"\b{re.escape(alt)}\b", record.lower()):
                    return alt.title()
    return claimed


_NUM_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                         "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUM_WORDS_RE = re.compile(rf"\b({'|'.join(_NUM_WORDS)})\s+(years?|yrs?)\b", re.I)

# Safety net: wording that usually carries a checkable fact. If the extractor returned nothing for that kind of fact,
# the claim was missed and the check is unverifiable (block), not a silent pass.
_SIGNALS: list[tuple[str, tuple[str, ...], str]] = [
    (r"\b(?:\d+(?:\.\d+)?|" + "|".join(_NUM_WORDS) + r")\+?\s+(?:years?|yrs?|months?)\b", ("tenure_years", "years_experience", "start_date"),
     "a length of time"),
    (r"\b(?:19|20)\d\d\b", ("start_date", "tenure_years"), "a year"),
    (r"\b(?:director|vp|vice president|head of|chief|cto|ceo|cfo|coo|founder|principal|staff|senior|lead|manager)\b",
     ("title",), "a job title"),
    (r"\b(?:live|living|based|located|relocated|moved)\s+(?:in|to)\b|\byou(?:'re| are) (?:from|in)\b", ("location",), "a location"),
    (r"\b(?:joined|started at|founded|work(?:ing|ed)? at|over at|been at|role at|team at|(?:previously|formerly|were) at)\b",
     ("employer", "start_date", "tenure_years"),
     "an employer"),
]
_SECOND_PERSON = re.compile(r"\b(?:you|your|you're|you've|yours)\b", re.I)
# Pitches ("you'd be joining", "you could work from") are about the future, not facts about the recipient.
_HYPOTHETICAL = re.compile(r"\byou(?:'d| would| could|'ll| will| might| can)\b|\b(?:would|could|will|can) you\b", re.I)
_FACTUAL_YOU = re.compile(r"\byou(?:'re|'ve| are| have| were| joined| work| led| lead| built| run| spent| started)\b|\byour\b", re.I)
_FIRST_PERSON_LEAD = re.compile(r"^\s*(?:i|i'm|i've|we|we're|we've|our|my)\b", re.I)


def missed_claims(body: str, stated: BodyClaims) -> list[str]:
    """Kinds of fact a second-person sentence seems to state that the extractor did not return."""
    got = set(stated.facts()) - {"skills"}
    if stated.past_roles:
        got |= {"employer", "title"}
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", body):
        if not _SECOND_PERSON.search(sent) or _FIRST_PERSON_LEAD.search(sent):
            continue
        if _HYPOTHETICAL.search(sent) and not _FACTUAL_YOU.search(sent):
            continue
        for pat, kinds, label in _SIGNALS:
            if re.search(pat, sent, re.I) and not got & set(kinds):
                out.append(f"{label} in \"{sent.strip()[:90]}\"")
    return list(dict.fromkeys(out))


def extract_claims_rules(body: str, companies: list[str] = (), titles: list[str] = ()) -> BodyClaims:
    """Deterministic extractor for second-person facts. Used alone in LLM_MODE=mock, and to fill LLM gaps.
    companies / titles: names from the recipient's record, matched as-is ("ept AI", "Lowe's India", odd titles)."""
    found: dict[str, Any] = {}
    body = _NUM_WORDS_RE.sub(lambda m: f"{_NUM_WORDS[m.group(1).lower()]} {m.group(2)}", body)
    patterns, past_role_re = (_build_patterns(_known(companies, _CO_GREEDY), _known(titles, _TITLE))
                              if companies or titles else (_PATTERNS, _PAST_ROLE_RE))
    for pat, keys in patterns:
        m = re.search(pat, body, re.I if keys == ("years_experience",) else 0)
        if not m:
            continue
        for k, v in zip(keys, m.groups()):
            if k in found or v is None:
                continue
            v = re.sub(r"\s+(?:and|&)$", "", v.strip().rstrip(".!,"))
            found[k] = float(v) if k in ("tenure_years", "years_experience") else v
    skills = [(m.group(1) or m.group(2)).strip() for m in re.finditer(_SKILL_RE, body)]
    past = []
    for m in re.finditer(past_role_re, body):
        title, co = (m.group("title") or "").strip() or None, re.sub(r"\s+(?:and|&)$", "", m.group("co").strip().rstrip(".!,"))
        if found.get("employer") == co and found.get("title") == title:
            found.pop("employer", None), found.pop("title", None)  # "as a X at Y" inside a past-tense phrase
        past.append(PastRole(employer=co, title=title))
    return BodyClaims(**found, skills=list(dict.fromkeys(skills)), past_roles=past)


_EXTRACT_PROMPT = """Extract the factual claims this outbound message makes ABOUT ITS RECIPIENT ({name}).
Ignore anything the sender says about themselves or their own company, opinions, and questions.
A skill, technology or domain counts only if the message says THE RECIPIENT has it or works in it. Services, stack or
products of the sender's company ("Acme builds infra on AWS and Kubernetes", "we specialize in Django") are NOT about the
recipient and must not appear in skills.
Only fill a field when the message states it; leave the rest null.
  employer: the company the message says the recipient works at NOW. A company mentioned as past goes in past_roles.
  title: the recipient's CURRENT job title as stated
  start_date: when the message says they joined their current employer (YYYY or YYYY-MM)
  tenure_years: years at their current employer, as stated ("5 years at Razorpay" -> 5)
  years_experience: total career years, as stated
  location: where the message says they are based
  company_stage: funding stage the message attributes to their current employer (seed, series b, public...)
  skills: skills, technologies or domains the message says they have or work in ("your experience with Payments" -> "Payments")
  past_roles: roles the message describes as in the past ("you were Tech Lead at TransFi", "your earlier work at Cvent"),
              each as {{employer, title or null}}
  other: any OTHER checkable fact the message asserts about the recipient's career that fits none of the fields
         above (e.g. "you led the payments team", "you were at Google before"), each as a short phrase. Not opinions.

Message:
\"\"\"{body}\"\"\""""


async def extract_claims(body: str, recipient_name: str = "the recipient", pr: Profile | None = None) -> tuple[BodyClaims, bool]:
    """(claims, used_llm). Gemini when available, with the rule extractor filling gaps; rules alone otherwise."""
    jobs = (pr.current + pr.past) if pr else []
    rules = extract_claims_rules(body, [j.company for j in jobs if j.company], [j.title for j in jobs if j.title])
    if llm.is_mock():
        return rules, False
    try:
        got = await llm.generate_json(_EXTRACT_PROMPT.format(name=recipient_name, body=body), BodyClaims)
    except Exception as e:  # LLMError or anything else: rules + the missed-claim safety net take over
        log.warning("guard: LLM claim extraction failed, using rules only: %s", e)
        return rules, False
    merged = got.model_dump()
    for k, v in rules.model_dump(exclude={"other"}).items():
        if merged.get(k) in (None, "", []) and v not in (None, []):
            merged[k] = v
    out = BodyClaims(**merged)
    # The model sometimes attributes the sender's stack to the recipient; keep list items only when a sentence that
    # names them is about the recipient (your / you've / you're...). Items it can't locate in the text are kept.
    out.skills = [x for x in out.skills if _about_recipient(body, x)]
    out.past_roles = [r for r in out.past_roles if _about_recipient(body, r.employer)]
    out.other = [x for x in out.other if _about_recipient(body, x)]
    return out, True


def _about_recipient(body: str, term: str) -> bool:
    words = [w for w in re.findall(r"[\w+#.\-]+", term or "") if len(w) > 2][:3]
    if not words:
        return True
    pat = re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b", re.I)
    sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", body) if pat.search(x)]
    if not sents:
        return True  # paraphrased by the model: can't place it, so check it (fail closed)
    return any(_FACTUAL_YOU.search(x) and not _FIRST_PERSON_LEAD.search(x) for x in sents)


def _describe(k: str, c: BodyClaims) -> str:
    return {
        "employer": f"works at {c.employer}",
        "title": f"is {c.title}",
        "start_date": f"joined {c.employer or 'their employer'} in {c.start_date}",
        "tenure_years": f"has been at {c.employer or 'their employer'} for {c.tenure_years:g} years" if c.tenure_years is not None else "",
        "years_experience": f"has {c.years_experience:g} years of experience" if c.years_experience is not None else "",
        "location": f"is based in {c.location}",
        "company_stage": f"{c.employer or 'their employer'} is {c.company_stage}",
    }[k]


def _claim_key(c: Claim) -> str | None:
    """Which stated fact a verify_candidate claim answers. The verifier emits fixed claim wording per section."""
    t = c.claim
    if t.startswith("Works at") or t == "Current employer":
        return "employer"
    if t.startswith("Title"):
        return "title"
    if " yrs at " in t or t.startswith("Tenure at") or (t.startswith("At ") and " since " in t):
        return "tenure"
    if "of experience" in t:
        return "years_experience"
    if t.startswith("Based in") or t == "Location":
        return "location"
    if t.endswith("stage/size") or (": " in t and re.search(r"employees|stage|founded", t)) or (c.status == "contradicted" and " is " in t):
        return "company_stage"
    return None


# ---- checks --------------------------------------------------------------------

def _src(d: dict | None, field: str | None = None, url: str | None = None) -> Source:
    s = (d or {}).get("_source") or {}
    return Source(endpoint=s.get("endpoint") or "person/enrich", field=field, url=url or s.get("matched_on"))


def _signature_check(passport: Passport, body: str, signature: str) -> Check:
    ok = verify_message_signature(passport, body, signature)
    return Check(
        id="g1", name="message_signature_valid", status="pass" if ok else "fail",
        detail=f"Ed25519 signature over this exact body matches agent {passport.agent_id}'s key" if ok
        else "Signature does not match this body and agent key: the message was altered or signed by someone else",
        source=Source(endpoint="passport", field="public_key"),
    )


async def _recipient_checks(to: dict, body: str, graph: Graph, client: Any, today: date) -> list[Check]:
    url, company, name = to.get("profile_url"), to.get("company"), to.get("name") or "recipient"
    cid, cname = "g2", "recipient_still_at_company"
    if not url:
        return [Check(id=cid, name=cname, status="unverifiable", detail=f"No profile URL for {name}, so nothing to look up")]
    try:
        rec = await asyncio.wait_for(graph.person(url), CALL_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 - fail closed
        log.warning("guard: recipient lookup failed: %s", e)
        return [Check(id=cid, name=cname, status="unverifiable", detail=f"Crustdata lookup failed ({type(e).__name__}); cannot confirm the recipient",
                      source=Source(endpoint="person/enrich", url=url))]
    if rec is None:
        return [Check(id=cid, name=cname, status="unverifiable", detail=f"No Crustdata record for {url}",
                      source=Source(endpoint="person/enrich", url=url))]

    pr = load_person(rec)
    who = pr.name or name
    checks: list[Check] = []
    cur = next((j for j in pr.current if _co_match(company, j.company)), None)
    if not company:
        checks.append(Check(id=cid, name=cname, status="unverifiable", detail="no recipient company given", source=_src(rec, None, url)))
    elif cur:
        since = f" since {cur.start.isoformat()}" if cur.start else ""
        checks.append(Check(id=cid, name=cname, status="pass",
                            detail=f"{who} is currently {cur.title or 'employed'} at {cur.company}{since}",
                            source=_src(rec, cur.path, url)))
    else:
        left = next((j for j in pr.past if _co_match(company, j.company)), None)
        now = pr.current[0] if pr.current else None
        if left:
            detail = f"{who} left {left.company}" + (f" on {left.end.isoformat()}" if left.end else "")
            fld = f"{left.path}.end_date"
        else:
            detail, fld = f"{who} has no role at {company} in the record", now.path if now else "current_employers"
        if now:
            detail += f"; now {now.title + ' at ' if now.title else 'at '}{now.company}"
        checks.append(Check(id=cid, name=cname, status="fail", detail=detail, source=_src(rec, fld, url)))

    stated, used_llm = await extract_claims(body, who, pr)
    keys = stated.facts()
    named = {r.employer for r in stated.past_roles}
    stale = _former_employers_named(body, pr, stated.employer, named)
    # With Gemini, its "other" list names facts that fit no field; without it, the keyword safety net does.
    missed = [f'"{o}"' for o in stated.other if o.strip()] if used_llm else missed_claims(body, stated)
    if not keys and not stale and not missed:
        checks.append(Check(id="g3", name="claims_in_body_true", status="pass",
                            detail="The draft states no checkable facts about the recipient", source=_src(rec, None, url)))
        return checks
    n0 = len(checks)
    for j in stale:
        checks.append(Check(id=f"g{len(checks) + 2}", name="claims_in_body_true", status="fail",
                            detail=f"Draft mentions {j.company}, which {who} left" + (f" on {j.end.isoformat()}" if j.end else "")
                            + (f"; now at {pr.current[0].company}" if pr.current else "") + ". Stale.",
                            source=_src(rec, f"{j.path}.end_date", url)))
    for m in missed:
        checks.append(Check(id=f"g{len(checks) + 2}", name="claims_in_body_true", status="unverifiable",
                            detail=f"The draft states {m}, which the guard could not check against the record. Reword or remove it.",
                            source=Source(endpoint="guard/extract", field="body")))

    if stated.location:
        stated.location = _canon_city(stated.location, pr.location)
    job, job_current = _job_for_claim(pr, stated.employer)
    n = len(checks) - n0 + 2

    def add(status: str, text: str, detail: str, source: Source | None) -> None:
        nonlocal n
        n += 1
        checks.append(Check(id=f"g{n}", name="claims_in_body_true", status=status, detail=f"{text}. {detail}", source=source))

    # Tenure, start date and title are checked against the job the draft names (a concurrent or past role counts).
    for r in stated.past_roles:
        status, detail, fld = _past_role_claim(r, pr)
        add(status, f"Draft says {who} was " + (f"{r.title} at {r.employer}" if r.title else f"at {r.employer}"), detail, _src(rec, fld, url))
    keys = [k for k in keys if k != "past_roles"]

    own = {k for k in ("tenure_years", "start_date", "title") if k in keys}
    for k in ("tenure_years", "start_date", "title"):
        if k in own:
            status, detail, fld = _job_claim(k, stated, job, job_current, today)
            add(status, f"Draft says {who} {_describe(k, stated)}", detail, _src(rec, fld, url))

    rest = [k for k in keys if k not in own]
    if "employer" in rest and own and job is not None and job_current:
        rest.remove("employer")  # the role-specific check above already confirmed the employer
    if not rest:
        return checks
    claimed = {k: getattr(stated, k) for k in rest}
    claimed["_source"] = "the draft message"
    try:
        found, _ = await verify_candidate({**rec, "claimed": claimed}, None, Criteria(), client, today=today)
    except Exception as e:  # noqa: BLE001 - verify_candidate shouldn't raise, but fail closed if it does
        found = []
        log.warning("guard: verify_candidate raised: %s", e)
    by_key: dict[str, Claim] = {}
    for c in found:
        k = _claim_key(c)
        if k and k not in by_key:
            by_key[k] = c
    for k in rest:
        if k == "skills":
            for sk in stated.skills:
                c = next((x for x in found if x.claim.lower() == f"skill: {sk}".lower()), None)
                text = f"Draft says {who} has {sk} experience"
                if c and c.status == "verified":
                    add("pass", text, f"Record: {c.evidence}", c.source)
                else:
                    add("unverifiable", text, "Not in their skills, headline, titles or employers' industries", _src(rec, pr.skills_field or "skills", url))
            continue
        c = by_key.get(k)
        text = f"Draft says {who} {_describe(k, stated)}"
        if c is None:
            add("unverifiable", text, "Nothing in the record to check it against", _src(rec, None, url))
            continue
        status = {"verified": "pass", "contradicted": "fail"}.get(c.status, "unverifiable")
        add(status, text, c.evidence if c.status != "verified" else f"Record: {c.claim}", c.source)
    return checks


_PAST_TENSE = re.compile(r"\b(?:was|were|had|previously|formerly|earlier|before|prior|back (?:at|in|when)|used to|ex-?|"
                         r"past|stint|days at|time at|worked|led|built|spent|served|joined .* (?:after|from))\b", re.I)


def _former_employers_named(body: str, pr: Profile, claimed_employer: str | None, past_named: set[str] = frozenset()) -> list[Job]:
    """Former employers the draft talks about as if the recipient were still there. A mention in past tense
    ("you were Tech Lead at TransFi", "your earlier work at Cvent") is a past-role claim, not stale; the claimed
    current employer is handled by the employer check."""
    out: list[Job] = []
    for j in pr.past:
        if not j.company or any(same_company(j.company, c.company) for c in pr.current):
            continue
        if (claimed_employer and _co_match(claimed_employer, j.company)) or any(_co_match(n, j.company) for n in past_named):
            continue
        key = re.sub(r"\s+(?:pvt|private|ltd|limited|inc|llc|technologies|technology|solutions|software)\b.*$", "", j.company, flags=re.I).strip()
        if len(key) < 2:
            continue
        pat = re.compile(rf"(?<![\w-]){re.escape(key)}(?![\w-])", re.I if len(key) >= 4 else 0)
        sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", body) if pat.search(x)]
        if sents and not all(_PAST_TENSE.search(x) for x in sents) and j not in out:
            out.append(j)
    return out


def _past_role_claim(r: PastRole, pr: Profile) -> tuple[str, str, str | None]:
    """A role the draft calls past: the employer must appear in the record (past, or current), and the title match it."""
    jobs = [j for j in pr.past + pr.current if _co_match(r.employer, j.company)]
    if not jobs:
        return "fail", f"No role at {r.employer} in the record", "experience.employment_details"
    if not r.title:
        j = jobs[0]
        when = f" until {j.end.isoformat()}" if j.end else ""
        return "pass", f"Record: {j.title or 'role'} at {j.company}{when}", j.path
    best = max(jobs, key=lambda j: title_similarity(r.title, j.title))
    rank = max(seniority_rank(best.title), seniority_rank(best.seniority_level) if best.seniority_level else 0)
    if best.title and seniority_rank(r.title) <= rank and (title_similarity(r.title, best.title) >= 0.5
                                                             or norm(r.title) in norm(best.title) or norm(best.title) in norm(r.title)):
        when = f" until {best.end.isoformat()}" if best.end else ""
        return "pass", f"Record: {best.title} at {best.company}{when}", f"{best.path}.title"
    return "fail", f"Record says '{best.title}' at {best.company}", f"{best.path}.title"


def _co_match(a: str | None, b: str | None) -> bool:
    """same_company, plus a name cut short in the draft ("Samsung R&D Institute India" vs "... India - Bangalore")."""
    if same_company(a, b):
        return True
    ka, kb = company_key(a), company_key(b)
    return min(len(ka), len(kb)) >= 4 and (ka.startswith(kb) or kb.startswith(ka))


def _job_for_claim(pr: Profile, employer: str | None) -> tuple[Job | None, bool]:
    if not employer:
        return (pr.current[0], True) if pr.current else (None, False)
    for j in pr.current:
        if _co_match(employer, j.company):
            return j, True
    for j in pr.past:
        if _co_match(employer, j.company):
            return j, False
    return None, False


def _job_claim(k: str, c: BodyClaims, job: Job | None, current: bool, today: date) -> tuple[str, str, str | None]:
    """(status, detail, source field) for a tenure / start date / title claim about one specific role."""
    if job is None:
        return "fail" if c.employer else "unverifiable", (f"No role at {c.employer} in the record" if c.employer
                                                          else "No current role in the record"), "experience.employment_details"
    if not current:
        end = f" on {job.end.isoformat()}" if job.end else ""
        return "fail", f"Stale: they left {job.company}{end}" + (f" (was {job.title})" if job.title else ""), f"{job.path}.end_date"
    if k == "title":
        if not job.title:
            return "unverifiable", f"No title on the {job.company} role", f"{job.path}.title"
        sim = title_similarity(c.title, job.title)
        rank = max(seniority_rank(job.title), seniority_rank(job.seniority_level) if job.seniority_level else 0)
        inflated = seniority_rank(c.title) > rank
        if inflated:
            return "fail", f"More senior than the record: '{job.title}' at {job.company}", f"{job.path}.title"
        if sim >= 0.5 or norm(c.title) in norm(job.title) or norm(job.title) in norm(c.title):
            return "pass", f"Record: {job.title} at {job.company}", f"{job.path}.title"
        return "fail", f"Record says '{job.title}' at {job.company}", f"{job.path}.title"
    if not job.start:
        return "unverifiable", f"The {job.company} role has no start date", f"{job.path}.start_date"
    yrs = (today - job.start).days / 365.25
    since = f"started {job.start.isoformat()} ({yrs:.1f} yrs)"
    if k == "tenure_years":
        ok = abs(float(c.tenure_years) - yrs) <= TENURE_TOLERANCE_YEARS
        return ("pass" if ok else "fail"), f"Record: {job.company} role {since}", f"{job.path}.start_date"
    m = re.fullmatch(r"((?:19|20)\d\d)(?:-(\d\d))?", str(c.start_date).strip())
    if not m:
        d = parse_date(c.start_date)
        ok = bool(d) and abs((d - job.start).days) <= 62
    elif m.group(2):
        ok = (int(m.group(1)), int(m.group(2))) == (job.start.year, job.start.month)
    else:
        ok = int(m.group(1)) == job.start.year
    return ("pass" if ok else "fail"), f"Record: {job.company} role {since}", f"{job.path}.start_date"


def _ledger_append(verdict: Verdict, passport: Passport, to: dict, scope: str, body: str) -> str | None:
    payload = {
        "agent_id": passport.agent_id, "subject": verdict.subject, "decision": verdict.decision, "scope": scope,
        "to": {k: to.get(k) for k in ("name", "profile_url", "company")},
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "checks": [c.model_dump(exclude={"source"}) for c in verdict.checks],
    }
    try:
        return ledger.append("guard.verdict", payload, [c.source for c in verdict.checks if c.source])
    except Exception as e:  # noqa: BLE001 - a ledger failure must not turn a block into an allow
        log.warning("guard: ledger append failed: %s", e)
        return None


# ---- public API ----------------------------------------------------------------

class UnknownAgent(LookupError):
    pass


def resolve_agent(agent_id: str) -> tuple[Passport, str]:
    """(passport, registry status) for an onboarded AI employee. The registry holds the passport, so callers send
    only their agent_id; the private key never leaves the agent (it signs locally with passport.sign_message)."""
    try:
        from . import registry  # WS8
    except ImportError as e:
        raise UnknownAgent("no AI employee registry in this build; send the passport instead") from e
    try:
        rec = registry.get_agent(agent_id)
    except Exception as e:  # RegistryError: unknown id
        raise UnknownAgent(str(e)) from e
    return Passport.model_validate(rec["passport"]), rec.get("status") or "active"


def _status_check(status: str | None) -> list[Check]:
    if status is None:
        return []
    ok = status == "active"
    return [Check(id="g0", name="agent_active", status="pass" if ok else "fail",
                  detail="Active in the AI employee registry" if ok else f"Registry status is {status}: this agent may not send",
                  source=Source(endpoint="countersign/registry", field="status"))]


async def check_send(passport: Passport | dict, signature: str, to: dict, body: str, scope: Scope,
                     client: CrustdataClient | None = None, *, today: date | None = None,
                     graph: Graph | None = None, agent_status: str | None = None) -> Verdict:
    """Run every pre-send check; allow only if all pass. Never raises on bad data. Records one ledger entry.
    agent_status: the registry status when the passport was resolved from an agent_id (anything but active blocks)."""
    today = today or datetime.now(timezone.utc).date()
    graph = graph or Graph(client)
    client = client if client is not None else graph.client
    if isinstance(passport, dict):
        passport = Passport.model_validate(passport)
    to, body = to or {}, body or ""
    pv, r_checks = await asyncio.gather(
        verify_passport(passport, client, scope, today=today, graph=graph, record=False),
        _recipient_checks(to, body, graph, client, today),
    )
    checks = [*_status_check(agent_status), *pv.checks, _signature_check(passport, body, signature or ""), *r_checks]
    decision = "allow" if checks and all(c.status == "pass" for c in checks) else "block"
    subject = "msg_" + hashlib.sha256(f"{passport.agent_id}\n{body}".encode()).hexdigest()[:12]
    verdict = Verdict(subject=subject, decision=decision, checks=checks)
    verdict.ledger_entry = _ledger_append(verdict, passport, to, scope, body)
    return verdict


def blocking_reasons(v: Verdict) -> list[str]:
    return [f"{c.name}: {c.status}, {c.detail}" + (f" ({c.source.endpoint}{', ' + c.source.field if c.source.field else ''})" if c.source else "")
            for c in v.checks if c.status != "pass"]


async def send_if_allowed(passport: Passport | dict, signature: str, to: dict, body: str, scope: Scope,
                          client: CrustdataClient | None = None, *, today: date | None = None,
                          graph: Graph | None = None, agent_status: str | None = None) -> tuple[Verdict, bool]:
    """Guarded "send": on allow, append the message to the outbox file. Nothing leaves the machine."""
    v = await check_send(passport, signature, to, body, scope, client, today=today, graph=graph, agent_status=agent_status)
    if v.decision != "allow":
        return v, False
    agent_id = passport.agent_id if isinstance(passport, Passport) else passport.get("agent_id")
    from . import seal
    seal_id, sealed = seal.issue(passport, signature, body, scope, "message", to)  # verify footer for the recipient
    out = outbox_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "subject": v.subject, "agent_id": agent_id,
                            "to": to, "scope": scope, "body": sealed, "seal_id": seal_id,
                            "verify_url": f"{seal.base_url()}/verify/{seal_id}", "ledger_entry": v.ledger_entry}) + "\n")
    return v, True
