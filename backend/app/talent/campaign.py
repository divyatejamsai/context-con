"""Campaigns: a brief becomes a job, a ranked pool of real candidates, and a persistent set of conversations.

    parse_job(brief)                  pay band, notice limit, openings and city from a three-line brief
    source(criteria, client, want)    paged Crustdata Person Search over the brief's title ladder, every record verified
                                      and ranked (app/verify), best `want` kept with a verified fact for the outreach hook
    GuardSender(agent_id, graph)      every outbound message signed with the agent's key and run through Send Guard
    create / load / save / engine_for campaigns persisted as JSON (CAMPAIGNS_DIR, default backend/data/campaigns)
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from ..agents import ledger, registry
from ..agents.guard import check_send
from ..agents.models import Passport
from ..agents.passport import sign_message
from ..brief import broaden_ladder, parse_brief
from ..orchestrator import to_crustdata_filters
from ..schemas import Criteria
from ..verify.profile import load_person
from ..verify.ranker import rank_candidate
from ..verify.verifier import verify_candidate
from .conversations import Engine
from .pool import PoolGraph, fetch_pool
from .sim import Sim

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "a": 1, "an": 1}


def campaigns_dir() -> Path:
    return Path(os.getenv("CAMPAIGNS_DIR") or ROOT / "backend" / "data" / "campaigns")


def parse_job(brief: str, criteria: Criteria | None = None) -> dict:
    """The terms the brief sets. Anything it doesn't say stays None and the engine doesn't enforce it."""
    t = brief.lower()
    job: dict[str, Any] = {"role": (criteria.role if criteria and criteria.role else None) or brief.strip().splitlines()[0][:80],
                           "city": (criteria.locations[0] if criteria and criteria.locations else None),
                           "band_low": None, "band_high": None, "notice_max_days": None, "openings": 1}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|l\b|lakhs?|lacs?)", t)
    if m:
        job["band_low"], job["band_high"] = sorted((float(m.group(1)), float(m.group(2))))
    elif m := re.search(r"(?:up to|upto|max|budget|<)\s*(\d+(?:\.\d+)?)\s*(?:lpa|l\b|lakhs?)", t):
        job["band_high"] = float(m.group(1))
        job["band_low"] = round(job["band_high"] * 0.75, 1)
    m = re.search(r"notice[^.\n\d]{0,20}(\d+)\s*(day|days|d|week|weeks|month|months)", t) or \
        re.search(r"join(?:ing)? (?:in|within)\s*(\d+)\s*(day|days|week|weeks|month|months)", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        job["notice_max_days"] = n * (30 if u.startswith("month") else 7 if u.startswith("week") else 1)
    m = re.search(r"\b(\d+|one|two|three|four|five|a|an)\s+(?:hires?|openings?|seats?|positions?|people)\b", t)
    if m:
        job["openings"] = int(m.group(1)) if m.group(1).isdigit() else _WORDS[m.group(1)]
    return job


def hook_for(claims: list) -> str | None:
    """One verified fact for the outreach line, never scoring text."""
    for c in claims:
        txt = c.claim if hasattr(c, "claim") else c.get("claim", "")
        st = c.status if hasattr(c, "status") else c.get("status")
        if st != "verified":
            continue
        if m := re.match(r"At (.+?) since (\d{4})", txt):
            return f"Your time at {m.group(1)} since {m.group(2)} stood out."
        if m := re.match(r"Skill: (.+)", txt):
            return f"Your {m.group(1)} experience stood out."
    return None


async def source(criteria: Criteria, client: Any, want: int = 100, today: date | None = None,
                 pool: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """(ranked candidates, raw records). Pages Person Search down the brief's ladder until `want` profiles."""
    records: dict[str, dict] = {}
    if pool is None:
        for _desc, f in broaden_ladder(criteria):
            if len(records) >= want:
                break
            try:
                rows = await fetch_pool(client, to_crustdata_filters(f) if hasattr(client, "request") else f, want - len(records))
            except Exception as e:  # noqa: BLE001 - try the next, looser step
                log.warning("campaign sourcing: %s", e)
                continue
            for r in rows:
                u = load_person(r).profile_url
                if u:
                    records.setdefault(u, r)
        pool = list(records.values())
    ranked = []
    for rec in pool:
        pr = load_person(rec)
        if not pr.profile_url or not pr.name:
            continue
        claims, flags = await verify_candidate(rec, None, criteria, None, today=today)
        score, reasons = await rank_candidate(rec, claims, criteria)
        if any(c.status == "contradicted" for c in claims):
            score = min(score, 30)
        cur = pr.current[0] if pr.current else None
        ranked.append({"name": pr.name, "profile_url": pr.profile_url, "company": cur.company if cur else None,
                       "title": cur.title if cur else None, "score": score,
                       "reasons": [r.model_dump() for r in reasons], "claims": [c.model_dump() for c in claims],
                       "flags": flags, "hook": hook_for(claims)})
    ranked.sort(key=lambda c: -c["score"])
    return ranked[:want], pool


