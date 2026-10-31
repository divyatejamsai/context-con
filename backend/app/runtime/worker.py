"""What one task runs inside: the agent's own Ctx (app/fleet/base.py), wired to the runtime.

- Every line the agent logs and every event it emits lands on the task live (steps, progress, output).
- Crustdata and Gemini calls are counted against the agent's daily budget; going over stops the task.
- send() is where the employer's control sits: Send Guard checks the draft first (a block never reaches a person),
  then, if the agent's policy asks for it, the draft waits in the approval inbox. Approving re-runs the guard at
  send time (the recipient may have moved, the agent may have been suspended), and only then writes the outbox.
- The agent reaches Countersign through the same tool functions the MCP server serves (in process, so several
  agents can run at once without queueing on one stdio pipe).
"""
from __future__ import annotations

import contextvars
import hashlib
import importlib.util
import inspect
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agents import ledger, registry
from ..agents.passport import sign_message
from ..fleet.base import Ctx, blocked_by
from . import store

log = logging.getLogger(__name__)
BACKEND = Path(__file__).resolve().parents[2]


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Meter:
    """Counts one task's calls. Lives in a contextvar so concurrent tasks don't share counts."""
    task_id: str
    agent_id: str
    crustdata: int = 0
    llm: int = 0
    sends: int = 0

    def charge(self, what: str, n: int = 1) -> None:
        pol = store.policy(self.agent_id)["budget"]
        used = store.usage(self.agent_id)
        cap = {"crustdata": pol["crustdata_calls_per_day"], "llm": pol["llm_calls_per_day"],
               "sends": pol["sends_per_day"]}[what]
        if used.get(what, 0) + n > cap:
            raise BudgetExceeded(f"daily {what} budget reached ({used.get(what, 0)}/{cap})")
        from ..rules import engine as rules
        hit = rules.cap_hit(self.agent_id, what, n)
        if hit:
            rules.enforced(hit, self.agent_id, what, "task stopped", task_id=self.task_id)
            raise BudgetExceeded(rules.explain(hit))
        setattr(self, what, getattr(self, what) + n)
        store.add_usage(self.agent_id, **{what: n})
        store.task_mutate(self.task_id, lambda t: t["usage"].__setitem__(what, t["usage"].get(what, 0) + n))


METER: contextvars.ContextVar[Meter | None] = contextvars.ContextVar("countersign_meter", default=None)


class MeteredClient:
    """Wraps the shared CrustdataClient: every public API call is charged to the task that made it."""
    _CALLS = {"person_search", "person_enrich", "person_enrich_many", "company_search", "company_identify",
              "company_enrich", "job_search", "web_search", "web_fetch"}

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)
        if name not in self._CALLS or not inspect.iscoroutinefunction(attr):
            return attr

        async def call(*a, **kw):
            m = METER.get()
            if m is not None:
                m.charge("crustdata")
            return await attr(*a, **kw)
        return call


_llm_patched = False


def meter_llm() -> None:
    """Count real Gemini calls (llm._call is what generate_json and generate_text both use). Idempotent."""
    global _llm_patched
    if _llm_patched:
        return
    from .. import llm
    inner = llm._call

    async def counted(*a, **kw):
        m = METER.get()
        if m is not None:
            m.charge("llm")
        return await inner(*a, **kw)
    llm._call = counted
    _llm_patched = True


_mcp_mod = None


