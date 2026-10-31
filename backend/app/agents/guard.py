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
from ..verify.profile import load_person, same_company
from ..verify.verifier import verify_candidate
from . import ledger
from .graph import Graph
from .models import Check, Passport, Scope, Verdict
from .passport import verify_message_signature, verify_passport

if TYPE_CHECKING:
    from ..crustdata.client import CrustdataClient

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = float(os.getenv("GUARD_CALL_TIMEOUT", "8"))
REPO_ROOT = Path(__file__).resolve().parents[3]


def outbox_path() -> Path:
    return Path(os.getenv("OUTBOX_PATH", REPO_ROOT / "backend" / "data" / "outbox.jsonl"))


# ---- claim extraction ---------------------------------------------------------

class BodyClaims(BaseModel):
    """Facts a draft states about its recipient. Keys mirror verify_candidate's person["claimed"]."""
    employer: str | None = None
    title: str | None = None
    start_date: str | None = None
    tenure_years: float | None = None
    years_experience: float | None = None
    location: str | None = None
    company_stage: str | None = None


_CO = r"([A-Z][\w&\-]*(?:\.[A-Za-z]+)?(?:\s+[A-Z][\w&\-]*){0,3})"
_NUM = r"(\d+(?:\.\d+)?)\+?\s*(?i:years?|yrs?)"
_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    (rf"{_NUM}\s+(?i:at|with)\s+{_CO}", ("tenure_years", "employer")),
    (rf"{_NUM}\s+(?:of\s+)?(?:experience|exp\b|in the industry)", ("years_experience",)),
    (rf"\b(?i:you(?:'re| are)|your role as|as)\s+(?i:an?\s+|the\s+)?([A-Z][\w/&\-]*(?:\s+[A-Z][\w/&\-]*){{0,4}})\s+at\s+{_CO}", ("title", "employer")),
    (rf"\b(?i:at|with|joined)\s+{_CO}\s+(?i:since)\s+((?:19|20)\d\d(?:-\d\d)?)", ("employer", "start_date")),
    (rf"\b(?i:your\s+(?:work|time|role|team|journey|tenure)\s+at)\s+{_CO}", ("employer",)),
    (rf"\b(?i:you(?:'re| are)\s+(?:now\s+)?(?:at|with))\s+{_CO}", ("employer",)),
    (rf"\b(?i:you(?:'re| are)\s+(?:based\s+)?in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", ("location",)),
    (rf"\b{_CO}\s+(?:is|being)\s+(?:a\s+|an\s+)?((?i:(?:pre-?)?seed|series [a-j]|public|ipo'?d))\b", ("employer", "company_stage")),
]


def extract_claims_rules(body: str) -> BodyClaims:
    """Deterministic extractor for second-person facts. Used alone in LLM_MODE=mock, and to fill LLM gaps."""
    found: dict[str, Any] = {}
    for pat, keys in _PATTERNS:
        m = re.search(pat, body, re.I if keys == ("years_experience",) else 0)
        if not m:
            continue
        for k, v in zip(keys, m.groups()):
            if k in found or v is None:
                continue
            v = v.strip().rstrip(".!,")
            found[k] = float(v) if k in ("tenure_years", "years_experience") else v
    return BodyClaims(**found)


_EXTRACT_PROMPT = """Extract the factual claims this outbound message makes ABOUT ITS RECIPIENT ({name}).
Ignore anything the sender says about themselves or their own company, opinions, and questions.
Only fill a field when the message states it; leave the rest null.
  employer: the company the message says the recipient works at
  title: the recipient's job title as stated
  start_date: when the message says they joined (YYYY or YYYY-MM)
  tenure_years: years at their current employer, as stated ("5 years at Razorpay" -> 5)
  years_experience: total career years, as stated
  location: where the message says they are based
  company_stage: funding stage the message attributes to their employer (seed, series b, public...)

Message:
\"\"\"{body}\"\"\""""


