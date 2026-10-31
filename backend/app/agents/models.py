"""Shared Agaxes types (docs/COUNTERSIGN.md). WS6 owns this file; WS7/WS8 import from it."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..schemas import Source

Scope = Literal["outreach.hiring", "outreach.sales", "data.read", "contract.sign", "payment.send"]
SCOPES: tuple[str, ...] = ("outreach.hiring", "outreach.sales", "data.read", "contract.sign", "payment.send")


class Sponsor(BaseModel):
    """The real human an AI employee acts for. Everything here is a claim until verify_passport checks it."""
    name: str
    profile_url: str
    company: str
    company_domain: str | None = None
    title: str | None = None


class Passport(BaseModel):
    agent_id: str
    agent_name: str
    role: str
    sponsor: Sponsor
    scopes: list[Scope] = Field(default_factory=list)
    issued_at: str
    expires_at: str
    public_key: str          # agent's Ed25519 public key, base64
    issuer_key_id: str = ""  # which Agaxes issuer key signed it
    issuer_signature: str = ""


class Check(BaseModel):
    id: str
    name: str
    status: Literal["pass", "fail", "unverifiable"]
    detail: str
    source: Source | None = None


class Verdict(BaseModel):
    subject: str
    decision: Literal["allow", "block"]
    checks: list[Check] = Field(default_factory=list)
    ledger_entry: str | None = None


__all__ = ["Scope", "SCOPES", "Sponsor", "Passport", "Check", "Verdict", "Source"]
