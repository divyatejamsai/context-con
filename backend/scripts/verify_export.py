"""Check an Agaxes audit export offline:  python scripts/verify_export.py agaxes-ledger.jsonl [--issuer-key <b64>]

Without --issuer-key it trusts the key named in the manifest (proves nothing was edited since export); pass the key
from GET /api/passport/issuer to also prove the export came from that Agaxes. Exit code 0 = every check passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--issuer-key")
    a = ap.parse_args()
    from app.agents.audit import verify_export
    res = verify_export(Path(a.file).read_text(), a.issuer_key)
    for c in res["checks"]:
        print(f"{'PASS' if c['status'] == 'pass' else 'FAIL'}  {c['name']}: {c['detail']}")
    print(json.dumps({"ok": res["ok"], "count": res.get("count")}))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