def _mcp_server():
    """backend/mcp_server.py, loaded once as a module: its call_tool is exactly what MCP clients reach."""
    global _mcp_mod
    if _mcp_mod is None:
        spec = importlib.util.spec_from_file_location("countersign_mcp_server", BACKEND / "mcp_server.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _mcp_mod = mod
    return _mcp_mod


class InprocMCP:
    """Same .tool(name, args) -> payload contract as fleet.mcp_client.CountersignMCP, without the subprocess."""
    server = {"name": "countersign", "version": "in-process"}
    tools = ["verify_agent", "check_before_send", "send_message", "record_work", "ledger_lookup"]

    async def tool(self, name: str, args: dict) -> dict:
        text, err = await _mcp_server().call_tool(name, args)
        if err:
            raise RuntimeError(f"{name}: {text}")
        start = text.find("\n\n{")
        start = start + 2 if start >= 0 else text.index("{")
        return json.loads(text[start:])

    async def close(self) -> None:
        return None


def to_key(to: dict) -> str:
    return f"{to.get('name')} ({to.get('company')})"


class RuntimeCtx(Ctx):
    """A fleet Ctx whose sends go through the employer's approval policy and whose output lands on the task."""

    task_id: str = ""

    def _emit(self, ev: dict) -> None:
        """Collect the agent's structured events on the task: findings, artifacts, filed work, clock-in verdicts."""
        super()._emit(ev)
        typ, tid = ev.get("type"), self.task_id

        def fn(t: dict) -> None:
            out, p = t["output"], t["progress"]
            if typ == "finding":
                out.setdefault("findings", []).append({k: v for k, v in ev.items() if k not in ("type", "agent", "agent_id")})
                p["done"] = min(p["done"] + 1, p["total"]) if p["total"] else p["done"]
            elif typ == "artifact":
                out.setdefault("artifacts", []).append({k: ev.get(k) for k in ("kind", "title", "path", "content")})
            elif typ == "filed":
                out.setdefault("filed", []).append({k: ev.get(k) for k in ("kind", "summary", "ledger_entry")})
                if ev.get("ledger_entry"):
                    t["ledger"].append(ev["ledger_entry"])
            elif typ == "verdict" and ev.get("action") == "clock_in":
                out["clock_in"] = {"decision": ev.get("decision"), "headline": ev.get("headline"),
                                   "ledger_entry": ev.get("ledger_entry"),
                                   "failed": [c for c in ev.get("checks", []) if c.get("status") != "pass"]}
            elif typ == "verdict" and ev.get("action") == "send":
                p["done"] = min(p["done"] + 1, p["total"]) if p["total"] else p["done"]
            else:
                return
        if typ in ("finding", "artifact", "filed", "verdict"):
            store.task_mutate(tid, fn)

    async def send(self, to: dict, body: str, scope: str) -> dict:
        tid, who = self.task_id, to_key(to)
        sig = sign_message(self.passport, self.key, body)
        self._emit({"type": "draft", "to": to, "scope": scope, "body": body})
        v = await self.mcp.tool("check_before_send", {"agent_id": self.agent_id, "signature": sig, "to": to,
                                                      "body": body, "scope": scope, **self._today()})
        return await self.after_guard(to, body, scope, sig, v)

    async def after_guard(self, to: dict, body: str, scope: str, sig: str, v: dict) -> dict:
        """Send Guard has looked at the draft (verdict v). Block, hold for approval, or send."""
        tid, who = self.task_id, to_key(to)
        rec = {"to": to, "scope": scope, "body": body, "decision": v["decision"], "guard_entry": v.get("ledger_entry"),
               "checks": v.get("checks", []), "approval_id": None, "state": None}
        if v["decision"] != "allow":
            reasons = blocked_by(v)
            self.log(f"  send      BLOCK  {who}: {'; '.join(reasons) or 'blocked'}")
            self._verdict("send", {**v, "sent": False}, f"Blocked message to {who}: {reasons[0] if reasons else 'blocked'}", to)
            rec["state"] = "blocked"
            _add_send(tid, rec)
            if self.report is not None:
                self.report.blocked += 1
            return {**v, "sent": False}

        pol = store.policy(self.agent_id)
        from ..rules import engine as rules
        holds = [h for h in rules.send_hits(self.agent, to, scope) if h["effect"] == "hold"]
        if pol["require_approval"] or holds:
            a = store.add_approval(task_id=tid, agent_id=self.agent_id, agent_name=self.agent["name"], action="send",
                                   to=to, body=body, scope=scope, signature=sig, today=self._today().get("today"),
                                   preview={"decision": v["decision"], "checks": v.get("checks", []),
                                            "ledger_entry": v.get("ledger_entry")},
                                   rules=holds, approvals_needed=1, approvals=[])
            if holds:
                rules.enforced(holds[0], self.agent, "send", "held in the approval inbox", target=to,
                               approval_id=a["approval_id"], task_id=tid)
                self.log(f"  send      HOLD   {who}: {rules.explain(holds[0])}")
            else:
                self.log(f"  send      HOLD   {who}: Send Guard cleared it; waiting for your approval")
            self._verdict("send", {**v, "sent": False}, f"Cleared by Send Guard, waiting for approval: {who}", to)
            rec.update(state="pending_approval", approval_id=a["approval_id"], rules=holds)
            _add_send(tid, rec)
            if self.report is not None:
                self.report.allowed += 1
            return {**v, "sent": False, "pending_approval": a["approval_id"]}

        m = METER.get()
        if m is not None:
            m.charge("sends")
        res = await self.mcp.tool("send_message", {"agent_id": self.agent_id, "signature": sig, "to": to, "body": body,
                                                   "scope": scope, **self._today()})
        rec.update(state="sent" if res.get("sent") else "blocked", decision=res["decision"],
                   guard_entry=res.get("ledger_entry"))
        self.log(f"  send      {'SENT ' if res.get('sent') else 'BLOCK'}  {who}"
                 + (": written to the outbox (never emailed)" if res.get("sent") else f": {'; '.join(blocked_by(res))}"))
        self._verdict("send", res, (f"Sent to {who}" if res.get("sent") else f"Blocked at send: {who}"), to)
        _add_send(tid, rec)
        if self.report is not None:
            self.report.allowed += int(bool(res.get("sent")))
        return res


def _add_send(task_id: str, rec: dict) -> None:
    store.task_mutate(task_id, lambda t: t["output"].setdefault("sends", []).append(rec))


async def execute_approval(approval_id: str, by: str, mcp: Any = None, body: str | None = None) -> dict:
    """A person approved a held draft: re-run the guard at send time and, only if it still clears, write the outbox.
    With `body`, the person edited the draft first: an in-house agent re-signs the edited text with its own key (an
    outside agent's key never leaves its machine, so its drafts can only be approved or rejected as written), and
    Send Guard checks the edited text from scratch."""
    edited = body is not None and body.strip() and body.strip() != (store.get_approval(approval_id) or {}).get("body", "").strip()
    if edited:
        cur = store.get_approval(approval_id)
        from .kinds import is_external
        if cur and is_external(registry.get_agent(cur["agent_id"])):
            raise ValueError("an outside agent's draft can't be edited here: reject it and ask the agent for a new one")
    met = _rules_before_send(approval_id, by, body.strip() if edited else None)
    if met is not None:
        return met  # recorded toward a quorum; still waiting for more people
    a = store.claim_approval(approval_id, by)
    if a is None:
        cur = store.get_approval(approval_id)
        raise ValueError(f"approval is {cur['status'] if cur else 'unknown'}")
    mcp = mcp or InprocMCP()
    if a.get("action") == "sign_offer":
        return await _sign_offer(a, by, mcp, body.strip() if edited else None)
    try:
        rec = registry.get_agent(a["agent_id"])
        pol = store.policy(a["agent_id"])["budget"]
        if store.usage(a["agent_id"])["sends"] >= pol["sends_per_day"]:
            raise BudgetExceeded(f"daily sends budget reached ({pol['sends_per_day']})")
        from ..rules import engine as rules
        hit = rules.cap_hit(rec, "sends")
        if hit:
            rules.enforced(hit, rec, "send", "blocked at approval", target=a["to"], approval_id=approval_id)
            raise BudgetExceeded(rules.explain(hit))
        if edited:
            from ..agents.models import Passport
            original = a["body"]
            a["body"] = body.strip()
            a["signature"] = sign_message(Passport.model_validate(rec["passport"]), registry.private_key(a["agent_id"]), a["body"])
            store.update_approval(approval_id, body=a["body"], signature=a["signature"], edited_by=by, original_body=original)
        args = {"agent_id": a["agent_id"], "signature": a["signature"], "to": a["to"], "body": a["body"],
                "scope": a["scope"]}
        if a.get("today"):
            args["today"] = a["today"]
        res = await mcp.tool("send_message", args)
        sent = bool(res.get("sent"))
        mail = None
        if sent:
            store.add_usage(a["agent_id"], sends=1)
            from ..agents import seal
            srec = seal.latest(a["agent_id"], seal.sha(a["body"]))
            if srec:
                mail = await seal.email_copy(srec, f"{rec['name']} (AI agent): a message for {a['to'].get('name') or 'you'}", a["to"])
                mail["verify_url"] = f"{seal.base_url()}/verify/{srec['seal_id']}"
        status = "sent" if sent else "blocked_at_send"
        result = {"sent": sent, "decision": res["decision"], "checks": res.get("checks", []),
                  "ledger_entry": res.get("ledger_entry"), "agent_status": rec.get("status"), "email": mail,
                  "verify_url": (mail or {}).get("verify_url")}
    except BudgetExceeded as e:
        status, result = "blocked_at_send", {"sent": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - fail closed: nothing was sent
        log.exception("approval %s failed", approval_id)
        status, result = "blocked_at_send", {"sent": False, "error": f"{type(e).__name__}: {e}"}
    entry = ledger.append("runtime.approval", {"agent_id": a["agent_id"], "approval_id": approval_id, "task_id": a["task_id"],
                                                "decision": "approved", "by": by, "outcome": status, "edited": bool(edited),
                                                "to": a["to"], "guard_entry": result.get("ledger_entry")})
    out = store.update_approval(approval_id, status=status, result={**result, "approval_entry": entry})
    _sync_send(a["task_id"], approval_id, status)
    return out


async def _sign_offer(a: dict, by: str, mcp: Any, edited: str | None) -> dict:
    """The employer approved an offer letter. Re-check the agent's passport for contract.sign right now (a sponsor who
    left since the draft voids it), then the agent signs the document's hash with its own key and the signature, the
    hash and the approver go on the ledger. Nothing is emailed: the signed letter is written to data/offers/."""
    from ..agents.models import Passport
    from ..fleet.demo import store_dir
    rec = registry.get_agent(a["agent_id"])
    if edited:
        store.update_approval(a["approval_id"], body=edited, edited_by=by, original_body=a["body"])
        a["body"] = edited
    doc = a["body"]
    sha = hashlib.sha256(doc.encode()).hexdigest()
    try:
        v = await mcp.tool("verify_agent", {"agent_id": a["agent_id"], "scope": "contract.sign"})
    except Exception as e:  # noqa: BLE001 - fail closed
        v = {"decision": "block", "checks": [{"name": "verify_agent", "status": "unverifiable", "detail": str(e)}]}
    sealed = doc
    if v.get("decision") == "allow" and rec["status"] == "active":
        from ..agents import seal
        p = Passport.model_validate(rec["passport"])
        sig = sign_message(p, registry.private_key(a["agent_id"]), doc)
        seal_id, sealed = seal.issue(p, sig, doc, "contract.sign", "offer_letter", a["to"])
        d = store_dir() / "offers"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{a['approval_id']}.txt").write_text(sealed + f"\n\nApproved by {by}. sha256 {sha}\n")
        entry = ledger.append("offer.signed", {"agent_id": a["agent_id"], "task_id": a["task_id"], "to": a["to"],
                                               "sha256": sha, "agent_signature": sig, "approved_by": by,
                                               "passport_check": v.get("ledger_entry"), "edited": bool(edited),
                                               "approvers": [x.get("by") for x in a.get("approvals") or []] or [by],
                                               "rules": [{k: h[k] for k in ("rule_id", "version", "sentence")}
                                                         for h in a.get("rules") or []]})
        mail = await seal.email_copy(seal.get(seal_id), f"Offer letter from {p.sponsor.company}: {a['to'].get('name')}", a["to"])
        status, result = "signed", {"signed": True, "sha256": sha, "signature": sig, "ledger_entry": entry,
                                    "checks": v.get("checks", []), "seal_id": seal_id,
                                    "verify_url": f"{seal.base_url()}/verify/{seal_id}", "email": mail}
    else:
        failed = [f"{c['name']}: {c['detail']}" for c in v.get("checks", []) if c.get("status") != "pass"]
        entry = ledger.append("offer.refused", {"agent_id": a["agent_id"], "task_id": a["task_id"], "sha256": sha,
                                                "approved_by": by, "why": failed[:3] or [rec["status"]]})
        status, result = "blocked_at_send", {"signed": False, "error": "; ".join(failed[:2]) or f"agent is {rec['status']}",
                                             "ledger_entry": entry, "checks": v.get("checks", [])}
    store.update_approval(a["approval_id"], status=status, result=result)

    def fn(t):
        o = t["output"].get("offer")
        if o:
            o.update(state="signed" if status == "signed" else "refused at signing", sha256=sha, signed_by=by,
                     signed_at=store.now(), letter=sealed if status == "signed" else doc,
                     verify_url=result.get("verify_url"))
    store.task_mutate(a["task_id"], fn)
    store.task_step(a["task_id"], f"Offer {'signed' if status == 'signed' else 'NOT signed'}: approved by {by}; "
                                  + ("passport re-checked for contract.sign, document hash signed and on the ledger"
                                     if status == "signed" else result["error"]), "control")
    return store.get_approval(a["approval_id"])


def _rules_before_send(approval_id: str, by: str, edited_body: str | None) -> dict | None:
    """Company rules, checked when a person approves (rules apply at action time, so a rule added after the draft
    still counts). A held send (quiet hours) raises: it stays pending and the 409 names the rule. An offer that needs
    more approvers records this person's approval and returns the approval, still pending; None = go ahead."""
    from ..rules import engine as rules
    cur = store.get_approval(approval_id)
    if not cur or cur["status"] != "pending":
        return None  # claim_approval reports the real status
    rec = registry.get_agent(cur["agent_id"])
    if cur.get("action") == "sign_offer":
        needed, hits = rules.offer_approvers(rec, (cur.get("terms") or {}).get("compensation"))
        if needed <= 1:
            store.update_approval(approval_id, approvals_needed=1, rules=[])
            return None
        if edited_body:
            # earlier approvals were for different text: the count restarts with the editor
            store.update_approval(approval_id, body=edited_body, edited_by=by, original_body=cur["body"],
                                  approvals_needed=needed, rules=hits)
            rules.reset_approvals(approval_id, by)
            a, met = store.get_approval(approval_id), needed <= 1
        else:
            try:
                a, met = rules.add_approver(approval_id, by, needed, hits)
            except rules.RuleError as e:
                raise ValueError(str(e))
        if met:
            return None
        n = len(a.get("approvals") or [])
        entry = ledger.append("runtime.approval", {"agent_id": cur["agent_id"], "approval_id": approval_id,
                                                    "task_id": cur["task_id"], "decision": "approved", "by": by,
                                                    "outcome": "needs_more_approvers", "approvals": n, "needed": needed,
                                                    "edited": bool(edited_body), "to": cur["to"], "action": "sign_offer",
                                                    "rules": [{k: h[k] for k in ("rule_id", "version", "sentence")} for h in hits]})
        rules.enforced(hits[0], rec, "sign_offer", f"waiting for approver {n + 1} of {needed}", target=cur["to"],
                       approval_id=approval_id, task_id=cur["task_id"], approvals=n, needed=needed)
        store.task_step(cur["task_id"], f"{by} approved the offer ({n} of {needed}). {rules.explain(hits[0])}. "
                                        "Waiting for another person.", "control")
        store.task_mutate(cur["task_id"], lambda t: (t["output"].get("offer") or {}).update(
            state=f"approved by {n} of {needed}: waiting for another approver", approvals=a.get("approvals"),
            approvals_needed=needed))
        return store.update_approval(approval_id, last_entry=entry)
    holds = [h for h in rules.send_hits(rec, cur.get("to"), cur.get("scope")) if h["effect"] == "hold"]
    if holds:
        rules.enforced(holds[0], rec, "send", "approval refused for now; still pending", target=cur.get("to"),
                       approval_id=approval_id)
        store.update_approval(approval_id, rules=holds)
        raise ValueError(f"{rules.explain(holds[0])}. It stays in your inbox: approve it after then.")
    return None


def reject_approval(approval_id: str, by: str, note: str | None = None) -> dict:
    a = store.get_approval(approval_id)
    if not a or a["status"] != "pending":
        raise ValueError(f"approval is {a['status'] if a else 'unknown'}")
    entry = ledger.append("runtime.approval", {"agent_id": a["agent_id"], "approval_id": approval_id, "task_id": a["task_id"],
                                                "decision": "rejected", "by": by, "note": note, "to": a["to"]})
    out = store.update_approval(approval_id, status="rejected", decided_by=by, decided_at=store.now(), note=note,
                                result={"sent": False, "approval_entry": entry})
    _sync_send(a["task_id"], approval_id, "rejected")
    if a.get("action") == "sign_offer":
        store.task_mutate(a["task_id"], lambda t: (t["output"].get("offer") or {}).update(state="rejected", signed_by=by))
    return out


def _sync_send(task_id: str, approval_id: str, state: str) -> None:
    body = (store.get_approval(approval_id) or {}).get("body")

    def fn(t):
        for s in t["output"].get("sends", []):
            if s.get("approval_id") == approval_id:
                s["state"] = state
                if body and s.get("body") != body:
                    s["body"], s["edited"] = body, True
    store.task_mutate(task_id, fn)
