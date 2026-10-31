"""Past searches: every shortlist run and every campaign, newest first, with where each candidate stands now.

    GET  /api/searches                                   one row per search: title, brief, when, stage counts
    GET  /api/searches/{id}                              the search and its candidates, each with a current stage
    POST /api/searches/{id}/candidates/{key}/stage       {stage, reason}: move a candidate by hand

A search is either a shortlist run (the run.finished ledger entry Sourced writes after each brief, id "run_<hash>")
or a campaign (id "cmp_..."). Every candidate has one of eight stages:

    shortlisted  contacted  replied  interviewing  offered  hired  rejected  dropped

Shortlist runs start everyone on the shortlist at "shortlisted" ("contacted" if Sourced emailed them). Campaign
candidates take their stage from the conversation engine, translated: screening is "replied", a booked interview is
"interviewing", a signed offer is "hired", and declined / ghosted / unsubscribed / role filled / guard-blocked are
"dropped" with the engine's reason. A stage set by hand wins over both, is kept in PIPELINE_PATH and goes on the
ledger as candidate.stage. Dropping or rejecting a campaign candidate by hand also ends their conversation, so the
engine stops messaging them.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..accounts import authz
from ..accounts.authz import require_operate, require_read
from ..agents import ledger
from . import campaign as C
from .conversations import TERMINAL

router = APIRouter(prefix="/api", tags=["searches"])
ROOT = Path(__file__).resolve().parents[3]

STAGES = ("shortlisted", "contacted", "replied", "interviewing", "offered", "hired", "rejected", "dropped")
Stage = Literal["shortlisted", "contacted", "replied", "interviewing", "offered", "hired", "rejected", "dropped"]

# engine stage -> (our stage, the plain detail shown under it)
ENGINE = {
    "contacted": ("contacted", "Waiting for a reply"),
    "screening": ("replied", "Said yes, answering screening questions"),
    "scheduling": ("replied", "Screened, picking an interview slot"),
    "interview": ("interviewing", "Interview booked"),
    "offer_pending": ("interviewing", "Passed the interview, waiting on the slate"),
    "offer": ("offered", "Offer letter out"),
    "offer_held": ("offered", "Offer waiting for the sponsor's countersign"),
    "signed": ("hired", "Signed the offer"),
    "rejected": ("rejected", None),
    "declined": ("dropped", "Declined"),
    "ghosted": ("dropped", "Ghosted"),
    "unsubscribed": ("dropped", "Asked not to be contacted"),
    "closed": ("dropped", "Closed"),
    "blocked": ("dropped", "Blocked by Send Guard"),
}
_lock = threading.Lock()


# ---- hand-set stages ------------------------------------------------------------------------------------------------

def store_path() -> Path:
    return Path(os.getenv("PIPELINE_PATH") or ROOT / "backend" / "data" / "pipeline.json")


def _read() -> dict:
    p = store_path()
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    p = store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _who() -> str | None:
    p = authz.current()
    u = (p.user or {}) if p is not None else {}
    return u.get("name") or u.get("email")


# ---- reading searches -------------------------------------------------------------------------------------------------

def _title(brief: str, role: str | None) -> str:
    lines = (brief or "").strip().splitlines()
    return (role or (lines[0] if lines else "") or "Untitled search")[:90]


def _runs() -> dict[str, dict]:
    ids = authz.visible_agent_ids()
    out = {}
    for e in ledger.entries(kind="run.finished"):
        pl = e.get("payload") or {}
        if ids is not None and pl.get("agent_id") not in ids:
            continue
        out["run_" + e["hash"][:12]] = e
    return out


def _campaign_times() -> dict[str, str]:
    return {(e.get("payload") or {}).get("campaign"): e["ts"] for e in ledger.entries(kind="campaign.started")}


def _cap(s: str | None) -> str | None:
    return s[:1].upper() + s[1:] if s else s


def _plain(why: str | None) -> str | None:
    """The engine's terse reasons, said the way a recruiter would."""
    if not why:
        return why
    if m := re.fullmatch(r"notice (\d+)d > (\d+)d", why):
        return f"Notice period is {m.group(1)} days, the brief allows {m.group(2)}"
    if m := re.fullmatch(r"expects ([\d.]+) LPA, band tops at ([\d.]+)", why):
        return f"Expects {m.group(1)} LPA, the band tops out at {m.group(2)}"
    if m := re.fullmatch(r"interview: panel score ([\d.]+) \(pass at ([\d.]+)\)", why):
        return f"Didn't pass the interview (panel score {m.group(1)}, pass mark {m.group(2)})"
    if why in ("interview: did not pass", "interview: did not pass (entered in the UI)"):
        return "Didn't pass the interview"
    if why.startswith("set by hand: "):
        return why[len("set by hand: "):]
    return _cap(why)