class GuardSender:
    """Signs each message with the agent's own key and runs Send Guard. Nothing is ever emailed: an allowed message is
    "sent" into the campaign transcript (and the guard's ledger entry), which is what the event rules permit."""

    def __init__(self, agent_id: str, graph: PoolGraph, client: Any = None):
        rec = registry.get_agent(agent_id)
        self.agent_id = agent_id
        self.status = rec.get("status")
        self.passport = Passport.model_validate(rec["passport"])
        self.key = registry.private_key(agent_id)
        self.graph = graph
        self.client = client

    async def __call__(self, conv: dict, body: str, scope: str, now: datetime) -> dict:
        to = {"name": conv["name"], "profile_url": conv["profile_url"], "company": conv.get("company")}
        v = await check_send(self.passport, sign_message(self.passport, self.key, body), to, body, scope, self.client,
                             today=now.date(), graph=self.graph, agent_status=self.status)
        return {"decision": v.decision, "checks": [c.model_dump() for c in v.checks], "ledger_entry": v.ledger_entry}


SUBJECTS = {"offer": "Your offer", "offer_revised": "Revised offer", "offer_final": "Best and final offer",
            "sign_request": "Your offer", "welcome": "Welcome aboard"}


class EmailSender:
    """Live campaigns: real email through the outbound layer (app/outbound, PR #21). guarded_send runs Send Guard on
    the exact body, finds the address on Crustdata and threads every message of a conversation by thread_key, so
    replies come back to this conversation (see register_replies). Anything but "sent" counts as blocked here."""

    def __init__(self, camp: dict):
        self.camp = camp

    async def __call__(self, conv: dict, body: str, scope: str, now: datetime) -> dict:
        from ..outbound.send import guarded_send  # imported lazily: optional until the outbound layer is merged

        kind = conv.get("sending_kind")
        subject = SUBJECTS.get(kind or "", f"{self.camp['job']['role']} at {self.camp['job'].get('company') or 'our team'}")
        to = {"name": conv["name"], "profile_url": conv["profile_url"], "company": conv.get("company")}
        res = await guarded_send(self.camp["agent_id"], to, subject, body, scope=scope,
                                 thread_key=f"{self.camp['id']}:{conv['id']}")
        v = dict(res.verdict or {})
        checks = list(v.get("checks") or [])
        if not res.ok:
            checks.append({"name": f"outbound_{res.status}", "status": "fail", "detail": res.detail or res.status})
        return {"decision": "allow" if res.ok else "block", "checks": checks, "ledger_entry": v.get("ledger_entry")}


_registered = False


