"""The conversation engine: a three-line brief to a signed offer, with a hundred conversations kept alive for weeks.

Every candidate is one conversation with a stage, a transcript and one pending timer. Nobody types: the engine sends,
waits, follows up, reads replies, screens, books interviews, makes and negotiates offers and collects the signature.

    contacted   outreach sent; follow-ups after 3 and 7 days of silence, ghosted after 14
                "later" snoozes 30 days; "decline" closes politely; "unsubscribe" stops all contact at once
    screening   notice period and expected pay asked; a missing answer is asked once more. Out of band (pay above
                the band's ceiling by >25%) or notice longer than the brief allows: closed with a kind rejection
    scheduling  three interview slots offered; "none work" gets three more; the pick is confirmed
    interview   the panel's verdict arrives after the slot (POST .../feedback; the simulator's panel in tests)
    offer_pending  passed, waiting for an opening. Best first: record score, then interview
    offer       offer letter sent under the passport's contract.sign scope; a counter inside the band gets a revised
                offer, a counter above it gets the band's ceiling as best and final; unanswered offers are nudged at
                3 days and expire at 5. Accepting means typing "Signed: <full name>", matched to the record's name
    signed      the signature, the offer document's hash and the time go on the ledger; when every opening is
                signed, every other open conversation is closed with a "role filled" note

Every outbound message goes through Countersign's Send Guard (passport, signature, the recipient still where we
think, every fact in the message checked). A blocked outreach is retried once with no facts in it; anything else
blocked ends that conversation as "blocked" with the guard's reasons. Offers blocked for scope wait as offer_held
until the sponsor countersigns.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, time, timedelta
from typing import Any, Awaitable, Callable

from ..agents import ledger
from .replies import classify
from .sim import Sim
from .staffing import names_match

log = logging.getLogger(__name__)

TERMINAL = {"signed", "declined", "ghosted", "rejected", "unsubscribed", "closed", "blocked"}
STAGES = ["contacted", "screening", "scheduling", "interview", "offer_pending", "offer", "offer_held", "signed",
          "declined", "ghosted", "rejected", "unsubscribed", "closed", "blocked"]
FOLLOWUP_DAYS = (3, 7)
GHOST_DAYS = 14
SNOOZE_DAYS = 30
SCREEN_NUDGE_DAYS = 3
SCREEN_TIMEOUT_DAYS = 7
SLOT_TIMEOUT_DAYS = 4
OFFER_NUDGE_DAYS = 3
OFFER_EXPIRE_DAYS = 5
COUNTER_CEILING = 1.25   # pay expectation this far above the band's top ends screening
SLATE_PER_OPENING = 3    # compare this many passed interviews per opening before the first offer...
DECIDE_AFTER_DAYS = 14   # ...or decide with whoever has passed by this day

# sender(conv, body, scope, now) -> {"decision": "allow"|"block", "checks": [...], "ledger_entry": str|None}
Sender = Callable[[dict, str, str, datetime], Awaitable[dict]]
Emit = Callable[[dict], Awaitable[None]]


async def _noop(_: dict) -> None:
    return None


def first_name(conv: dict) -> str:
    return (conv.get("name") or "there").split()[0]


class Engine:
    def __init__(self, camp: dict, sender: Sender, *, sim: Sim | None = None,
                 panel: Callable[[dict], tuple[bool, str]] | None = None, emit: Emit = _noop):
        self.camp = camp
        self.sender = sender
        self.sim = sim
        self.panel = panel or (sim.interview if sim else None)
        self.emit = emit

    # ---- clock ----
    @property
    def now(self) -> datetime:
        return datetime.fromisoformat(self.camp["clock"])

    @now.setter
    def now(self, t: datetime) -> None:
        self.camp["clock"] = t.isoformat()

    @property
    def job(self) -> dict:
        return self.camp["job"]

    @property
    def convs(self) -> dict[str, dict]:
        return self.camp["conversations"]

    def _event(self, conv: dict | None, etype: str, text: str, **data: Any) -> dict:
        ev = {"type": etype, "at": self.camp["clock"], "cid": conv["id"] if conv else None,
              "name": conv["name"] if conv else None, "text": text, **data}
        self.camp.setdefault("events", []).append(ev)
        self.camp["events"] = self.camp["events"][-2000:]
        return ev

    async def _say(self, conv: dict | None, etype: str, text: str, **data: Any) -> None:
        await self.emit(self._event(conv, etype, text, **data))

    def _timer(self, conv: dict, kind: str | None, days: float = 0, at: datetime | None = None) -> None:
        conv["timer"] = None if kind is None else {"kind": kind, "at": (at or self.now + timedelta(days=days)).isoformat()}

    async def _move(self, conv: dict, stage: str, why: str) -> None:
        old = conv["stage"]
        conv["stage"] = stage
        conv.setdefault("history", []).append({"at": self.camp["clock"], "from": old, "to": stage, "why": why})
        if stage in TERMINAL:
            self._timer(conv, None)
            if self.sim:
                self.sim.drop(conv["id"])
        await self._say(conv, "stage", f"{conv['name']}: {old} -> {stage} ({why})", stage=stage, previous=old)

    # ---- sending, always through Send Guard ----
    async def _send(self, conv: dict, kind: str, body: str, scope: str = "outreach.hiring", **meta: Any) -> bool:
        conv["sending_kind"] = kind
        try:
            v = await self.sender(conv, body, scope, self.now)
        except Exception as e:  # noqa: BLE001 - a guard failure blocks, it never allows
            log.warning("guard failed for %s: %s", conv["id"], e)
            v = {"decision": "block", "checks": [{"name": "guard_error", "status": "fail", "detail": f"{type(e).__name__}: {e}"}]}
        ok = v.get("decision") == "allow"
        failed = [f"{c.get('name')}: {c.get('detail')}" for c in v.get("checks", []) if c.get("status") != "pass"]
        conv["messages"].append({"dir": "out", "at": self.camp["clock"], "kind": kind, "body": body, "scope": scope,
                                 "guard": {"decision": v.get("decision"), "ledger_entry": v.get("ledger_entry"), "failed": failed}, **meta})
        self.camp["stats"]["guard_" + ("allowed" if ok else "blocked")] += 1
        await self._say(conv, "message", f"{'Sent' if ok else 'Guard blocked'} {kind} to {conv['name']}",
                        dir="out", message_kind=kind, decision=v.get("decision"), failed=failed[:3])
        if ok and self.sim:
            self.sim.on_message(conv, kind, self.now, offer_lpa=meta.get("offer_lpa"))
        return ok

    # ---- message bodies ----
    def _sig(self) -> str:
        return f"\n\n{self.job.get('recruiter') or 'Sourced'} (AI recruiter for {self.job.get('company') or 'the hiring team'})"

    def outreach_body(self, conv: dict, plain: bool = False) -> str:
        role, where = self.job["role"], f" in {self.job['city']}" if self.job.get("city") else ""
        at = f" at {conv['company']}" if conv.get("company") else ""
        hook = "" if plain or not conv.get("hook") else f" {conv['hook']}"
        return (f"Hi {first_name(conv)},\n\nI came across your work as {conv.get('title') or 'an engineer'}{at}.{hook} "
                f"{self.job.get('company') or 'We'} {'is' if self.job.get('company') else 'are'} hiring a {role}{where}. "
                f"Open to a short chat this week?{self._sig()}")

    # ---- opening ----
    async def open(self, ranked: list[dict]) -> None:
        """ranked: [{name, profile_url, company, title, score, reasons, hook, claims}] best first."""
        for i, c in enumerate(ranked):
            cid = f"c{i + 1:03d}"
            if cid in self.convs:
                continue
            self.convs[cid] = {"id": cid, "name": c["name"], "profile_url": c["profile_url"], "company": c.get("company"),
                               "title": c.get("title"), "score": c.get("score", 0), "reasons": c.get("reasons", []),
                               "claims": c.get("claims", []), "hook": c.get("hook"), "stage": "new", "messages": [],
                               "history": [], "followups": 0, "timer": None, "screening": {}, "interview": {}, "offer": {}}
        await self._say(None, "campaign", f"Opened {len(ranked)} conversations for {self.job['role']}")
        for conv in self.convs.values():
            if conv["stage"] == "new":
                await self._outreach(conv)

    async def _outreach(self, conv: dict, kind: str = "outreach") -> None:
        ok = await self._send(conv, kind, self.outreach_body(conv))
        if not ok and conv.get("hook"):
            ok = await self._send(conv, kind, self.outreach_body(conv, plain=True), retry="without facts")
        if not ok:
            return await self._move(conv, "blocked", "Send Guard blocked outreach: " + "; ".join(conv["messages"][-1]["guard"]["failed"][:2]))
        if conv["stage"] != "contacted":
            await self._move(conv, "contacted", "outreach sent" if kind == "outreach" else "re-engaged after snooze")
        conv["followups"] = 0
        self._timer(conv, "followup", FOLLOWUP_DAYS[0])

    # ---- the loop ----
    def _next(self, until: datetime) -> tuple[datetime, str, Any] | None:
        best = None
        for conv in self.convs.values():
            t = conv.get("timer")
            if conv["stage"] not in TERMINAL and t:
                at = datetime.fromisoformat(t["at"])
                if at <= until and (best is None or at < best[0]):
                    best = (at, "timer", conv)
        dec = self._decide_at()
        if dec and dec <= until and not self.camp.get("decided") and (best is None or dec < best[0]):
            best = (dec, "decide", None)
        if self.sim:
            due = self.sim.due(until)
            if due:
                at = datetime.fromisoformat(due[0]["at"])
                if best is None or at <= best[0]:
                    best = (at, "inbound", due[0])
        return best

    async def advance(self, until: datetime, max_steps: int = 100_000) -> int:
        steps = 0
        while steps < max_steps:
            nxt = self._next(until)
            if nxt is None:
                break
            at, what, item = nxt
            if at > self.now:
                self.now = at
            if what == "decide":
                self.camp["decided"] = True
                await self._say(None, "decide", f"Day {DECIDE_AFTER_DAYS}: deciding with the slate so far")
                await self._fill_openings()
            elif what == "timer":
                conv, t = item, item["timer"]
                self._timer(conv, None)
                await self._on_timer(conv, t["kind"])
            else:
                self.sim.pop(item)
                conv = self.convs.get(item["cid"])
                if conv and conv["stage"] not in TERMINAL:
                    await self.receive(conv["id"], item["text"])
            steps += 1
        if until > self.now:
            self.now = until
        return steps

    async def _on_timer(self, conv: dict, kind: str) -> None:
        st = conv["stage"]
        if kind == "followup" and st == "contacted":
            if conv["followups"] >= len(FOLLOWUP_DAYS):
                return await self._move(conv, "ghosted", f"no reply in {GHOST_DAYS} days")
            conv["followups"] += 1
            body = (f"Hi {first_name(conv)}, following up on my note about the {self.job['role']} role. "
                    f"Worth a quick chat?{self._sig()}" if conv["followups"] == 1 else
                    f"Hi {first_name(conv)}, last nudge from me on the {self.job['role']} role. If now isn't the time, "
                    f"just say so and I won't follow up again.{self._sig()}")
            if not await self._send(conv, "followup", body):
                return await self._move(conv, "blocked", "Send Guard blocked a follow-up")
            nxt = FOLLOWUP_DAYS[1] - FOLLOWUP_DAYS[0] if conv["followups"] == 1 else GHOST_DAYS - FOLLOWUP_DAYS[1]
            self._timer(conv, "followup", nxt)
        elif kind == "re_engage" and st == "contacted":
            await self._outreach(conv, "re_engage")
        elif kind == "screening_nudge" and st == "screening":
            await self._send(conv, "screening_nudge", f"Hi {first_name(conv)}, quick reminder: what's your notice period "
                             f"and expected pay (in LPA)?{self._sig()}")
            self._timer(conv, "screening_timeout", SCREEN_TIMEOUT_DAYS - SCREEN_NUDGE_DAYS)
        elif kind == "screening_timeout" and st == "screening":
            await self._move(conv, "ghosted", "stopped replying during screening")
        elif kind == "slots_timeout" and st == "scheduling":
            await self._move(conv, "ghosted", "never picked an interview slot")
        elif kind == "interview_done" and st == "interview":
            if self.panel is None:
                return  # waits for POST .../feedback from the panel
            passed, notes = self.panel(conv)
            await self.feedback(conv["id"], passed, notes)
        elif kind == "offer_nudge" and st == "offer":
            await self._send(conv, "offer_nudge", f"Hi {first_name(conv)}, checking in on the offer. It's open until "
                             f"{conv['offer']['expires_at'][:10]}. Happy to answer anything.{self._sig()}", offer_lpa=conv["offer"]["ctc_lpa"])
            self._timer(conv, "offer_expire", OFFER_EXPIRE_DAYS - OFFER_NUDGE_DAYS)
        elif kind == "offer_expire" and st == "offer":
            await self._move(conv, "declined", "offer expired unanswered")
            await self._fill_openings()

    # ---- inbound ----
    async def receive(self, cid: str, text: str) -> dict:
        conv = self.convs[cid]
        conv["messages"].append({"dir": "in", "at": self.camp["clock"], "body": text})
        st = conv["stage"]
        r = await classify(text, st)
        conv["messages"][-1]["read_as"] = r.model_dump(exclude_none=True)
        self.camp["stats"]["replies"] += 1
        await self._say(conv, "message", f"{conv['name']} replied ({r.intent})", dir="in", intent=r.intent, body=text[:200])
        if st in TERMINAL:
            return r.model_dump()
        if r.intent == "unsubscribe":
            await self._move(conv, "unsubscribed", "asked not to be contacted")
        elif r.intent == "decline" and st != "offer":
            await self._send(conv, "close", f"Thanks for letting me know, {first_name(conv)}. Wishing you the best.{self._sig()}")
            await self._move(conv, "declined", "not interested")
        elif st == "contacted":
            await self._on_contacted(conv, r)
        elif st == "screening":
            await self._on_screening(conv, r)
        elif st == "scheduling":
            await self._on_scheduling(conv, r)
        elif st == "offer":
            await self._on_offer(conv, r)
        elif r.intent == "question":
            await self._answer(conv, r.question or text)
        return r.model_dump()

    async def _answer(self, conv: dict, q: str) -> None:
        ql = q.lower()
        j = self.job
        if any(w in ql for w in ("budget", "comp", "salary", "pay", "ctc", "range")):
            a = f"The band is {j['band_low']:g}-{j['band_high']:g} LPA." if j.get("band_low") else "Pay depends on experience; tell me what you're looking for."
        elif any(w in ql for w in ("remote", "office", "location", "hybrid")):
            a = f"The role is based in {j['city']}." if j.get("city") else "Location is flexible."
        else:
            a = f"It's a {j['role']} role at {j.get('company') or 'our company'}; happy to share more on a call."
        await self._send(conv, "answer", f"Good question. {a} Shall we take the next step?{self._sig()}")

    async def _on_contacted(self, conv: dict, r) -> None:
        if r.intent == "later":
            await self._send(conv, "close", f"Of course, {first_name(conv)}. I'll check back in a month.{self._sig()}")
            self._timer(conv, "re_engage", SNOOZE_DAYS)
            await self._say(conv, "snooze", f"{conv['name']} snoozed {SNOOZE_DAYS} days")
        elif r.intent == "question":
            await self._answer(conv, r.question or "")
            self._timer(conv, "followup", FOLLOWUP_DAYS[0])
        elif r.intent in ("interested", "info"):
            if r.question:
                await self._answer(conv, r.question)
            await self._move(conv, "screening", "said yes")
            await self._send(conv, "screening", f"Great to hear, {first_name(conv)}! Two quick questions so I can set up the "
                             f"interview: what's your notice period, and what pay are you looking for (in LPA)? And does "
                             f"working from {self.job.get('city') or 'our office'} suit you?{self._sig()}")
            self._timer(conv, "screening_nudge", SCREEN_NUDGE_DAYS)
        else:
            await self._send(conv, "clarify", f"Thanks {first_name(conv)}! Just to check: would you like to hear more about the "
                             f"role? A yes or no is perfect.{self._sig()}")
            self._timer(conv, "followup", FOLLOWUP_DAYS[0])

    async def _on_screening(self, conv: dict, r) -> None:
        s = conv["screening"]
        if r.notice_days is not None:
            s["notice_days"] = r.notice_days
        if r.expected_lpa is not None:
            s["expected_lpa"] = r.expected_lpa
        if r.intent == "question":
            await self._answer(conv, r.question or "")
        missing = [k for k in ("notice_days", "expected_lpa") if k not in s]
        if missing:
            if s.get("asked_again"):
                return
            s["asked_again"] = True
            what = " and ".join({"notice_days": "your notice period", "expected_lpa": "your expected pay (in LPA)"}[k] for k in missing)
            await self._send(conv, "screening_nudge", f"Thanks! Could you also share {what}?{self._sig()}")
            self._timer(conv, "screening_timeout", SCREEN_TIMEOUT_DAYS)
            return
        j = self.job
        if j.get("notice_max_days") is not None and s["notice_days"] > j["notice_max_days"]:
            await self._send(conv, "rejection", f"Thanks {first_name(conv)}. This role needs someone who can start within "
                             f"{j['notice_max_days']} days, so I'll keep you in mind for the next one.{self._sig()}")
            return await self._move(conv, "rejected", f"notice {s['notice_days']}d > {j['notice_max_days']}d")
        if j.get("band_high") and s["expected_lpa"] > j["band_high"] * COUNTER_CEILING:
            await self._send(conv, "rejection", f"Thanks {first_name(conv)}. Your expectation is well above this role's band "
                             f"({j['band_low']:g}-{j['band_high']:g} LPA), so I don't want to waste your time.{self._sig()}")
            return await self._move(conv, "rejected", f"expects {s['expected_lpa']:g} LPA, band tops at {j['band_high']:g}")
        await self._move(conv, "scheduling", "screening passed")
        await self._offer_slots(conv)

    def _slots(self, round_: int) -> list[datetime]:
        d = self.now.date() + timedelta(days=1 + 3 * round_)
        out = []
        while len(out) < 3:
            if d.weekday() < 5:
                out.append(datetime.combine(d, time((11, 15, 17)[len(out)])))
            d += timedelta(days=1)
        return out

    async def _offer_slots(self, conv: dict) -> None:
        rnd = conv["interview"].get("rounds", 0)
        slots = self._slots(rnd)
        conv["interview"].update(rounds=rnd + 1, options=[s.isoformat() for s in slots])
        lines = "\n".join(f"  Option {i + 1}: {s.strftime('%a %d %b, %H:%M')}" for i, s in enumerate(slots))
        await self._send(conv, "slots", f"Let's book a 45-minute interview with the hiring panel. Which works?\n{lines}\n"
                         f"Reply with the option number.{self._sig()}")
        self._timer(conv, "slots_timeout", SLOT_TIMEOUT_DAYS)

    async def _on_scheduling(self, conv: dict, r) -> None:
        iv = conv["interview"]
        if r.intent == "slot" and r.slot and 1 <= r.slot <= len(iv.get("options", [])):
            at = datetime.fromisoformat(iv["options"][r.slot - 1])
            iv["slot"] = at.isoformat()
            await self._send(conv, "interview_confirm", f"Booked: {at.strftime('%a %d %b, %H:%M')}. You'll get a calendar invite "
                             f"from the panel.{self._sig()}")
            await self._move(conv, "interview", f"booked {at:%d %b %H:%M}")
            self._timer(conv, "interview_done", at=at + timedelta(hours=2))
        elif r.intent == "reschedule" and iv.get("rounds", 0) < 3:
            await self._offer_slots(conv)
        else:
            await self._send(conv, "clarify", f"Sorry, which option works: 1, 2 or 3?{self._sig()}")
            self._timer(conv, "slots_timeout", SLOT_TIMEOUT_DAYS)

    async def feedback(self, cid: str, passed: bool, notes: str = "") -> None:
        conv = self.convs[cid]
        if conv["stage"] != "interview":
            return
        conv["interview"].update(passed=passed, notes=notes, at=self.camp["clock"])
        if not passed:
            await self._send(conv, "rejection", f"Thanks for your time with the panel, {first_name(conv)}. We won't be moving "
                             f"forward this time, but I'd be glad to stay in touch.{self._sig()}")
            return await self._move(conv, "rejected", f"interview: {notes or 'did not pass'}")
        await self._move(conv, "offer_pending", f"interview passed ({notes})" if notes else "interview passed")
        await self._fill_openings()

    # ---- offers ----
    def _open_seats(self) -> int:
        live = sum(1 for c in self.convs.values() if c["stage"] in ("offer", "offer_held", "signed"))
        return self.job.get("openings", 1) - live

    def _decide_at(self) -> datetime | None:
        return datetime.fromisoformat(self.camp["started_at"]) + timedelta(days=self.job.get("decide_after_days", DECIDE_AFTER_DAYS))

    def _offer_amount(self, conv: dict) -> float:
        j, want = self.job, conv["screening"].get("expected_lpa")
        if not j.get("band_high"):
            return float(want or 0)
        if want is None:
            return float(j["band_low"])
        return float(min(max(want, j["band_low"]), j["band_high"]))

    async def _fill_openings(self) -> None:
        if self.camp.get("status") == "filled":
            return
        if not self.camp.get("decided"):
            pend = sum(1 for c in self.convs.values() if c["stage"] == "offer_pending")
            still = sum(1 for c in self.convs.values() if c["stage"] in ("contacted", "screening", "scheduling", "interview"))
            if pend < SLATE_PER_OPENING * self.job.get("openings", 1) and still:
                return  # keep interviewing: compare a slate before the first offer
            self.camp["decided"] = True
            await self._say(None, "decide", f"Slate of {pend} passed interview(s): making offers, best record first")
        while self._open_seats() > 0:
            pend = [c for c in self.convs.values() if c["stage"] == "offer_pending"]
            if not pend:
                return
            best = max(pend, key=lambda c: (c.get("score", 0), -int(c["id"][1:])))
            await self._send_offer(best, self._offer_amount(best), "offer")

    def offer_letter(self, conv: dict, ctc: float, version: int, final: bool = False) -> str:
        j = self.job
        start = (self.now.date() + timedelta(days=max(conv["screening"].get("notice_days") or 0, 7) + 7)).isoformat()
        expires = (self.now + timedelta(days=OFFER_EXPIRE_DAYS)).date().isoformat()
        head = "Best and final offer" if final else ("Revised offer" if version > 1 else "Offer of employment")
        return (f"{head}: {j['role']}{' at ' + j['company'] if j.get('company') else ''}\n\n"
                f"Dear {conv['name']},\n\nWe're delighted to offer you the role of {j['role']}"
                f"{', based in ' + j['city'] if j.get('city') else ''}.\n"
                f"  Annual CTC: Rs {ctc:g} lakh (LPA)\n  Start date: {start}\n  Offer valid until: {expires}\n\n"
                f"To accept, reply \"I accept\" and type \"Signed: <your full name>\".{self._sig()}")

    async def _send_offer(self, conv: dict, ctc: float, kind: str) -> None:
        o = conv["offer"]
        version = o.get("version", 0) + 1
        body = self.offer_letter(conv, ctc, version, final=kind == "offer_final")
        sha = hashlib.sha256(body.encode()).hexdigest()
        o.update(version=version, ctc_lpa=ctc, sent_at=self.camp["clock"], doc_sha256=sha,
                 expires_at=(self.now + timedelta(days=OFFER_EXPIRE_DAYS)).isoformat())
        if not await self._send(conv, kind, body, scope="contract.sign", offer_lpa=ctc, doc_sha256=sha):
            failed = conv["messages"][-1]["guard"]["failed"]
            if any("scope" in f.lower() for f in failed):
                await self._move(conv, "offer_held", "offer needs the sponsor's countersign (passport lacks contract.sign)")
                return
            await self._move(conv, "blocked", "Send Guard blocked the offer: " + "; ".join(failed[:2]))
            return await self._fill_openings()
        if conv["stage"] != "offer":
            await self._move(conv, "offer", f"offer sent at {ctc:g} LPA")
        self.camp["stats"]["offers"] += 1
        self._timer(conv, "offer_nudge", OFFER_NUDGE_DAYS)

    async def _on_offer(self, conv: dict, r) -> None:
        o, j = conv["offer"], self.job
        if r.intent == "accept":
            if not r.signature:
                await self._send(conv, "sign_request", f"Wonderful! To make it official, please reply with "
                                 f"\"Signed: {conv['name']}\".{self._sig()}")
                return
            if not names_match(r.signature, conv["name"]):
                await self._send(conv, "sign_request", f"The signature \"{r.signature}\" doesn't match the name on the offer "
                                 f"({conv['name']}). Please sign with your full name.{self._sig()}")
                return
            return await self._signed(conv, r.signature)
        if r.intent == "counter":
            ask = r.expected_lpa
            top = j.get("band_high")
            if ask and top and ask <= top and ask > o["ctc_lpa"] and o.get("version", 1) < 3:
                return await self._send_offer(conv, float(ask), "offer_revised")
            if top and o["ctc_lpa"] < top and o.get("version", 1) < 3:
                return await self._send_offer(conv, float(top), "offer_final")
            await self._send(conv, "offer_nudge", f"I understand. {o['ctc_lpa']:g} LPA is the top of what this role pays, so "
                             f"the offer stands as is until {o['expires_at'][:10]}.{self._sig()}", offer_lpa=o["ctc_lpa"])
            return
        if r.intent == "decline":
            await self._send(conv, "close", f"Thanks for considering it, {first_name(conv)}. The door stays open.{self._sig()}")
            await self._move(conv, "declined", "declined the offer")
            return await self._fill_openings()
        if r.intent == "question":
            return await self._answer(conv, r.question or "")

    async def _signed(self, conv: dict, signature: str) -> None:
        o = conv["offer"]
        conv["signature"] = {"name": signature, "at": self.camp["clock"], "doc_sha256": o["doc_sha256"], "ctc_lpa": o["ctc_lpa"]}
        entry = ledger.append("offer.signed", {"campaign": self.camp["id"], "agent_id": self.camp.get("agent_id"),
                                               "candidate": conv["name"], "profile_url": conv["profile_url"],
                                               "ctc_lpa": o["ctc_lpa"], "offer_version": o["version"],
                                               "doc_sha256": o["doc_sha256"], "signed_as": signature, "signed_at": self.camp["clock"]},
                              [c.get("source") for c in conv.get("claims", []) if c.get("source")][:20])
        conv["signature"]["ledger_entry"] = entry
        self.camp["hires"].append(conv["id"])
        await self._move(conv, "signed", f"signed at {o['ctc_lpa']:g} LPA")
        await self._send(conv, "welcome", f"Welcome aboard, {first_name(conv)}! Your signed offer is on record. The team "
                         f"will reach out about onboarding.{self._sig()}")
        if sum(1 for c in self.convs.values() if c["stage"] == "signed") >= self.job.get("openings", 1):
            self.camp["status"] = "filled"
            self.camp["filled_at"] = self.camp["clock"]
            await self._say(None, "filled", f"All {self.job.get('openings', 1)} opening(s) signed. Closing the other conversations.")
            for c in self.convs.values():
                if c["stage"] not in TERMINAL:
                    await self._send(c, "role_filled", f"Hi {first_name(c)}, an update: the {self.job['role']} role has been "
                                     f"filled. Thank you for your time, and I'd love to stay in touch.{self._sig()}")
                    await self._move(c, "closed", "role filled")

    # ---- reporting ----
    def summary(self) -> dict:
        from collections import Counter

        stages = Counter(c["stage"] for c in self.convs.values())
        reached = Counter()
        for c in self.convs.values():
            seen = {h["to"] for h in c.get("history", [])}
            for s in ("contacted", "screening", "scheduling", "interview", "offer_pending", "offer", "signed"):
                if s in seen:
                    reached[s] += 1
        start = datetime.fromisoformat(self.camp["started_at"])
        return {
            "id": self.camp["id"], "status": self.camp.get("status", "open"), "role": self.job["role"], "job": self.job,
            "clock": self.camp["clock"], "day": (self.now - start).days, "started_at": self.camp["started_at"],
            "filled_at": self.camp.get("filled_at"), "conversations": len(self.convs),
            "open": sum(1 for c in self.convs.values() if c["stage"] not in TERMINAL),
            "stages": dict(stages), "funnel": {s: reached[s] for s in ("contacted", "screening", "scheduling", "interview", "offer_pending", "offer", "signed")},
            "hires": [{"cid": h, "name": self.convs[h]["name"], **{k: v for k, v in (self.convs[h].get("signature") or {}).items()}}
                      for h in self.camp["hires"]],
            "stats": self.camp["stats"], "mode": self.camp.get("mode"),
            "messages": sum(len(c["messages"]) for c in self.convs.values()),
        }