def _engine_reason(conv: dict) -> tuple[Stage, str | None]:
    stage, label = ENGINE.get(conv["stage"], ("contacted", None))
    why = next((h.get("why") for h in reversed(conv.get("history") or []) if h.get("to") == conv["stage"]), None)
    if conv["stage"] == "rejected":
        return stage, _plain(why)
    if conv["stage"] in ("declined", "ghosted", "closed"):
        return stage, f"{label}: {why}" if why else label
    if conv["stage"] == "blocked":
        return stage, _cap(why) or label
    return stage, label


def _engine_history(conv: dict) -> list[dict]:
    out: list[dict] = []
    for h in conv.get("history") or []:
        st, _ = ENGINE.get(h.get("to"), (None, None))
        if not st or (out and out[-1]["stage"] == st) or str(h.get("why") or "").startswith("set by hand: "):
            continue
        out.append({"at": h.get("at"), "stage": st, "reason": _plain(h.get("why")), "by": "Sourced"})
    return out


def _apply(row: dict, manual: dict | None) -> dict:
    if manual:
        row["history"] = [*row.get("history", []), *manual.get("history", [])]
        row.update(stage=manual["stage"], reason=manual.get("reason") or None, set_by="you", updated_at=manual.get("at"))
    return row


def _run_candidates(sid: str, e: dict, marks: dict) -> list[dict]:
    pl = e.get("payload") or {}
    rows = []
    for c in pl.get("candidates") or []:
        key = str(c.get("id") or c.get("name"))
        tier = c.get("tier") or "shortlist"
        sent = c.get("sent") == "sent"
        stage = "contacted" if sent else "shortlisted" if tier == "shortlist" else None
        hist = [{"at": e.get("ts"), "stage": "shortlisted", "reason": None, "by": "Sourced"}] if tier == "shortlist" else []
        if sent:
            hist.append({"at": e.get("ts"), "stage": "contacted", "reason": "Emailed by Sourced", "by": "Sourced"})
        rows.append(_apply({
            "key": key, "name": c.get("name") or "Unknown", "title": c.get("title"), "company": c.get("company"),
            "profile_url": c.get("profile_url"), "score": c.get("score"), "tier": tier, "stage": stage,
            "reason": "Emailed by Sourced" if sent else None, "detail": None if tier == "shortlist" else
            ("Near miss" if tier == "near_miss" else "Below the bar"), "set_by": "Sourced", "updated_at": e.get("ts"),
            "why": [_cap(re.sub(r"^[+-]?\d+:\s*", "", r)) for r in c.get("reasons") or [] if isinstance(r, str)][:2],
            "history": hist,
        }, marks.get(key)))
    return rows


def _campaign_candidates(camp: dict, marks: dict) -> list[dict]:
    rows = []
    for conv in camp["conversations"].values():
        stage, reason = _engine_reason(conv)
        terminal_reason = stage in ("rejected", "dropped")
        last = (conv.get("history") or [{}])[-1].get("at")
        rows.append(_apply({
            "key": conv["id"], "name": conv["name"], "title": conv.get("title"), "company": conv.get("company"),
            "profile_url": conv.get("profile_url"), "score": conv.get("score"), "tier": "shortlist", "stage": stage,
            "reason": reason if terminal_reason else None, "detail": None if terminal_reason else reason,
            "set_by": "Sourced", "updated_at": last, "why": [], "history": _engine_history(conv),
        }, marks.get(conv["id"])))
    return rows


def _counts(rows: list[dict]) -> dict:
    out = {s: 0 for s in STAGES}
    for r in rows:
        if r["stage"] in out:
            out[r["stage"]] += 1
    return out


def _summary(sid: str, kind: str, title: str, brief: str, at: str | None, rows: list[dict], **extra) -> dict:
    return {"id": sid, "kind": kind, "title": title, "brief": brief, "at": at, "counts": _counts(rows),
            "candidates_total": sum(1 for r in rows if r["stage"]), **extra}


def _campaigns_visible() -> list[str]:
    ids = authz.visible_agent_ids()
    out = []
    for cid in C.list_ids():
        try:
            camp = C.load(cid)
        except (KeyError, OSError, json.JSONDecodeError):
            continue
        if ids is None or camp.get("agent_id") in ids:
            out.append(cid)
    return out


