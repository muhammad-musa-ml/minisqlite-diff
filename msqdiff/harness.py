"""Run one case on both engines and compare."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .engines import Oracle, Runner
from .model import Divergence, compare

_ROW_STATEMENTS = re.compile(r"^\s*\(?\s*(select|with|values|pragma|explain)\b", re.IGNORECASE)
_RETURNING = re.compile(r"\breturning\b", re.IGNORECASE)


def op_for(sql: str) -> str:
    """Q when the statement can produce rows, E otherwise."""
    if _ROW_STATEMENTS.match(sql) or _RETURNING.search(sql):
        return "Q"
    return "E"


@dataclass
class Case:
    """Setup statements followed by one statement under test."""

    id: str
    setup: list[str]
    sql: str
    ordered: bool = False
    tags: list[str] = field(default_factory=list)


class Pair:
    """A SQLite oracle and a minisqlite runner kept in step."""

    def __init__(self, runner: Runner | None = None) -> None:
        self.oracle = Oracle()
        self.runner = runner or Runner()

    def fresh(self) -> None:
        self.oracle.reset()
        self.runner.reset()

    def close(self) -> None:
        self.oracle.close()
        self.runner.close()

    def step(self, sql: str, ordered: bool = False, check_columns: bool = True) -> Divergence | None:
        op = op_for(sql)
        a = self.oracle.run(op, sql)
        b = self.runner.run(op, sql)
        return compare(sql, ordered, a, b, check_columns)

    def run_case(self, case: Case, check_columns: bool = True) -> Divergence | None:
        """The first divergence in the case, or None. Setup statements count."""
        self.fresh()
        for stmt in case.setup:
            d = self.step(stmt, False, check_columns)
            if d is not None:
                return d
        return self.step(case.sql, case.ordered, check_columns)
