"""The fleet (app/fleet): every agent does its job over MCP, offline on the committed fixtures (replay + mock LLM)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.agents.passport import issue_passport, sign_message
from app.agents.models import Sponsor
from app.fleet.base import work_body
from app.fleet.reference import parse_resume

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "fixtures/countersign/sponsors.json").read_text())["scenarios"]}


def test_run_fleet_end_to_end(tmp_path):
    env = {**os.environ, "CRUSTDATA_MODE": "replay", "LLM_MODE": "mock"}
    res = subprocess.run([sys.executable, str(BACKEND / "scripts/run_fleet.py"), "--store", str(tmp_path),
                          "--skip", "sourced", "--today", "2026-10-31"],
                         cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
    out = res.stdout
    assert res.returncode == 0, out + res.stderr
    assert "PASS" in out and "chain_ok=True" in out
    agents = {a["name"]: a for a in json.loads((tmp_path / "agents.json").read_text()).values()}
    assert agents["Closer"]["status"] == "suspended" and "PulseTrader" in agents["Closer"]["reason"]
    assert all(agents[n]["status"] == "active" for n in ("Pipeline", "Diligence", "Reference", "Claude Code"))
    assert agents["Claude Code"]["runtime"] == "external" and agents["Pipeline"]["job"]
    outbox = [json.loads(line) for line in (tmp_path / "outbox.jsonl").read_text().splitlines()]
    sent_to = {m["to"]["name"] for m in outbox}
    assert sent_to == {"Charish Anumukonda", "Vinayak Kalushe", "Vinod Sonagara"}  # stale CRM row and Closer blocked
    ledger = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in ledger]
    assert kinds.count("work.resume_check") == 5 and "work.vendor_brief" in kinds and "work.outreach_run" in kinds
    key = json.loads((tmp_path / "applicants.answer_key.json").read_text())
    checks = [e["payload"] for e in ledger if e["kind"] == "work.resume_check"]
    assert sum(len(c["details"]["contradicted"]) for c in checks) == sum(len(k["lies"]) for k in key)
    assert (tmp_path / "work" / "brief-razorpay.md").exists()


def test_resume_parser_reads_the_plain_format():
    c = parse_resume("Jane Doe\nhttps://www.linkedin.com/in/jane\n\nStaff Engineer at Acme Corp\nIn current role since 2020-01-01\n"
                     "9 years of experience\nBased in Pune, India\nCurrent company: Series B\nSkills: Go, Rust\n")
    assert (c.title, c.employer, c.start_date, c.years_experience) == ("Staff Engineer", "Acme Corp", "2020-01-01", 9.0)
    assert c.profile_url.endswith("/in/jane") and c.skills == ["Go", "Rust"] and c.company_stage == "Series B"


@pytest.fixture
def store(tmp_path, monkeypatch):
    for var, name in (("AGENTS_PATH", "agents.json"), ("LEDGER_PATH", "ledger.jsonl"), ("ISSUER_KEY_PATH", "issuer.key")):
        monkeypatch.setenv(var, str(tmp_path / name))
    monkeypatch.setenv("LLM_MODE", "mock")
    return tmp_path


async def _record(args):
    import mcp_server

    res = await mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "record_work", "arguments": args}})
    return json.loads(res["result"]["content"][0]["text"])


@pytest.mark.asyncio
async def test_record_work_needs_the_agents_signature_and_an_active_agent(store):
    from app.agents import ledger, registry

    a = registry.onboard("Diligence", "analyst", Sponsor(**SCENARIOS["authorised_founder"]["sponsor"]))
    p, key = registry.get_agent(a["agent_id"])["passport"], registry.private_key(a["agent_id"])
    from app.agents.models import Passport
    p = Passport.model_validate(p)
    args = {"agent_id": a["agent_id"], "kind": "vendor_brief", "summary": "Razorpay: proceed", "details": {"n": 1},
            "sources": [{"endpoint": "company/enrich", "field": "headcount.total"}]}

    res = await _record({**args, "signature": sign_message(p, key, work_body("vendor_brief", "Razorpay: proceed", {"n": 1}))})
    assert res["recorded"] and ledger.entries(a["agent_id"])[-1]["kind"] == "work.vendor_brief"

    _, other_key = issue_passport("x", "analyst", p.sponsor, ["data.read"])
    with pytest.raises(ValueError):
        sign_message(p, other_key, "x")  # someone else's key can't even produce a signature for this passport
    res = await _record({**args, "summary": "Razorpay: hold", "signature": sign_message(p, key, work_body("vendor_brief", "Razorpay: proceed", {"n": 1}))})
    assert not res["recorded"] and "work signature" in res["refused"][0]  # signed one summary, filed another

    registry.suspend(a["agent_id"], "test")
    res = await _record({**args, "signature": sign_message(p, key, work_body("vendor_brief", "Razorpay: proceed", {"n": 1}))})
    assert not res["recorded"] and any("suspended" in r for r in res["refused"])
