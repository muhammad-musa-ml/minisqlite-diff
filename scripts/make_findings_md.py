"""Write findings/FINDINGS.md from findings/findings.json and the measured answers.

Usage (from the repository root):
    python scripts/make_findings_md.py

Inputs:
    findings/findings.json         the repros, their status and where the cause sits
    findings/measured_3541.json    `check --out` against SQLite 3.54.1, pinned minisqlite
    findings/measured_3533.json    `check --out` against SQLite 3.53.3, pinned minisqlite
    findings/measured_patched.json `check --out --patched` against SQLite 3.54.1, local fix
    findings/measured_3500.json    `check --out` against SQLite 3.50.0 (the release minisqlite reports)
    findings/measured_3401.json    `check --out` against SQLite 3.40.1 (the Debian library, pinned build removed)

Every answer printed in FINDINGS.md is copied from those files; nothing is typed by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIND = ROOT / "findings"
PINNED = "4a5c1341fdde38beaf438e0241c9f45833c4b870"

KIND = {
    "wrong-result": "wrong result",
    "accepted-rejected": "accepted by one engine, rejected by the other",
    "unsupported": "feature missing",
}


def load(name: str) -> list[dict]:
    return json.loads((FIND / name).read_text(encoding="utf-8"))


def by_id(rows: list[dict], what: str, ids: list[str]) -> dict[str, dict]:
    got = {r["id"]: r for r in rows}
    if list(got) != ids:
        sys.exit(f"{what}: ids {list(got)} differ from findings.json ids {ids}")
    for r in rows:
        for key in ("sqlite_answer", "minisqlite_answer", "reproduces"):
            if key not in r:
                sys.exit(f"{what}: row {r.get('id')} has no {key}; regenerate it with `check --out`")
    return got


def code(s: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", s)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if s.startswith("`") or s.endswith("`") else ""
    return f"{fence}{pad}{s}{pad}{fence}"


def ascii_only(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def main() -> int:
    spec = load("findings.json")
    ids = [f["id"] for f in spec]
    m41 = by_id(load("measured_3541.json"), "measured_3541.json", ids)
    m33 = by_id(load("measured_3533.json"), "measured_3533.json", ids)
    mpa = by_id(load("measured_patched.json"), "measured_patched.json", ids)
    m35 = by_id(load("measured_3500.json"), "measured_3500.json", ids)
    m34 = by_id(load("measured_3401.json"), "measured_3401.json", ids)
    older = (("3.50.0", m35), ("3.40.1", m34))

    out: list[str] = []
    w = out.append
    fixed = [f for f in spec if f["status"] == "fixed"]
    opened = [f for f in spec if f["status"] == "open"]
    w("# Findings")
    w("")
    w(f"{len(spec)} minimal repros against `cursor/minisqlite` at commit `{PINNED}`, each replayed")
    w("with `python -m msqdiff check` on SQLite 3.54.1 and SQLite 3.53.3. A row is listed only when both")
    w("SQLite releases give the same answer and minisqlite gives a different one; the two releases agree")
    w(f"on all {len(spec)} (see `measured_3541.json` and `measured_3533.json`).")
    w("")
    n35 = sum(1 for f in spec if m35[f["id"]]["reproduces"])
    n34 = sum(1 for f in spec if m34[f["id"]]["reproduces"])
    w("SQLite changes between releases, and minisqlite's `sqlite_version()` reports 3.50.0 while a comment in its")
    w("source cites a documentation change of 3.52.0, so the same repros were also run on SQLite 3.50.0 and on")
    w(f"the SQLite 3.40.1 that the Debian base image ships. {n35} of {len(spec)} differ on 3.50.0 and {n34} of {len(spec)} on 3.40.1;")
    w("the table says which, and each finding below shows the answer of an older release when it is not the")
    w("answer of 3.54.1. The 3.50.0 and 3.40.1 columns are recorded measurements and are not rerun in CI.")
    w("")
    w(f"- **fixed** ({len(fixed)}): the difference is gone on a local fix branch, with regression tests. That branch is not published (the upstream repository has no licence).")
    w(f"- **open** ({len(opened)}): the difference is still there and nothing was changed for it.")
    w("")
    w("What counts as a difference: the rows (values compared exactly, a real by its bit pattern), or one engine")
    w("accepting a statement the other rejects. Error wording, error codes and result-column names are not")
    w("findings: SQLite documents column names as unspecified, and minisqlite's own source says it does not")
    w("match error text. Error messages are shown below only to make a repro readable.")
    w("")
    w("| id | status | kind | differs on 3.40.1 / 3.50.0 / 3.53.3 / 3.54.1 | what differs |")
    w("|---|---|---|---|---|")
    for f in spec:
        yn = " / ".join("yes" if d[f["id"]]["reproduces"] else "no" for d in (m34, m35, m33, m41))
        w(f"| {f['id']} | {f['status']} | {KIND.get(f['kind'], f['kind'])} | {yn} | {f['title'].replace('|', '/')} |")
    w("")
    for f in spec:
        i = f["id"]
        w(f"## {i} ({f['status']}): {f['title']}")
        w("")
        w("```sql")
        for st in f.get("setup", []):
            w(st.rstrip(";") + ";")
        w(f["sql"].rstrip(";") + ";")
        w("```")
        w("")
        if m41[i]["sqlite_answer"] != m33[i]["sqlite_answer"] or m41[i]["minisqlite_answer"] != m33[i]["minisqlite_answer"]:
            sys.exit(f"{i}: SQLite 3.54.1 and 3.53.3 answers differ; this finding needs a version note")
        w(f"- SQLite 3.54.1 and 3.53.3: {code(ascii_only(m41[i]['sqlite_answer']))}")
        w(f"- minisqlite at `{PINNED[:7]}`: {code(ascii_only(m41[i]['minisqlite_answer']))}")
        for rel, d in older:
            if d[i]["sqlite_answer"] != m41[i]["sqlite_answer"]:
                same = "the same as minisqlite" if not d[i]["reproduces"] else "different from minisqlite"
                w(f"- SQLite {rel} answers differently: {code(ascii_only(d[i]['sqlite_answer']))} ({same})")
        if f["status"] == "fixed":
            w(f"- minisqlite with the local fix: {code(ascii_only(mpa[i]['minisqlite_answer']))}")
        if f.get("where"):
            w(f"- Where in the source: {f['where']}")
        w("")
    text = "\n".join(out) + "\n"
    (FIND / "FINDINGS.md").write_text(ascii_only(text), encoding="ascii", newline="\n")
    print(f"wrote findings/FINDINGS.md: {len(spec)} findings ({len(fixed)} fixed, {len(opened)} open)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
