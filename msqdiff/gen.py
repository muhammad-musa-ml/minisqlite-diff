"""Seeded random SQL generator.

Every case is built from one integer seed, so a divergence is reproduced by
`python -m msqdiff fuzz --seed N --count 1`. The generator avoids statements whose
result SQLite leaves unspecified (a LIMIT without a total ORDER BY, a bare column
next to an aggregate, random(), the current time), so a mismatch is a difference
in specified behaviour, not noise.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .harness import Case

INTS = ["0", "1", "-1", "2", "3", "7", "10", "-10", "100", "255", "256", "65536", "2147483647", "2147483648",
        "4294967296", "9223372036854775807", "-9223372036854775808", "9223372036854775806"]
REALS = ["0.0", "0.5", "1.5", "2.5", "-2.5", "0.1", "3.14159", "1e10", "1e-10", "1e100", "-1e100", "123456789.125", "1e15", "1e16",
         "100.0", "-0.5", "2.675", "1.005", "4.35", "0.30000000000000004"]
TEXTS = ["''", "'a'", "'A'", "'b'", "'abc'", "'ABC'", "'hello'", "'Hello World'", "'  x  '", "'12'", "'12abc'", "'1.5'", "'1e3'",
         "'-7'", "'0x1F'", "'é'", "'a_b'", "'100%'", "'NULL'", "'zz'", "' 5'", "'5 '", "'+3'", "'.5'", "'1e'", "'-'"]
BLOBS = ["x''", "x'00'", "x'7f'", "x'616263'", "x'31'", "x'0102'"]  # all valid UTF-8 as text
PATTERNS = ["'a%'", "'%a'", "'%a%'", "'_'", "'__'", "'a_c'", "'%'", "''", "'A%'", "'%b%c'", "'1%'", "'[ab]%'", "'a*'", "'?b*'", "'*'"]
DATES = ["'2024-01-15'", "'2024-02-29'", "'2023-12-31 23:59:59'", "'2000-01-01 00:00:00'", "'2024-05-15 12:34:56.789'", "'1999-12-31'",
         "'0001-01-01'", "'9999-12-31'", "'2024-01-31'", "'12:34:56'", "2460000.5", "2451545", "'2024-W03'", "'bogus'", "NULL", "0", "1700000000"]
DATE_MODS = ["'+1 day'", "'-1 day'", "'+1 month'", "'-1 month'", "'+1 year'", "'start of month'", "'start of year'", "'start of day'",
             "'weekday 0'", "'weekday 3'", "'+36 hours'", "'-90 minutes'", "'+1.5 days'", "'unixepoch'", "'+10 days'", "'subsec'", "'ceiling'", "'floor'"]
JSONS = ["'{\"a\":1,\"b\":[1,2,3]}'", "'[1,2,3]'", "'{\"a\":{\"b\":2}}'", "'[]'", "'{}'", "'{\"a\":null}'", "'[1,[2,[3]]]'", "'{\"a\":\"x\",\"b\":1.5}'",
         "'\"str\"'", "'123'", "'{\"a\":[]}'", "'bad json'", "NULL", "'[1,2'", "'{\"k\":true}'"]
JSON_PATHS = ["'$'", "'$.a'", "'$.b'", "'$.a.b'", "'$[0]'", "'$[1]'", "'$[#-1]'", "'$.b[1]'", "'$.c'", "'$[5]'", "'$.a[0]'", "'$[0][1]'"]
AFFINITY_TYPES = ["INTEGER", "INT", "TEXT", "REAL", "NUMERIC", "BLOB", "", "VARCHAR(5)", "BOOLEAN", "DECIMAL(5,2)", "FLOAT", "CHAR(3)"]
COLLATIONS = ["", "", "", " COLLATE NOCASE", " COLLATE RTRIM", " COLLATE BINARY"]
CAST_TYPES = ["INTEGER", "REAL", "TEXT", "BLOB", "NUMERIC"]


@dataclass
class Table:
    name: str
    cols: list[str]  # includes the "id" primary key first
    types: dict[str, str]


class Gen:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.r = random.Random(seed)
        self.tables: list[Table] = []

    # ---- literals and leaves -------------------------------------------------
    def lit(self) -> str:
        r = self.r
        k = r.random()
        if k < 0.33:
            return r.choice(INTS)
        if k < 0.5:
            return r.choice(REALS)
        if k < 0.8:
            return r.choice(TEXTS)
        if k < 0.9:
            return r.choice(BLOBS)
        return "NULL"

    def col(self, tables: list[Table], qualify: bool) -> str:
        t = self.r.choice(tables)
        c = self.r.choice(t.cols[1:] or t.cols)
        return f"{t.name}.{c}" if qualify else c

    def leaf(self, tables: list[Table], qualify: bool) -> str:
        if tables and self.r.random() < 0.6:
            return self.col(tables, qualify)
        return self.lit()

    # ---- expressions ---------------------------------------------------------
    def expr(self, tables: list[Table], depth: int, qualify: bool = False) -> str:
        r = self.r
        if depth <= 0 or r.random() < 0.18:
            return self.leaf(tables, qualify)
        e = lambda: self.expr(tables, depth - 1, qualify)  # noqa: E731
        k = r.randrange(36)
        if k < 6:
            return f"({e()} {r.choice(['+', '-', '*', '/', '%'])} {e()})"
        if k < 8:
            return f"({e()} {r.choice(['&', '|', '<<', '>>'])} {e()})"
        if k < 12:
            return f"({e()} {r.choice(['=', '==', '!=', '<>', '<', '<=', '>', '>=', 'IS', 'IS NOT'])} {e()})"
        if k < 14:
            return f"({e()} {r.choice(['AND', 'OR'])} {e()})"
        if k == 14:
            return f"({e()} || {e()})"
        if k == 15:
            return f"({r.choice(['-', '+', '~', 'NOT '])}{e()})"
        if k == 16:
            return f"({e()} {r.choice(['IS NULL', 'IS NOT NULL'])})"
        if k == 17:
            return f"({e()} {r.choice(['', 'NOT '])}BETWEEN {e()} AND {e()})"
        if k == 18:
            items = ", ".join(e() for _ in range(r.randint(1, 3)))
            return f"({e()} {r.choice(['', 'NOT '])}IN ({items}))"
        if k == 19:
            return f"({e()} {r.choice(['', 'NOT '])}{r.choice(['LIKE', 'GLOB'])} {r.choice(PATTERNS)})"
        if k == 20:
            whens = " ".join(f"WHEN {e()} THEN {e()}" for _ in range(r.randint(1, 2)))
            base = f"{e()} " if r.random() < 0.3 else ""
            els = f" ELSE {e()}" if r.random() < 0.6 else ""
            return f"(CASE {base}{whens}{els} END)"
        if k == 21:
            return f"CAST({e()} AS {r.choice(CAST_TYPES)})"
        if k == 22:
            return f"{r.choice(['coalesce', 'ifnull', 'nullif'])}({e()}, {e()})"
        if k == 23:
            return f"iif({e()}, {e()}, {e()})"
        if k < 28:
            return self.function(tables, depth, qualify)
        if k == 28:
            return f"{r.choice(['max', 'min'])}({e()}, {e()}{', ' + e() if r.random() < 0.3 else ''})"
        if k == 29:
            return f"printf({r.choice(self.formats())}, {e()}{', ' + e() if r.random() < 0.2 else ''})"
        if k == 30:
            return self.date_expr()
        if k == 31:
            return self.json_expr(tables, depth, qualify)
        if k == 32 and tables:
            return f"({e()} COLLATE {r.choice(['NOCASE', 'RTRIM', 'BINARY'])})"
        if k == 33 and tables:
            t = r.choice(tables)
            return f"(SELECT {r.choice(['count(*)', 'max(' + r.choice(t.cols[1:] or t.cols) + ')', 'min(' + r.choice(t.cols[1:] or t.cols) + ')'])} FROM {t.name})"
        if k == 34:
            return f"({e()}, {e()}) {r.choice(['=', '<', '<>', 'IS'])} ({e()}, {e()})"
        return self.leaf(tables, qualify)

    def formats(self) -> list[str]:
        return ["'%d'", "'%5d|%-5d'", "'%s'", "'%.2f'", "'%5.1f'", "'%x'", "'%o'", "'%c'", "'%e'", "'%g'", "'%q'", "'%Q'", "'%05d'", "'%+d'",
                "'%10s|'", "'%-10s|'", "'%.3s'", "'%i'", "'%.0f'", "'%u'", "'%X'", "'%G'", "'%E'", "'%#x'", "'% d'"]

    def function(self, tables: list[Table], depth: int, qualify: bool) -> str:
        r = self.r
        e = lambda: self.expr(tables, depth - 1, qualify)  # noqa: E731
        one = ["abs", "length", "lower", "upper", "typeof", "hex", "quote", "trim", "ltrim", "rtrim", "sign", "unicode", "zeroblob", "octet_length",
               "round", "ceil", "floor", "trunc", "sqrt", "exp", "ln", "log10", "log2", "sin", "cos", "atan"]
        name = r.choice(one + ["substr", "substr", "replace", "instr", "round", "trim", "ltrim", "rtrim", "char", "unhex", "concat", "concat_ws"])
        if name in ("substr",):
            return f"substr({e()}, {e()}{', ' + e() if r.random() < 0.6 else ''})"
        if name == "replace":
            return f"replace({e()}, {e()}, {e()})"
        if name in ("instr",):
            return f"instr({e()}, {e()})"
        if name in ("round", "trim", "ltrim", "rtrim"):
            return f"{name}({e()}{', ' + e() if r.random() < 0.4 else ''})"
        if name == "char":
            return f"char({e()}{', ' + e() if r.random() < 0.3 else ''})"
        if name == "unhex":
            return f"unhex({e()})"
        if name in ("concat", "concat_ws"):
            return f"{name}({e()}, {e()}, {e()})"
        return f"{name}({e()})"

    def date_expr(self) -> str:
        r = self.r
        fn = r.choice(["date", "time", "datetime", "julianday", "unixepoch", "strftime"])
        mods = "".join(", " + r.choice(DATE_MODS) for _ in range(r.choice([0, 0, 1, 1, 2])))
        d = r.choice(DATES)
        if fn == "strftime":
            fmt = r.choice(["'%Y-%m-%d'", "'%H:%M:%S'", "'%j'", "'%w'", "'%W'", "'%s'", "'%f'", "'%J'", "'%u'", "'%V'", "'%G'", "'%e'", "'%p'", "'%I'", "'%%'", "'%Y-%m-%d %H:%M'"])
            return f"strftime({fmt}, {d}{mods})"
        return f"{fn}({d}{mods})"

    def json_expr(self, tables: list[Table], depth: int, qualify: bool) -> str:
        r = self.r
        j = r.choice(JSONS)
        k = r.randrange(11)
        if k == 0:
            return f"json_extract({j}, {r.choice(JSON_PATHS)})"
        if k == 1:
            return f"{j} {r.choice(['->', '->>'])} {r.choice(JSON_PATHS)}"
        if k == 2:
            return f"json_set({j}, {r.choice(JSON_PATHS)}, {self.lit()})"
        if k == 3:
            return f"json_insert({j}, {r.choice(JSON_PATHS)}, {self.lit()})"
        if k == 4:
            return f"json_replace({j}, {r.choice(JSON_PATHS)}, {self.lit()})"
        if k == 5:
            return f"json_remove({j}, {r.choice(JSON_PATHS)})"
        if k == 6:
            return f"json_type({j}{', ' + r.choice(JSON_PATHS) if r.random() < 0.6 else ''})"
        if k == 7:
            return f"json_array_length({j}{', ' + r.choice(JSON_PATHS) if r.random() < 0.4 else ''})"
        if k == 8:
            return f"json_valid({j})"
        if k == 9:
            return f"json_array({self.lit()}, {self.lit()})"
        return f"json_object('k', {self.lit()}, 'j', {self.lit()})"

    # ---- aggregates and windows ----------------------------------------------
    def aggregate(self, tables: list[Table], depth: int, qualify: bool) -> str:
        r = self.r
        e = self.expr(tables, depth, qualify)
        name = r.choice(["count", "sum", "total", "avg", "min", "max", "group_concat"])
        if name == "count" and r.random() < 0.3:
            return "count(*)"
        distinct = "DISTINCT " if name in ("count", "sum", "avg", "total", "group_concat") and r.random() < 0.2 else ""
        extra = ""
        if name == "group_concat" and not distinct and r.random() < 0.4:
            extra = f", {r.choice(TEXTS)}"
        filt = f" FILTER (WHERE {self.expr(tables, 1, qualify)})" if r.random() < 0.1 else ""
        return f"{name}({distinct}{e}{extra}){filt}"

    # ---- schema --------------------------------------------------------------
    def make_schema(self) -> list[str]:
        r = self.r
        out: list[str] = []
        for i in range(r.choice([1, 1, 2, 2, 3])):
            name = f"t{i + 1}"
            ncols = r.randint(2, 4)
            cols = ["id"] + [f"c{j + 1}" for j in range(ncols)]
            types: dict[str, str] = {"id": "INTEGER"}
            defs = ["id INTEGER PRIMARY KEY"]
            for c in cols[1:]:
                ty = r.choice(AFFINITY_TYPES)
                types[c] = ty
                d = f"{c} {ty}".rstrip()
                d += r.choice(COLLATIONS)
                x = r.random()
                if x < 0.08:
                    d += " NOT NULL DEFAULT " + r.choice(INTS + TEXTS[:4])
                elif x < 0.14:
                    d += " DEFAULT " + self.lit()
                elif x < 0.2:
                    d += " UNIQUE"
                defs.append(d)
            if r.random() < 0.1:
                defs.append(f"CHECK({cols[1]} IS NULL OR {cols[1]} <> {r.choice(INTS[:6])})")
            self.tables.append(Table(name, cols, types))
            out.append(f"CREATE TABLE {name}({', '.join(defs)})")
            for _ in range(r.choice([0, 0, 1, 1, 2])):
                c = r.choice(cols[1:])
                kind = r.random()
                if kind < 0.15:
                    out.append(f"CREATE INDEX i{len(out)} ON {name}({c} DESC)")
                elif kind < 0.3 and len(cols) > 2:
                    out.append(f"CREATE INDEX i{len(out)} ON {name}({c}, {r.choice(cols[1:])})")
                elif kind < 0.4:
                    out.append(f"CREATE INDEX i{len(out)} ON {name}({c}) WHERE {c} IS NOT NULL")
                elif kind < 0.5:
                    out.append(f"CREATE INDEX i{len(out)} ON {name}(({c} + 1))")
                else:
                    out.append(f"CREATE {'UNIQUE ' if r.random() < 0.15 else ''}INDEX i{len(out)} ON {name}({c})")
            for rid in range(1, r.randint(0, 9) + 1):
                vals = ", ".join(self.lit() for _ in cols[1:])
                out.append(f"INSERT OR IGNORE INTO {name}(id, {', '.join(cols[1:])}) VALUES({rid}, {vals})")
        return out

    def dml(self) -> str:
        r = self.r
        t = r.choice(self.tables)
        w = f" WHERE {self.expr([t], 2)}" if r.random() < 0.8 else ""
        k = r.random()
        if k < 0.4:
            c = r.choice(t.cols[1:])
            return f"UPDATE {r.choice(['', 'OR IGNORE ', 'OR REPLACE '])}{t.name} SET {c} = {self.expr([t], 2)}{w}"
        if k < 0.65:
            return f"DELETE FROM {t.name}{w}"
        vals = ", ".join(self.lit() for _ in t.cols[1:])
        rid = r.randint(1, 14)
        return f"INSERT {r.choice(['', 'OR REPLACE ', 'OR IGNORE '])}INTO {t.name}(id, {', '.join(t.cols[1:])}) VALUES({rid}, {vals})"

    # ---- queries -------------------------------------------------------------
    def select(self) -> tuple[str, bool]:
        """A SELECT and whether its row order is fully specified."""
        r = self.r
        k = r.random()
        if k < 0.12:
            return self.compound()
        n = r.choice([1, 1, 2, 3])
        t1 = r.choice(self.tables)
        joined = r.random() < 0.28 and len(self.tables) >= 1
        t2 = r.choice(self.tables) if joined else None
        if joined and t2 is t1:
            # a self join needs aliases; keep the generator simple and use two names
            t2 = None if len(self.tables) == 1 and r.random() < 0.5 else t2
        tabs = [t1] + ([t2] if t2 and t2 is not t1 else [])
        qualify = len(tabs) > 1
        src = t1.name
        if len(tabs) > 1:
            kind = r.choice(["JOIN", "LEFT JOIN", "CROSS JOIN", "JOIN", "NATURAL JOIN", "RIGHT JOIN", "FULL JOIN"])
            if kind == "NATURAL JOIN":
                src += f" NATURAL JOIN {t2.name}"
            elif kind == "CROSS JOIN":
                src += f" CROSS JOIN {t2.name}"
            else:
                src += f" {kind} {t2.name} ON {self.expr(tabs, 2, True)}"
        use_group = r.random() < 0.3
        use_agg = use_group or r.random() < 0.18
        where = f" WHERE {self.expr(tabs, 3, qualify)}" if r.random() < 0.65 else ""
        items: list[str] = []
        group = ""
        having = ""
        if use_group:
            g = [self.expr(tabs, 1, qualify) for _ in range(r.choice([1, 1, 2]))]
            group = " GROUP BY " + ", ".join(g)
            items = g[: n] + [self.aggregate(tabs, 2, qualify) for _ in range(max(1, n - len(g[:n])))]
            if r.random() < 0.3:
                having = f" HAVING {self.aggregate(tabs, 1, qualify)} {r.choice(['>', '<', '=', '<>'])} {self.lit()}"
        elif use_agg:
            items = [self.aggregate(tabs, 2, qualify) for _ in range(n)]
        else:
            items = [self.expr(tabs, 3, qualify) for _ in range(n)]
        win = False
        if not use_agg and r.random() < 0.12 and len(tabs) == 1:
            win = True
            fn = r.choice(["row_number()", "rank()", "dense_rank()", "ntile(3)", "percent_rank()", "cume_dist()", "lag(" + tabs[0].cols[1] + ")",
                           "lead(" + tabs[0].cols[1] + ", 2, 0)", "first_value(" + tabs[0].cols[1] + ")", "last_value(" + tabs[0].cols[1] + ")",
                           "sum(" + tabs[0].cols[1] + ")", "count(*)", "avg(" + tabs[0].cols[1] + ")", "min(" + tabs[0].cols[1] + ")",
                           "nth_value(" + tabs[0].cols[1] + ", 2)", "total(" + tabs[0].cols[1] + ")"])
            frame = r.choice(["", "", " ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING", " ROWS UNBOUNDED PRECEDING", " RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW",
                              " GROUPS BETWEEN 1 PRECEDING AND CURRENT ROW", " ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING EXCLUDE CURRENT ROW",
                              " ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING"])
            part = f"PARTITION BY {tabs[0].cols[1]} " if r.random() < 0.3 else ""
            order = f"ORDER BY {r.choice([tabs[0].cols[1] + ', id', 'id', tabs[0].cols[-1] + ' DESC, id'])}"
            items.append(f"{fn} OVER ({part}{order}{frame})")
        distinct = "DISTINCT " if r.random() < 0.12 and not win else ""
        sql = f"SELECT {distinct}{', '.join(items)} FROM {src}{where}{group}{having}"
        ordered = False
        if r.random() < 0.45 or win:
            cols = ", ".join(f"{i + 1}{r.choice(['', '', ' DESC', ' NULLS LAST', ' NULLS FIRST'])}" for i in range(len(items)))
            sql += f" ORDER BY {cols}"
            ordered = True
            if r.random() < 0.3:
                sql += f" LIMIT {r.choice(['0', '1', '2', '3', '5', '-1', '1.0'])}"
                if r.random() < 0.4:
                    sql += f" OFFSET {r.choice(['0', '1', '2', '10'])}"
        return sql, ordered

    def compound(self) -> tuple[str, bool]:
        r = self.r
        t = r.choice(self.tables)
        n = r.choice([1, 2])
        def one() -> str:
            items = ", ".join(self.expr([t], 2) for _ in range(n))
            where = f" WHERE {self.expr([t], 2)}" if r.random() < 0.5 else ""
            return f"SELECT {items} FROM {t.name}{where}"
        op = r.choice(["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])
        sql = f"{one()} {op} {one()}"
        ordered = False
        if r.random() < 0.6:
            sql += " ORDER BY " + ", ".join(str(i + 1) for i in range(n))
            ordered = True
        return sql, ordered

    # ---- one case ------------------------------------------------------------
    def case(self) -> Case:
        setup = self.make_schema()
        for _ in range(self.r.choice([0, 0, 1, 2, 3])):
            setup.append(self.dml())
        if self.r.random() < 0.12:
            setup.append("BEGIN")
            setup.append(self.dml())
            setup.append(self.r.choice(["ROLLBACK", "COMMIT"]))
        k = self.r.random()
        if k < 0.06:
            t = self.r.choice(self.tables)
            sql, ordered = f"SELECT * FROM {t.name} ORDER BY id", True
        elif k < 0.12:
            sql, ordered = f"SELECT {self.expr([], 4)}", False
        else:
            sql, ordered = self.select()
        return Case(f"fuzz-{self.seed}", setup, sql, ordered)


def make_case(seed: int) -> Case:
    return Gen(seed).case()
