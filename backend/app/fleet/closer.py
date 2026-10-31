"""Closer, an AI sales rep for PulseTrader whose sponsor has left the company.

Its passport still says it acts for PulseTrader's co-founder. Crustdata says he left in April 2026 and works
somewhere else now, so the payroll run suspends Closer and revokes its passport. Closer doesn't know that: it
clocks in and tries to send a demo invite anyway, the way a forgotten agent on a cron job would. Both are refused.
"""
from __future__ import annotations

from .base import Ctx, Report

JOB = "Books demos for PulseTrader's trading API (sponsor left the company)"


async def run(ctx: Ctx, target: dict) -> Report:
    rep = ctx.report = Report(agent=ctx.agent["name"], job=JOB, expected="refused at clock-in and at send")
    status = ctx.agent.get("status")
    ctx.log(f"  registry  status {status}" + (f": {ctx.agent.get('reason')}" if ctx.agent.get("reason") else ""))
    clocked_in = await ctx.clock_in("outreach.sales")
    first = target["name"].split()[0]
    body = (f"Hi {first}, PulseTrader's trading API gives your team at {target['company']} real-time market data. "
            f"Open to a 15-minute demo this week?\n\nCloser (AI assistant to {ctx.passport.sponsor.name}, PulseTrader)")
    ctx.log("  draft     a demo invite queued before the sponsor left; Closer tries to send it")
    v = await ctx.send(target, body, "outreach.sales")
    rep.ok = not clocked_in and not v.get("sent")
    return rep
