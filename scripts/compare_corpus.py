"""Compare corpus runs against two SQLite releases (and optionally a patched runner).

Usage:
    docker run --rm -v "$PWD/out:/out" msqdiff:3541 corpus --no-columns --quiet --out /out/corpus_3541.json
    docker run --rm -v "$PWD/out:/out" msqdiff:3533 corpus --no-columns --quiet --out /out/corpus_3533.json
    python scripts/compare_corpus.py out/corpus_3541.json out/corpus_3533.json [out/corpus_patched.json]

A divergence is identified by its case id. The report says how many each run has, how many
the two SQLite releases have in common, and which differ between them. Differences that only
one release shows are version drift in SQLite, not in minisqlite, and are listed so that
nobody mistakes them for findings.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

SOFT = ("error-text", "error-code", "columns")


def load(path: str) -> dict[str, dict]:
    return {r["id"]: r for r in json.loads(Path(path).read_text(encoding="ascii"))}


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        sys.exit(__doc__)
    runs = {"newer SQLite": load(argv[0]), "older SQLite": load(argv[1])}
    if len(argv) == 3:
        runs["patched runner"] = load(argv[2])
    for name, d in runs.items():
        cats = Counter(r["category"] for r in d.values())
        print(f"{name}: {len(d)} divergences {dict(cats)}")
    a, b = (set(d) for d in list(runs.values())[:2])
    print(f"in both SQLite releases: {len(a & b)}; only the newer: {len(a - b)}; only the older: {len(b - a)}")
    for i in sorted(a - b):
        print(f"  only the newer: {i} {list(runs.values())[0][i]['sql']}")
    for i in sorted(b - a):
        print(f"  only the older: {i} {list(runs.values())[1][i]['sql']}")
    both = a & b
    first = list(runs.values())[0]
    print(f"in both, by category: {dict(Counter(first[i]['category'] for i in both))}")
    print(f"in both, behavioural (not {', '.join(SOFT)}): {sum(1 for i in both if first[i]['category'] not in SOFT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
