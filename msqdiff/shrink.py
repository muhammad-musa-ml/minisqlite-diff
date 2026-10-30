"""Reduce a diverging case to a small one.

No SQL parser is needed. The statement is cut into tokens and candidate edits are
tried against both engines; an edit is kept only if the case still diverges in the
same category. Edits: drop a run of tokens (delta debugging), replace a
parenthesised group by its contents or by a constant, replace a call f(a, b) by
its first argument. Setup statements are dropped one at a time and in chunks.
"""

from __future__ import annotations

import re
from typing import Callable

from .harness import Case, Pair

_TOKEN = re.compile(
    r"'(?:[^']|'')*'|\"[^\"]*\"|x'[0-9a-fA-F]*'|\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+|\w+|<<|>>|<=|>=|<>|!=|==|\|\||->>|->|\s+|.",
    re.S,
)


def tokens(sql: str) -> list[str]:
    return _TOKEN.findall(sql)


def _sig(sql: str) -> str:
    return "".join(sql.split())


def order_by_clause(sql: str) -> str | None:
    """The outermost ORDER BY and everything after it, whitespace-normalised, or None.

    Only a clause at parenthesis depth zero counts: an ORDER BY inside a window
    definition or a subquery does not order the rows the statement returns, and a
    string literal that happens to say ORDER BY is a single token.
    """
    toks = tokens(sql)
    depth = 0
    for i, t in enumerate(toks):
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        elif depth == 0 and t.upper() == "ORDER":
            j = i + 1
            while j < len(toks) and toks[j].isspace():
                j += 1
            if j < len(toks) and toks[j].upper() == "BY":
                return " ".join("".join(toks[i:]).split())
    return None


def _matching(toks: list[str], i: int) -> int:
    """Index of the ')' that closes the '(' at toks[i], or -1."""
    depth = 0
    for j in range(i, len(toks)):
        if toks[j] == "(":
            depth += 1
        elif toks[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _split_top(toks: list[str]) -> list[list[str]]:
    parts: list[list[str]] = [[]]
    depth = 0
    for t in toks:
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        if t == "," and depth == 0:
            parts.append([])
        else:
            parts[-1].append(t)
    return parts


def candidates(toks: list[str]):
    """Yield smaller token lists, most aggressive first."""
    n = len(toks)
    # 1. paren groups and calls
    for i, t in enumerate(toks):
        if t != "(":
            continue
        j = _matching(toks, i)
        if j < 0:
            continue
        inner = toks[i + 1 : j]
        # function call: name ( args ) -> first arg
        k = i - 1
        while k >= 0 and toks[k].isspace():
            k -= 1
        if k >= 0 and re.match(r"^\w+$", toks[k]) and toks[k].upper() not in ("IN", "AS", "ON", "AND", "OR", "NOT", "BY", "FROM", "WHERE", "OVER", "FILTER", "USING", "VALUES", "SELECT"):
            first = _split_top(inner)[0]
            if first:
                yield toks[:k] + ["("] + first + [")"] + toks[j + 1 :]
        yield toks[:i] + inner + toks[j + 1 :]
        for const in ("1", "0", "NULL", "''"):
            yield toks[:i] + [const] + toks[j + 1 :]
    # 2. drop windows of tokens
    size = max(1, n // 2)
    while size >= 1:
        for s in range(0, n - size + 1):
            yield toks[:s] + toks[s + size :]
        size //= 2


def shrink(pair: Pair, case: Case, category: str, in_setup: bool, budget: int = 600) -> Case:
    seen: dict[str, bool] = {}
    used = [0]
    # A row-order difference only means something while the whole ORDER BY clause, with
    # every sort key, is still there: without it, or with a key dropped, the statement
    # leaves the order open and the engines are free to differ.
    order_clause = order_by_clause(case.sql) if category == "row-order" and not in_setup else None

    def holds(c: Case) -> bool:
        key = "\x00".join(c.setup) + "\x01" + c.sql
        if key in seen:
            return seen[key]
        if category == "row-order" and not in_setup and (order_clause is None or order_by_clause(c.sql) != order_clause):
            seen[key] = False
            return False
        if used[0] >= budget:
            return False
        used[0] += 1
        d = pair.run_case(c)
        ok = d is not None and d.category == category
        if ok and not in_setup:
            ok = d.sql == c.sql
        seen[key] = ok
        return ok

    best = Case(case.id, list(case.setup), case.sql, case.ordered)
    changed = True
    while changed and used[0] < budget:
        changed = False
        # setup statements: drop one at a time, then in halves
        i = 0
        while i < len(best.setup):
            trial = Case(best.id, best.setup[:i] + best.setup[i + 1 :], best.sql, best.ordered)
            if holds(trial):
                best = trial
                changed = True
            else:
                i += 1
        if in_setup:
            # shrink the last setup statement instead of the query
            if best.setup:
                last = best.setup[-1]
                for cand in candidates(tokens(last)):
                    s = "".join(cand).strip()
                    if not s or _sig(s) == _sig(last):
                        continue
                    trial = Case(best.id, best.setup[:-1] + [s], best.sql, best.ordered)
                    if holds(trial):
                        best = trial
                        changed = True
                        break
            continue
        # the query: first accepted edit, then restart from the smaller query
        for cand in candidates(tokens(best.sql)):
            s = "".join(cand).strip()
            if not s or _sig(s) == _sig(best.sql):
                continue
            trial = Case(best.id, best.setup, s, best.ordered)
            if holds(trial):
                best = trial
                changed = True
                break
    # tidy: collapse runs of whitespace
    best = Case(best.id, [" ".join(x.split()) for x in best.setup], " ".join(best.sql.split()), best.ordered)
    return best


def skeleton(sql: str) -> str:
    """A key that ignores literal values, so equal root causes cluster together."""
    s = re.sub(r"'(?:[^']|'')*'", "'S'", sql)
    s = re.sub(r"x'[0-9a-fA-F]*'", "x'B'", s)
    s = re.sub(r"\b\d+(?:\.\d*)?(?:[eE][+-]?\d+)?\b", "N", s)
    return " ".join(s.split()).upper()
