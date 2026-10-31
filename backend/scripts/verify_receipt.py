"""Check a Countersign receipt offline: entry hash, chain link and issuer signature (plus the live ledger if present).

    python scripts/verify_receipt.py receipt.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.receipts import verify_receipt  # noqa: E402

if __name__ == "__main__":
    res = verify_receipt(json.loads(Path(sys.argv[1]).read_text()))
    for c in res["checks"]:
        print(f"{c['status'].upper():5} {c['name']}: {c['detail']}")
    print("VALID" if res["valid"] else "INVALID", f"entry #{res['entry']['seq']} {res['entry']['kind']}")
    sys.exit(0 if res["valid"] else 1)
