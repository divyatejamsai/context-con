"""Who is in the fleet: name, job, role, the real human sponsor (a Crustdata profile) and the scopes asked for.

Sponsors come from fixtures/countersign/sponsors.json where a scenario fits, so every one is a real public
profile with a Person Enrich record. Nothing here is trusted: onboarding and every payroll run check each
sponsor live against Crustdata, and the registry suspends the ones that don't hold up.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..agents.models import Sponsor
from . import closer, diligence, pipeline, reference

ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}

PANKAJ = Sponsor(**SCENARIOS["authorised_founder"]["sponsor"])        # Co-Founder, Grewon Technologies
SHIVANK = Sponsor(**SCENARIOS["sponsor_left"]["sponsor"])             # claims PulseTrader; left April 2026
CHARISH = Sponsor(name="Charish Anumukonda", profile_url="https://www.linkedin.com/in/charish-anumukonda-80b459140",
                  company="SpotDraft", company_domain="spotdraft.com", title="Backend Engineer")
VINAYAK = Sponsor(name="Vinayak Kalushe", profile_url="https://www.linkedin.com/in/vinayakkalushe",
                  company="KIoT", company_domain="kiot.io", title="Backend & DevOps Engineer")

FLEET: list[dict] = [
    {"key": "sourced", "name": "Sourced", "role": "recruiter", "sponsor": PANKAJ, "scopes": ["outreach.hiring", "data.read"],
     "job": "Sources candidates from a hiring brief and drafts verified outreach", "runtime": "in-house"},
    {"key": "pipeline", "name": "Pipeline", "role": "sdr", "sponsor": PANKAJ, "scopes": ["outreach.sales", "data.read"],
     "job": pipeline.JOB, "runtime": "in-house"},
    {"key": "diligence", "name": "Diligence", "role": "analyst", "sponsor": CHARISH, "scopes": ["data.read"],
     "job": diligence.JOB, "runtime": "in-house"},
    {"key": "reference", "name": "Reference", "role": "AI Reference Checker", "sponsor": VINAYAK, "scopes": ["data.read"],
     "job": reference.JOB, "runtime": "in-house"},
    {"key": "closer", "name": "Closer", "role": "sdr", "sponsor": SHIVANK, "scopes": ["outreach.sales", "data.read"],
     "job": closer.JOB, "runtime": "in-house"},
    {"key": "claude-code", "name": "Claude Code", "role": "recruiter", "sponsor": PANKAJ, "scopes": ["outreach.hiring", "data.read"],
     "job": "An outside agent (Claude Code) that reaches Agaxes only through the MCP server", "runtime": "external"},
]
