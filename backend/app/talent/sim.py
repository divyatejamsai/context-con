"""Simulated candidates, for testing the conversation engine over weeks in seconds.

Each candidate gets a hidden persona from a seeded RNG: how often and how fast they answer, whether they care, what
they expect to be paid, their notice period, how they'd do in an interview, and whether they haggle. When the engine
sends a message the simulator decides if and when the person answers and writes the reply in free text, in the many
ways people phrase things. The engine only ever sees the text: it never reads the persona.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

INTEREST = (("hot", 0.25), ("warm", 0.35), ("cold", 0.27), ("later", 0.08), ("unsubscribe", 0.05))

YES = ["Hi, yes I'm open to hearing more.", "Sure, sounds interesting. Happy to chat.", "Hey! yeah interested, tell me more",
       "Thanks for reaching out. I'm open to a chat.", "yes, would love to know more about the role", "Sounds good, let's talk."]
QUESTIONS = ["Before that, what's the budget for this role?", "Is this remote or in-office?", "What's the team size?",
             "Can you share more about the company?"]
NO = ["Thanks, but I'm not looking right now.", "Not interested, thanks.", "Appreciate it but I'm happy where I am.",
      "No thanks, it's not a fit for me.", "I'll pass on this one, good luck with the search."]
LATER = ["Bad timing, I have my appraisal next month. Can you reach out in a few weeks?",
         "Ping me in a month? Wrapping up a big launch.", "Could you circle back after Diwali?"]
UNSUB = ["Please stop messaging me.", "unsubscribe", "Please remove me from your list, do not contact."]
RESCHED = ["None of these work for me, sorry. Any other times?", "Can't do any of those, could we find a different time?"]


def _rng(seed: int, *parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join([str(seed), *parts]).encode()).hexdigest()[:12], 16))


def persona(seed: int, profile_url: str, band: tuple[float, float] | None) -> dict:
    r = _rng(seed, profile_url, "persona")
    kinds, weights = zip(*INTEREST)
    lo, hi = band or (30.0, 50.0)
    return {
        "interest": r.choices(kinds, weights)[0],
        "responsiveness": round(r.uniform(0.35, 0.95), 2),
        "delay_h": round(r.uniform(8, 90), 1),
        "expected_lpa": round(lo + r.uniform(-0.15, 1.35) * (hi - lo), 1),
        "notice_days": r.choice((0, 15, 30, 30, 60, 60, 90)),
        "quality": round(r.random(), 2),
        "haggles": r.random() < 0.55,
        "asks_question": r.random() < 0.3,
        "partial_screening": r.random() < 0.2,
        "picky_calendar": r.random() < 0.12,
        "counters": 0, "later_used": False, "question_used": False, "resched_used": False, "partial_used": False,
    }


class Sim:
    """State lives in campaign["sim"] so a saved campaign resumes exactly where it stopped."""

    def __init__(self, camp: dict):
        self.camp = camp
        self.state = camp.setdefault("sim", {"personas": {}, "inbox": [], "seed": camp.get("seed", 7)})

    def persona(self, conv: dict) -> dict:
        p = self.state["personas"].get(conv["id"])
        if p is None:
            job = self.camp["job"]
            band = (job["band_low"], job["band_high"]) if job.get("band_low") and job.get("band_high") else None
            p = self.state["personas"][conv["id"]] = persona(self.state["seed"], conv["profile_url"], band)
        return p

    def _r(self, conv: dict, n: int) -> random.Random:
        return _rng(self.state["seed"], conv["profile_url"], str(n))

    def _queue(self, conv: dict, now: datetime, text: str, r: random.Random, fast: bool = False) -> None:
        p = self.persona(conv)
        hours = min(r.expovariate(1 / (p["delay_h"] / (3 if fast else 1))), 120) + 0.25
        self.state["inbox"].append({"at": (now + timedelta(hours=hours)).isoformat(), "cid": conv["id"], "text": text})

    def due(self, until: datetime) -> list[dict]:
        return sorted((m for m in self.state["inbox"] if datetime.fromisoformat(m["at"]) <= until), key=lambda m: m["at"])

    def pop(self, msg: dict) -> None:
        self.state["inbox"].remove(msg)

    def next_at(self) -> datetime | None:
        return min((datetime.fromisoformat(m["at"]) for m in self.state["inbox"]), default=None)

    def drop(self, cid: str) -> None:
        self.state["inbox"] = [m for m in self.state["inbox"] if m["cid"] != cid]

    # ---- how a person answers each kind of message ----
    def on_message(self, conv: dict, kind: str, now: datetime, offer_lpa: float | None = None) -> None:
        p = self.persona(conv)
        r = self._r(conv, len(conv["messages"]))
        if kind in ("outreach", "followup", "re_engage"):
            if r.random() > p["responsiveness"]:
                return
            i = p["interest"]
            if i == "later" and not p["later_used"]:
                p["later_used"] = True
                p["interest"] = "warm"
                return self._queue(conv, now, r.choice(LATER), r)
            if i == "later":
                i = "warm"
            if i == "unsubscribe":
                return self._queue(conv, now, r.choice(UNSUB), r)
            if i == "cold":
                return self._queue(conv, now, r.choice(NO), r)
            if p["asks_question"] and not p["question_used"]:
                p["question_used"] = True
                return self._queue(conv, now, r.choice(YES) + " " + r.choice(QUESTIONS), r)
            return self._queue(conv, now, r.choice(YES), r)
        if kind == "answer":
            return self._queue(conv, now, r.choice(["Got it, thanks. Yes, let's proceed.", "Makes sense. Sure, I'm interested."]), r, fast=True)
        if kind in ("screening", "screening_nudge"):
            notice = "I can join immediately." if p["notice_days"] == 0 else r.choice((
                f"My notice period is {p['notice_days']} days.", f"Notice is {p['notice_days'] // 30 or 1} month(s)." if p["notice_days"] >= 30 else f"Notice period {p['notice_days']} days."))
            pay = r.choice((f"Expecting around {p['expected_lpa']} LPA.", f"Looking for {p['expected_lpa']} lakhs.", f"Expected CTC {p['expected_lpa']} LPA"))
            if kind == "screening" and p["partial_screening"] and not p["partial_used"]:
                p["partial_used"] = True
                return self._queue(conv, now, f"Hi! {notice} Yes, the location works for me.", r, fast=True)
            return self._queue(conv, now, f"{notice} {pay} Location is fine.", r, fast=True)
        if kind == "slots":
            if p["picky_calendar"] and not p["resched_used"]:
                p["resched_used"] = True
                return self._queue(conv, now, r.choice(RESCHED), r, fast=True)
            n = r.randint(1, 3)
            return self._queue(conv, now, r.choice((f"Option {n} works.", f"Let's do slot {n}", f"{n}")), r, fast=True)
        if kind in ("offer", "offer_revised", "offer_final", "offer_nudge", "sign_request"):
            name = conv["name"]
            if kind == "sign_request":
                return self._queue(conv, now, f"Signed: {name}", r, fast=True)
            offered = offer_lpa or 0
            if r.random() > max(p["responsiveness"], 0.8):
                return  # sits on it; the engine nudges, then the offer expires
            if offered >= p["expected_lpa"] * 0.97:
                if r.random() < 0.9:
                    return self._queue(conv, now, r.choice((f"Thrilled to accept! Signed: {name}", f"I accept the offer. Signed: {name}",
                                                            "Happy to accept, excited to join!")), r)
                return self._queue(conv, now, "Thank you, but I'm going with another offer.", r)
            if p["haggles"] and p["counters"] < 2 and kind != "offer_final":
                p["counters"] += 1
                return self._queue(conv, now, r.choice((f"Thanks! Could you stretch to {p['expected_lpa']} LPA?",
                                                        f"I was expecting {p['expected_lpa']} LPA, can you match that?")), r)
            if kind == "offer_final" and r.random() < 0.5:
                return self._queue(conv, now, f"Okay, I accept. Signed: {name}", r)
            return self._queue(conv, now, "I have to say no, the number doesn't work for me. Thanks for your time.", r)
        # rejection, close, role_filled, welcome, interview_confirm, clarify: no reply needed

    def interview(self, conv: dict) -> tuple[bool, str]:
        """The panel's verdict, from the hidden persona plus how strong the record is."""
        p = self.persona(conv)
        s = 0.6 * p["quality"] + 0.4 * (conv.get("score", 50) / 100)
        return s >= 0.5, f"panel score {s:.2f} (pass at 0.50)"
