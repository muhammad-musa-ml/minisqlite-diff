"""Replay the recorded findings and say whether each still reproduces.

`findings/findings.json` lists minimal repros. Each has a status:

    "open"   the divergence is expected on the pinned minisqlite and on a patched one
    "fixed"  the divergence is expected on the pinned minisqlite and gone on the patched
             checkout (the fix branch under vendor/minisqlite-fixed)

`check` runs every repro on SQLite and on minisqlite and compares the outcome with the
expectation for the checkout under test, so a fix that regresses, a fix that does not
take, or a SQLite release that changes its answer all turn up as a failed row.
"""

from __future__ import annotations

from dataclasses import dataclass

from .harness import Pair, op_for
from .model import SOFT, Result, compare


@dataclass
class Row:
    id: str
    status: str
    reproduces: bool
    expected: bool
    sqlite: Result
    mini: Result

    @property
    def ok(self) -> bool:
        return self.reproduces == self.expected


def check_findings(pair: Pair, spec: list[dict], patched: bool) -> list[Row]:
    """Run each finding on both engines.

    On the pinned checkout (`patched` false) every finding must reproduce. On the patched
    checkout a "fixed" finding must agree and every other finding must still reproduce.
    """
    rows: list[Row] = []
    for f in spec:
        pair.fresh()
        for st in f.get("setup", []):
            pair.step(st, False, check_columns=False)
        sql = f["sql"]
        op = op_for(sql)
        a = pair.oracle.run(op, sql)
        b = pair.runner.run(op, sql)
        d = compare(sql, False, a, b, check_columns=False)
        reproduces = d is not None and d.category not in SOFT
        expected = not (patched and f["status"] == "fixed")
        rows.append(Row(f["id"], f["status"], reproduces, expected, a, b))
    return rows