def _load_search(sid: str) -> tuple[dict, list[dict]]:
    marks = _read().get(sid, {})
    if sid.startswith("run_"):
        e = _runs().get(sid)
        if not e:
            raise HTTPException(404, "no such search")
        pl = e["payload"]
        rows = _run_candidates(sid, e, marks)
        return _summary(sid, "shortlist", _title(pl.get("brief", ""), (pl.get("understood") or {}).get("role")),
                        pl.get("brief", ""), e.get("ts"), rows, agent_id=pl.get("agent_id"), simulated=False,
                        understood=pl.get("understood") or {}), rows
    if sid.startswith("cmp_"):
        if sid not in _campaigns_visible():
            raise HTTPException(404, "no such search")
        camp = C.load(sid)
        rows = _campaign_candidates(camp, marks)
        return _summary(sid, "campaign", _title(camp["brief"], camp["job"].get("role")), camp["brief"],
                        camp.get("created_at") or _campaign_times().get(sid) or camp.get("started_at"), rows,
                        agent_id=camp.get("agent_id"), simulated=camp.get("mode") != "live",
                        status=camp.get("status"), job=camp.get("job")), rows
    raise HTTPException(404, "no such search")


@router.get("/searches", dependencies=[Depends(require_read)])
async def list_searches():
    store = _read()
    out = []
    for sid, e in _runs().items():
        pl = e["payload"]
        rows = _run_candidates(sid, e, store.get(sid, {}))
        out.append(_summary(sid, "shortlist", _title(pl.get("brief", ""), (pl.get("understood") or {}).get("role")),
                            pl.get("brief", ""), e.get("ts"), rows, simulated=False))
    times = _campaign_times()
    for cid in _campaigns_visible():
        camp = C.load(cid)
        rows = _campaign_candidates(camp, store.get(cid, {}))
        out.append(_summary(cid, "campaign", _title(camp["brief"], camp["job"].get("role")), camp["brief"],
                            camp.get("created_at") or times.get(cid) or camp.get("started_at"), rows,
                            simulated=camp.get("mode") != "live", status=camp.get("status")))
    out.sort(key=lambda s: s["at"] or "", reverse=True)
    return out


@router.get("/searches/{sid}", dependencies=[Depends(require_read)])
async def get_search(sid: str):
    summary, rows = _load_search(sid)
    order = {s: i for i, s in enumerate(STAGES)}
    rows.sort(key=lambda r: (r["stage"] is None, order.get(r["stage"] or "", 9) if r["stage"] in ("rejected", "dropped")
                             else -order.get(r["stage"] or "", 0), -(r.get("score") or 0)))
    return {**summary, "candidates": rows}


class StageChange(BaseModel):
    stage: Stage
    reason: str = Field("", max_length=300)


@router.post("/searches/{sid}/candidates/{key}/stage", dependencies=[Depends(require_operate)])
async def set_stage(sid: str, key: str, req: StageChange):
    summary, rows = _load_search(sid)
    row = next((r for r in rows if r["key"] == key), None)
    if row is None:
        raise HTTPException(404, "no such candidate in this search")
    reason = req.reason.strip()
    if req.stage in ("rejected", "dropped") and not reason:
        raise HTTPException(422, "say why: a reason is needed to reject or drop someone")
    by = _who()
    with _lock:
        data = _read()
        prev = data.setdefault(sid, {}).get(key) or {"history": []}
        at = _now()
        entry = {"at": at, "stage": req.stage, "reason": reason or None, "by": by or "you"}
        data[sid][key] = {"stage": req.stage, "reason": reason or None, "at": at, "by": by,
                          "history": [*prev.get("history", []), entry][-50:]}
        _write(data)
    if summary["kind"] == "campaign" and req.stage in ("rejected", "dropped"):
        await _end_conversation(sid, key, req.stage, reason)
    ledger.append("candidate.stage", {"agent_id": summary.get("agent_id"), "search": sid, "candidate": key,
                                      "name": row["name"], "from": row["stage"], "to": req.stage, "reason": reason or None})
    _, rows = _load_search(sid)
    return next(r for r in rows if r["key"] == key)


async def _end_conversation(cid: str, conv_id: str, stage: str, reason: str) -> None:
    """Close the engine's conversation so no more follow-ups go out. Sends nothing."""
    from .api import _lock as camp_lock, _never

    async with camp_lock(cid):
        camp = C.load(cid)
        conv = camp["conversations"].get(conv_id)
        if not conv or conv["stage"] in TERMINAL:
            return
        eng = C.engine_for(camp, sender=_never)
        await eng._move(conv, "rejected" if stage == "rejected" else "closed", f"set by hand: {reason}")
        C.save(camp)

