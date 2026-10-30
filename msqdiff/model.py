"""Result model and comparison rules shared by both engines.

A value is a tagged pair so the comparison is exact:
    ("n",)            NULL
    ("i", "123")      INTEGER, decimal text
    ("r", "3ff0...")  REAL, IEEE-754 bit pattern as 16 hex digits
    ("t", "text")     TEXT
    ("b", "00ff")     BLOB, hex

Reals compare by bit pattern, so 0.0 and -0.0 differ and the last digit of a
float counts. A divergence is therefore a real difference in what the engine
stored or returned, never an artifact of printing.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

Value = tuple


def v_null() -> Value:
    return ("n",)


def v_int(i: int) -> Value:
    return ("i", str(i))


def v_real(f: float) -> Value:
    return ("r", struct.pack(">d", f).hex())


def v_text(s: str) -> Value:
    return ("t", s)


def v_blob(b: bytes) -> Value:
    return ("b", b.hex())


def from_python(x: Any) -> Value:
    """Tag a value returned by Python's sqlite3 module."""
    if x is None:
        return v_null()
    if isinstance(x, bool):
        return v_int(int(x))
    if isinstance(x, int):
        return v_int(x)
    if isinstance(x, float):
        return v_real(x)
    if isinstance(x, str):
        return v_text(x)
    if isinstance(x, (bytes, bytearray, memoryview)):
        return v_blob(bytes(x))
    raise TypeError(f"unexpected sqlite3 value type {type(x)!r}")


def from_json(cell: list) -> Value:
    """Tag a cell decoded from msq-runner's JSON."""
    return tuple(cell)


def show(v: Value) -> str:
    """Human-readable form of a tagged value."""
    tag = v[0]
    if tag == "n":
        return "NULL"
    if tag == "i":
        return v[1]
    if tag == "r":
        f = struct.unpack(">d", bytes.fromhex(v[1]))[0]
        return f"{f!r}(real)"
    if tag == "t":
        return repr(v[1])
    return "x'" + v[1] + "'"


@dataclass
class Result:
    """What one engine did with one statement."""

    kind: str  # "ok" (no rows), "rows", "err", "panic", "hang"
    cols: list[str] = field(default_factory=list)
    rows: list[list[Value]] = field(default_factory=list)
    message: str = ""
    code: int = 0

    def answer(self, limit: int = 6) -> str:
        """What the engine said, without column names: the rows, the error, or "ok"."""
        if self.kind == "rows":
            shown = ["(" + ", ".join(show(c) for c in r) + ")" for r in self.rows[:limit]]
            more = "" if len(self.rows) <= limit else f" ... +{len(self.rows) - limit} rows"
            return f"{len(self.rows)} rows: " + "; ".join(shown) + more
        return self.brief(limit)

    def brief(self, limit: int = 6) -> str:
        if self.kind == "rows":
            shown = ["(" + ", ".join(show(c) for c in r) + ")" for r in self.rows[:limit]]
            more = "" if len(self.rows) <= limit else f" ... +{len(self.rows) - limit} rows"
            return f"{len(self.rows)} rows cols={self.cols}: " + "; ".join(shown) + more
        if self.kind == "err":
            return f"error[{self.code}] {self.message}"
        if self.kind in ("panic", "hang"):
            return f"{self.kind}: {self.message}"
        return "ok"


def _canon_rows(rows: list[list[Value]]) -> list[tuple]:
    return sorted(tuple(r) for r in rows)


# SQLite's NOCASE collation folds ASCII letters only.
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _tie_key(v: Value) -> tuple:
    """A key under which values that ORDER BY may treat as equal are equal.

    ORDER BY does not tell 0, 0.0 and -0.0 apart, and a column with COLLATE NOCASE or
    COLLATE RTRIM does not tell 'a' from 'A ' apart, so rows that differ only in such
    values may legitimately come back in either order. Integers and reals compare as
    numbers (exactly: Python compares int and float without rounding), text by ASCII
    case and trailing spaces; NULL, blobs and values of different kinds stay distinct.
    """
    tag = v[0]
    if tag == "i":
        return ("num", int(v[1]))
    if tag == "r":
        f = struct.unpack(">d", bytes.fromhex(v[1]))[0]
        return ("nan",) if f != f else ("num", f)
    if tag == "t":
        return ("t", v[1].translate(_ASCII_LOWER).rstrip(" "))
    return v


def _tie_rows(rows: list[list[Value]]) -> list[tuple]:
    return [tuple(_tie_key(c) for c in r) for r in rows]


_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)


def _has_limit(sql: str) -> bool:
    """True if LIMIT appears outside a string literal."""
    return _LIMIT.search(_STRING_LITERAL.sub("''", sql)) is not None


@dataclass
class Divergence:
    category: str  # see CATEGORIES
    sql: str
    sqlite: Result
    mini: Result

    def line(self) -> str:
        return f"[{self.category}] {self.sql}\n    sqlite: {self.sqlite.brief()}\n    mini:   {self.mini.brief()}"


CATEGORIES = (
    "panic",  # minisqlite panicked
    "hang",  # minisqlite did not answer in time
    "accept-reject",  # one engine runs the statement, the other refuses it
    "rows",  # same statement, different rows
    "row-order",  # same rows, different order of rows that do not tie under a top-level ORDER BY
    "limit-tie",  # a LIMIT cut a group of tied rows differently: either answer is allowed
    "columns",  # same rows, different column names
    "error-text",  # both refuse, different message text
    "error-code",  # both refuse, same text, different primary code
)

# Categories that describe wording, naming or an allowed choice between tied rows, not
# behaviour. SQLite documents result-column names as unspecified, minisqlite's own
# source says it does not match error wording exactly, and ORDER BY leaves tied rows
# in any order. They are counted but never reported as findings.
SOFT = {"columns", "error-text", "error-code", "limit-tie"}


def compare(sql: str, ordered: bool, a: Result, b: Result, check_columns: bool = True) -> Divergence | None:
    """Compare SQLite (a) with minisqlite (b). None means they agree."""
    if b.kind == "panic":
        return Divergence("panic", sql, a, b)
    if b.kind == "hang":
        return Divergence("hang", sql, a, b)
    a_fail = a.kind == "err"
    b_fail = b.kind == "err"
    if a_fail != b_fail:
        return Divergence("accept-reject", sql, a, b)
    if a_fail and b_fail:
        if a.message != b.message:
            return Divergence("error-text", sql, a, b)
        if a.code != b.code:
            return Divergence("error-code", sql, a, b)
        return None
    # Both ran. "ok" (no result set) and "rows" with no columns are the same thing.
    a_rows = a.rows if a.kind == "rows" else []
    b_rows = b.rows if b.kind == "rows" else []
    a_cols = a.cols if a.kind == "rows" else []
    b_cols = b.cols if b.kind == "rows" else []
    if ordered:
        if a_rows != b_rows:
            if _canon_rows(a_rows) != _canon_rows(b_rows):
                # Under a LIMIT the cut may fall inside a group of tied rows, and then
                # either engine may return any member of the group.
                if _has_limit(sql) and _tie_rows(a_rows) == _tie_rows(b_rows):
                    return Divergence("limit-tie", sql, a, b)
                return Divergence("rows", sql, a, b)
            # Same rows. They differ in order only if the order of rows that do not tie differs.
            if _tie_rows(a_rows) != _tie_rows(b_rows):
                return Divergence("row-order", sql, a, b)
    else:
        if _canon_rows(a_rows) != _canon_rows(b_rows):
            return Divergence("rows", sql, a, b)
    if check_columns and a_cols != b_cols:
        return Divergence("columns", sql, a, b)
    return None
