"""Reading candidate replies: intent plus the facts in them (notice period, expected pay, a chosen slot, a signature).

Rules first, so it works with no LLM and is testable; with Gemini live, a reply the rules can't place is classified by
the model (same schema). The engine never acts on a reply it can't read: "unclear" gets a clarifying question.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel

from .. import llm

log = logging.getLogger(__name__)

Intent = Literal["interested", "decline", "unsubscribe", "later", "question", "info", "slot", "reschedule",
                 "accept", "counter", "unclear"]


class Reply(BaseModel):
    intent: Intent = "unclear"
    notice_days: int | None = None
    expected_lpa: float | None = None
    slot: int | None = None            # 1-based option picked
    signature: str | None = None       # typed full name after "Signed:"
    question: str | None = None
    by: str = "rules"


_UNSUB = re.compile(r"\b(unsubscribe|stop (messaging|contacting|emailing)|do not contact|don'?t contact|remove me)\b", re.I)
_DECLINE = re.compile(r"\b(not interested|no thanks|no thank you|not looking|not open|i'?ll pass|pass on this|decline|"
                      r"happy where i am|not a fit for me|not for me|won'?t be (joining|moving)|have to say no|going with another)\b", re.I)
_LATER = re.compile(r"\b(later|next month|next quarter|in a few weeks|after (my )?(appraisal|bonus|diwali|vesting)|"
                    r"reach out in|ping me in|circle back)\b", re.I)
_ACCEPT = re.compile(r"\b(i accept|accept(ed|ing)? (the|your) offer|happy to accept|signed:|e-?signed|deal\b|count me in)\b", re.I)
_COUNTER = re.compile(r"\b(counter|can you (do|stretch|match|go)|could you (do|stretch|match|go)|any (room|flexibility)|"
                      r"match|bump|revise)\b", re.I)
_YES = re.compile(r"\b(yes|yeah|yep|sure|interested|sounds (good|great|interesting)|happy to (chat|talk|connect)|"
                  r"tell me more|keen|open to (it|a chat|talking|chat)|let'?s (talk|chat)|would love)\b", re.I)
_RESCHED = re.compile(r"\b(none of (these|those|them) work|can'?t do (any|those)|other (times|slots)|reschedule|different time)\b", re.I)
_SLOT = re.compile(r"\b(?:option|slot|#)\s*([123])\b|\b([123])(?:st|nd|rd)?\s+(?:option|slot|one)\b|^\s*([123])\s*[.!]?\s*$", re.I | re.M)
_SIGN = re.compile(r"signed:\s*([A-Za-z][A-Za-z .'-]{1,80})", re.I)
_LPA = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lpa|l\b|lakhs?|lacs?)", re.I)
_NOTICE = re.compile(r"(\d+)\s*(day|days|d|week|weeks|wk|month|months|mo)\b", re.I)
_IMMEDIATE = re.compile(r"\b(immediate(ly)?|can join right away|no notice|serving (my )?notice|already resigned)\b", re.I)


def extract_facts(text: str) -> tuple[int | None, float | None]:
    notice = None
    if _IMMEDIATE.search(text):
        notice = 0
    for m in _NOTICE.finditer(text):
        n, unit = int(m.group(1)), m.group(2).lower()
        ctx = text[max(0, m.start() - 40): m.end() + 20].lower()
        if "notice" in ctx or "join" in ctx or "serve" in ctx or "release" in ctx:
            notice = n * (30 if unit.startswith("mo") else 7 if unit.startswith("w") else 1)
            break
    lpa = None
    m = _LPA.search(text)
    if m:
        lpa = float(m.group(1))
    return notice, lpa


def classify_rules(text: str, stage: str) -> Reply:
    t = text.strip()
    notice, lpa = extract_facts(t)
    r = Reply(notice_days=notice, expected_lpa=lpa)
    if "?" in t:
        r.question = next((q.strip() for q in re.split(r"(?<=[.!?])\s+", t) if q.strip().endswith("?")), t)
    if m := _SIGN.search(t):
        r.signature = m.group(1).strip().rstrip(".")
    if _UNSUB.search(t):
        r.intent = "unsubscribe"
    elif stage == "offer" and (r.signature or _ACCEPT.search(t)) and not _DECLINE.search(t):
        r.intent = "accept"
    elif stage == "offer" and (_COUNTER.search(t) or (lpa and re.search(r"\b(if|could|can|would)\b", t, re.I))):
        r.intent = "counter"
    elif _DECLINE.search(t):
        r.intent = "decline"
    elif stage == "scheduling" and _RESCHED.search(t):
        r.intent = "reschedule"
    elif stage == "scheduling" and (m := _SLOT.search(t)):
        r.intent, r.slot = "slot", int(next(g for g in m.groups() if g))
    elif _LATER.search(t) and not _YES.search(t):
        r.intent = "later"
    elif stage == "screening" and (notice is not None or lpa is not None):
        r.intent = "info"
    elif _YES.search(t):
        r.intent = "interested"
    elif "?" in t:
        r.intent = "question"
    return r


PROMPT = """You are reading a candidate's reply in a recruiting conversation. The conversation is at stage "{stage}".
Classify the intent: interested, decline, unsubscribe, later (wants to be contacted later), question, info (answers
screening questions), slot (picks interview option 1, 2 or 3), reschedule (none of the slots work), accept (accepts the
offer), counter (asks for more money on the offer), unclear.
Also extract notice_days (integer days), expected_lpa (expected pay in lakhs per annum), slot (1-3), signature (the
full name typed after "Signed:"), and question (their question, if any). Use null when absent. Do not guess.

REPLY:
{text}
"""


async def classify(text: str, stage: str) -> Reply:
    r = classify_rules(text, stage)
    if r.intent != "unclear" or llm.is_mock():
        return r
    try:
        got = await llm.generate_json(PROMPT.format(stage=stage, text=text[:2000]), Reply, temperature=0)
        got.by = "gemini"
        for k in ("notice_days", "expected_lpa", "signature"):
            if getattr(got, k) is None and getattr(r, k) is not None:
                setattr(got, k, getattr(r, k))
        return got
    except Exception as e:  # noqa: BLE001 - LLMError or a bad payload: stay with the rules' "unclear"
        log.warning("reply classification by LLM failed: %s", e)
        return r
