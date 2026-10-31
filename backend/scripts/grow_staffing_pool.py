"""Grow the recorded shift-staffing applicant pool with live Crustdata Person Searches, one per role, for every template.

    cd backend && python scripts/grow_staffing_pool.py                       # every template, default sizes
    cd backend && python scripts/grow_staffing_pool.py --template hospital --per-role 400

Needs CRUSTDATA_API_KEY (CRUSTDATA_MODE=cache, the default, so pages already fetched are free). Quick-commerce goes to
fixtures/staffing/pool.json, every other template to fixtures/staffing-<template>/pool.json; the API reads them all.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND.parent / ".env")
load_dotenv(BACKEND / ".env")

SIZES = {"quick-commerce": 500, "bpo": 300, "retail-seasonal": 300, "hospital": 300, "events": 300, "campus": 400}


async def main(a) -> None:
    from app.talent.api import grow_pool
    from app.talent.staffing import DEFAULT_TEMPLATE, TEMPLATES, template

    tids = [t["id"] for t in TEMPLATES] if a.template == "all" else [a.template]
    for tid in tids:
        t0 = time.time()
        per = a.per_role or SIZES.get(tid, 300)

        async def prog(role: str, n: int) -> None:
            print(f"  {role}: {n} people")
        print(f"[{tid}] searching {per} per role")
        out = await grow_pool(template(tid), per, "staffing" if tid == DEFAULT_TEMPLATE else f"staffing-{tid}", prog)
        print(f"[{tid}] {out['found']} found, {out['new']} new, pool now {out['total']} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--template", default="all")
    p.add_argument("--per-role", type=int, default=0)
    asyncio.run(main(p.parse_args()))
