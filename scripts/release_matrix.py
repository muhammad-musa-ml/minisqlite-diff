"""Print, for every recorded finding, whether it differs from minisqlite on each SQLite release measured.

Usage (from the repository root):
    python scripts/release_matrix.py

Reads findings/findings.json and findings/measured_<release>.json for 3.40.1, 3.50.0, 3.53.3 and
3.54.1. The measured files come from `check --out`; see findings/FINDINGS.md for how each was made.
3.50.0 is the release minisqlite's sqlite_version() reports; 3.40.1 is the SQLite that the Debian base
image ships. The answers differ between releases, and a finding is only as general as this table says.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIND = ROOT / "findings"
RELEASES = [("3.40.1", "measured_3401.json"), ("3.50.0", "measured_3500.json"), ("3.53.3", "measured_3533.json"), ("3.54.1", "measured_3541.json")]


def load() -> tuple[list[dict], dict[str, dict[str, dict]]]:
    spec = json.loads((FIND / "findings.json").read_text(encoding="utf-8"))
    ids = [f["id"] for f in spec]
    data: dict[str, dict[str, dict]] = {}
    for rel, name in RELEASES:
        rows = json.loads((FIND / name).read_text(encoding="ascii"))
        if [r["id"] for r in rows] != ids:
            sys.exit(f"{name}: ids differ from findings.json")
        data[rel] = {r["id"]: r for r in rows}
    return spec, data


def main() -> int:
    spec, data = load()
    print("id    status  " + "  ".join(f"{rel:>7}" for rel, _ in RELEASES))
    for f in spec:
        cells = ["differs" if data[rel][f["id"]]["reproduces"] else "agrees " for rel, _ in RELEASES]
        print(f"{f['id']}  {f['status']:6s}  " + "  ".join(cells))
    print()
    print("findings that differ from minisqlite, per release: " + ", ".join(f"{rel}: {sum(1 for f in spec if data[rel][f['id']]['reproduces'])} of {len(spec)}" for rel, _ in RELEASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