async def extract_claims(body: str, recipient_name: str = "the recipient") -> BodyClaims:
    rules = extract_claims_rules(body)
    if llm.is_mock():
        return rules
    try:
        got = await llm.generate_json(_EXTRACT_PROMPT.format(name=recipient_name, body=body), BodyClaims)
    except Exception as e:  # LLMError or anything else: the rule extractor still runs
        log.warning("guard: LLM claim extraction failed, using rules only: %s", e)
        return rules
    merged = got.model_dump()
    for k, v in rules.model_dump().items():
        if merged.get(k) in (None, "") and v is not None:
            merged[k] = v
    return BodyClaims(**merged)


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
    cur = next((j for j in pr.current if same_company(company, j.company)), None)
    if not company:
        checks.append(Check(id=cid, name=cname, status="unverifiable", detail="no recipient company given", source=_src(rec, None, url)))
    elif cur:
        since = f" since {cur.start.isoformat()}" if cur.start else ""
        checks.append(Check(id=cid, name=cname, status="pass",
                            detail=f"{who} is currently {cur.title or 'employed'} at {cur.company}{since}",
                            source=_src(rec, cur.path, url)))
    else:
        left = next((j for j in pr.past if same_company(company, j.company)), None)
        now = pr.current[0] if pr.current else None
        if left:
            detail = f"{who} left {left.company}" + (f" on {left.end.isoformat()}" if left.end else "")
            fld = f"{left.path}.end_date"
        else:
            detail, fld = f"{who} has no role at {company} in the record", now.path if now else "current_employers"
        if now:
            detail += f"; now {now.title + ' at ' if now.title else 'at '}{now.company}"
        checks.append(Check(id=cid, name=cname, status="fail", detail=detail, source=_src(rec, fld, url)))

    stated = await extract_claims(body, who)
    keys = [k for k, v in stated.model_dump().items() if v not in (None, "")]
    if not keys:
        checks.append(Check(id="g3", name="claims_in_body_true", status="pass",
                            detail="The draft states no checkable facts about the recipient", source=_src(rec, None, url)))
        return checks

    claimed = {k: getattr(stated, k) for k in keys}
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
    for n, k in enumerate(keys, 1):
        if k == "start_date" and "tenure_years" in keys:
            continue  # both answered by the same tenure claim
        if k == "employer" and "tenure_years" in keys and by_key.get(k) and by_key[k].status == "verified":
            continue  # "5 years at Razorpay": the tenure check covers the employer, one line is enough
        c = by_key.get("tenure" if k in ("start_date", "tenure_years") else k)
        text = f"Draft says {who} {_describe(k, stated)}"
        if c is None:
            checks.append(Check(id=f"g{n + 2}", name="claims_in_body_true", status="unverifiable",
                                detail=f"{text}: nothing in the record to check it against", source=_src(rec, None, url)))
            continue
        status = {"verified": "pass", "contradicted": "fail"}.get(c.status, "unverifiable")
        evidence = c.evidence if c.status != "verified" else f"record: {c.claim}"
        checks.append(Check(id=f"g{n + 2}", name="claims_in_body_true", status=status,
                            detail=f"{text}. {evidence}", source=c.source))
    return checks


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

async def check_send(passport: Passport | dict, signature: str, to: dict, body: str, scope: Scope,
                     client: CrustdataClient | None = None, *, today: date | None = None,
                     graph: Graph | None = None) -> Verdict:
    """Run every pre-send check; allow only if all pass. Never raises on bad data. Records one ledger entry."""
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
    checks = [*pv.checks, _signature_check(passport, body, signature or ""), *r_checks]
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
                          graph: Graph | None = None) -> tuple[Verdict, bool]:
    """Guarded "send": on allow, append the message to the outbox file. Nothing leaves the machine."""
    v = await check_send(passport, signature, to, body, scope, client, today=today, graph=graph)
    if v.decision != "allow":
        return v, False
    agent_id = passport.agent_id if isinstance(passport, Passport) else passport.get("agent_id")
    out = outbox_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "subject": v.subject, "agent_id": agent_id,
                            "to": to, "scope": scope, "body": body, "ledger_entry": v.ledger_entry}) + "\n")
    return v, True
