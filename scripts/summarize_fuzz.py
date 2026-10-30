"""Summarise sharded fuzz runs written by scripts/run_shards.ps1.

Usage: python scripts/summarize_fuzz.py out/fuzz3541 out/fuzz3533 out/fuzzpatched

Prints, per run directory, the seeds covered, the behavioural divergences by category
(wording-only and tie-only differences are listed apart), how many of them were shrunk,
and the shrunk clusters per family. The family is assigned from the shrunk repro by simple
patterns, so it is a reading aid, not a measurement: a cluster that matches none lands in
"other".
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

HEAD = re.compile(r"fuzz seeds (\d+)\.\.(\d+) \((\d+) cases\) \| behavioural divergences: (\d+)")
NOT_COUNTED = re.compile(r"(?:not counted \(wording, ties\)|wording only \(ignored\)): (\{[^}]*\})")
CATEGORY = re.compile(r"^  ([a-z][a-z-]*): (\d+)$")
DATEFN = re.compile(r"\b(date|datetime|time|julianday|unixepoch|strftime|timediff)\s*\(", re.I)


def family(e: dict) -> str:
    text = e["sql"] + " " + " ".join(e["setup"])
    if re.search(r"e[+-]1[5-6]|1e1[5-6]", e["minisqlite"]) and not re.search(r"e[+-]1[5-6]", e["sqlite"]):
        return "real-to-text, 1e15 to 1e17"
    if DATEFN.search(text):
        return "date and time"
    if e["category"] == "accept-reject" and "NOT NULL constraint failed" in e["minisqlite"] and re.search(r"\bREPLACE\b", text, re.I):
        return "REPLACE into NOT NULL with DEFAULT"
    if re.search(r"\bGROUP BY\b|\bHAVING\b", e["sql"], re.I) and e["category"] == "accept-reject":
        return "GROUP BY / HAVING acceptance"
    return "other"


def read_report(txt: Path) -> tuple[int, int, Counter, Counter]:
    """Cases, behavioural divergences, divergences by category, uncounted differences by category."""
    lines = txt.read_text(encoding="ascii", errors="replace").splitlines()
    m = HEAD.search(lines[0])
    if not m:
        sys.exit(f"{txt}: first line is not a fuzz report")
    uncounted = NOT_COUNTED.search(lines[0])
    ignored = Counter(ast.literal_eval(uncounted.group(1))) if uncounted else Counter()
    by_cat: Counter = Counter()
    for line in lines[1:]:
        if line.startswith("clusters after shrinking"):
            break
        c = CATEGORY.match(line)
        if c:
            by_cat[c.group(1)] += int(c.group(2))
    if sum(by_cat.values()) != int(m.group(4)):
        sys.exit(f"{txt}: categories add up to {sum(by_cat.values())}, the header says {m.group(4)}")
    return int(m.group(3)), int(m.group(4)), by_cat, ignored


def main(dirs: list[str]) -> int:
    for d in dirs:
        root = Path(d)
        cases = divergences = shrunk_seeds = 0
        fam: Counter[str] = Counter()
        cats: Counter[str] = Counter()
        uncounted: Counter[str] = Counter()
        clusters = 0
        for txt in sorted(root.glob("shard*.txt")):
            n, div, by_cat, ign = read_report(txt)
            cases += n
            divergences += div
            cats.update(by_cat)
            uncounted.update(ign)
        for js in sorted(root.glob("shard*.json")):
            for e in json.loads(js.read_text(encoding="ascii")):
                clusters += 1
                shrunk_seeds += len(e["seeds"])
                fam[family(e)] += 1
        print(f"{d}: {cases} seeds, {divergences} behavioural divergences, {shrunk_seeds} shrunk into {clusters} clusters")
        print("    by category: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()))
        print("    not counted (wording, ties): " + (", ".join(f"{k} {v}" for k, v in uncounted.most_common()) or "none"))
        for name, n in fam.most_common():
            print(f"    {n:4d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
