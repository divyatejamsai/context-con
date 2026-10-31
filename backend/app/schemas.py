"""Core types shared by every workstream. Mirrors the SSE contract in CONTEXT.md section 6.

Change these only after telling the CONTEXT.md owner: WS1, WS3 and WS4 code against them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

ClaimStatus = Literal["verified", "contradicted", "unverifiable"]


class Criteria(BaseModel):
    role: str = ""
    title_variants: list[str] = Field(default_factory=list)
    seniority: str | None = None
    skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    company_preferences: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    raw_brief: str = ""
    min_years: int | None = None  # "5+ yrs" -> 5; WS3's ranker reads it


class Source(BaseModel):
    endpoint: str
    field: str | None = None
    url: str | None = None


class Claim(BaseModel):
    id: str
    claim: str
    status: ClaimStatus
    evidence: str
    source: Source


class Reason(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    id: str
    name: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    profile_url: str | None = None
    score: int = 0
    reasons: list[Reason] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    outreach_draft: str | None = None


class RunRequest(BaseModel):
    brief: str


# ---- SSE events -------------------------------------------------------------

StepName = Literal["parse", "search", "enrich", "verify", "rank", "outreach"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepEvent(BaseModel):
    type: Literal["step"] = "step"
    step: StepName
    message: str
    data: dict[str, Any] | None = None  # optional extras, e.g. parsed criteria
    ts: str = Field(default_factory=_now)


class CandidateEvent(BaseModel):
    type: Literal["candidate"] = "candidate"
    candidate: Candidate
    ts: str = Field(default_factory=_now)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    step: StepName | None = None
    message: str
    ts: str = Field(default_factory=_now)


class RunSummary(BaseModel):
    searched: int = 0
    enriched: int = 0
    shortlisted: int = 0  # candidates scoring >= SHORTLIST_MIN
    elapsed_ms: int = 0
    timings_ms: dict[str, int] = Field(default_factory=dict)  # per step: parse, search, enrich_batch, candidates


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    summary: RunSummary
    ts: str = Field(default_factory=_now)


Event = StepEvent | CandidateEvent | ErrorEvent | DoneEvent