def register_replies() -> bool:
    """Route real email replies (polled by the outbound layer) into the right live campaign conversation."""
    global _registered
    if _registered:
        return True
    try:
        from ..outbound.tracking import register_reply_handler
    except ImportError:
        return False

    async def on_reply(msg: dict, reply: dict) -> None:
        key = (msg or {}).get("thread_key") or ""
        if ":" not in key or not key.startswith("cmp_"):
            return
        cid, conv_id = key.split(":", 1)
        try:
            camp = load(cid)
        except KeyError:
            return
        if camp.get("mode") != "live" or conv_id not in camp["conversations"]:
            return
        eng = engine_for(camp)
        eng.now = max(eng.now, datetime.now())
        await eng.receive(conv_id, reply.get("text") or "")
        save(camp)

    register_reply_handler(on_reply)
    _registered = True
    return True


def _path(cid: str) -> Path:
    if not re.fullmatch(r"cmp_[a-f0-9]{10}", cid):
        raise KeyError(cid)
    return campaigns_dir() / f"{cid}.json"


def save(camp: dict) -> None:
    p = _path(camp["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(camp, default=str))
    tmp.replace(p)


def load(cid: str) -> dict:
    p = _path(cid)
    if not p.exists():
        raise KeyError(cid)
    return json.loads(p.read_text())


def list_ids() -> list[str]:
    d = campaigns_dir()
    return sorted((p.stem for p in d.glob("cmp_*.json")), key=lambda s: (d / f"{s}.json").stat().st_mtime) if d.exists() else []


def new(brief: str, job: dict, criteria: Criteria, agent_id: str, *, mode: str = "sim", seed: int = 7,
        start: datetime | None = None) -> dict:
    start = start or datetime.combine(datetime.now(timezone.utc).date(), time(9, 0))
    return {"id": "cmp_" + uuid.uuid4().hex[:10], "brief": brief, "job": job, "criteria": criteria.model_dump(),
            "agent_id": agent_id, "mode": mode, "seed": seed, "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": start.isoformat(), "clock": start.isoformat(),
            "status": "open", "conversations": {}, "hires": [], "events": [], "records": [],
            "stats": {"guard_allowed": 0, "guard_blocked": 0, "replies": 0, "offers": 0}}


def engine_for(camp: dict, client: Any = None, emit=None, sender=None) -> Engine:
    graph = PoolGraph(camp.get("records") or [], client)
    if sender is None and camp.get("mode") == "live":
        sender = EmailSender(camp)
        register_replies()
    sender = sender or GuardSender(camp["agent_id"], graph, client)
    sim = Sim(camp) if camp.get("mode") == "sim" else None
    kw = {"emit": emit} if emit else {}
    return Engine(camp, sender, sim=sim, **kw)


async def create(brief: str, agent_id: str, client: Any, *, size: int = 100, mode: str = "sim", seed: int = 7,
                 start: datetime | None = None, pool: list[dict] | None = None, emit=None, sender=None) -> tuple[dict, Engine]:
    from ..sourced_agent import resolve_agent_id

    agent_id = resolve_agent_id(agent_id)
    rec = registry.get_agent(agent_id)  # KeyError-like RegistryError if unknown
    if rec.get("status") != "active":
        raise PermissionError(f"{rec.get('name')} is {rec.get('status')}: {rec.get('reason') or 'no reason given'}")
    criteria = await parse_brief(brief)
    job = parse_job(brief, criteria)
    job["company"] = rec["passport"]["sponsor"]["company"]
    job["recruiter"] = rec.get("name") or "Sourced"
    camp = new(brief, job, criteria, agent_id, mode=mode, seed=seed, start=start)
    ranked, records = await source(criteria, client, size, today=datetime.fromisoformat(camp["clock"]).date(), pool=pool)
    camp["records"] = records
    eng = engine_for(camp, client, emit, sender)
    ledger.append("campaign.started", {"campaign": camp["id"], "agent_id": agent_id, "brief": brief, "job": job,
                                       "candidates": len(ranked), "mode": mode})
    await eng.open(ranked)
    save(camp)
    return camp, eng
