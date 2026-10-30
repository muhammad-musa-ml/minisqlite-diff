# Findings

28 minimal repros against `cursor/minisqlite` at commit `4a5c1341fdde38beaf438e0241c9f45833c4b870`, each replayed
with `python -m msqdiff check` on SQLite 3.54.1 and SQLite 3.53.3. A row is listed only when both
SQLite releases give the same answer and minisqlite gives a different one; the two releases agree
on all 28 (see `measured_3541.json` and `measured_3533.json`).

SQLite changes between releases, and minisqlite's `sqlite_version()` reports 3.50.0 while a comment in its
source cites a documentation change of 3.52.0, so the same repros were also run on SQLite 3.50.0 and on
the SQLite 3.40.1 that the Debian base image ships. 27 of 28 differ on 3.50.0 and 22 of 28 on 3.40.1;
the table says which, and each finding below shows the answer of an older release when it is not the
answer of 3.54.1. The 3.50.0 and 3.40.1 columns are recorded measurements and are not rerun in CI.

- **fixed** (11): the difference is gone on a local fix branch, with regression tests. That branch is not published (the upstream repository has no licence).
- **open** (17): the difference is still there and nothing was changed for it.

What counts as a difference: the rows (values compared exactly, a real by its bit pattern), or one engine
accepting a statement the other rejects. Error wording, error codes and result-column names are not
findings: SQLite documents column names as unspecified, and minisqlite's own source says it does not
match error text. Error messages are shown below only to make a repro readable.

| id | status | kind | differs on 3.40.1 / 3.50.0 / 3.53.3 / 3.54.1 | what differs |
|---|---|---|---|---|
| F01 | fixed | wrong result | no / no / yes / yes | A real from 1e15 up to (not including) 1e17 renders in scientific notation as text |
| F02 | fixed | wrong result | yes / yes / yes / yes | Negative zero renders as '-0.0' in text |
| F03 | fixed | wrong result | yes / yes / yes / yes | Float arithmetic that produces NaN returns a REAL NaN instead of NULL |
| F04 | fixed | wrong result | no / yes / yes / yes | substr() truncates its position and length arguments to 32 bits |
| F05 | fixed | wrong result | no / yes / yes / yes | log10() is one ulp off for exact powers of ten |
| F06 | fixed | wrong result | no / yes / yes / yes | log2() is one ulp off for exact powers of two |
| F07 | fixed | wrong result | yes / yes / yes / yes | Date functions return a value outside Julian day 0 to 5373484.499999 instead of NULL |
| F08 | fixed | wrong result | no / yes / yes / yes | date('2023-02-29') returns '2023-02-29' instead of normalising to '2023-03-01' |
| F09 | fixed | wrong result | yes / yes / yes / yes | The unixepoch modifier is accepted on a string time-value |
| F10 | fixed | accepted by one engine, rejected by the other | yes / yes / yes / yes | A space between the time and the time zone makes the date NULL |
| F11 | fixed | wrong result | yes / yes / yes / yes | A TEXT column compared with a typeless column has TEXT affinity applied to the typeless one, so '5' = 5 is true |
| O01 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | REPLACE into a NOT NULL column that has a DEFAULT fails instead of using the default |
| O02 | open | wrong result | yes / yes / yes / yes | A table NATURAL JOINed with itself returns 9 rows, not 3 |
| O03 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | GROUP BY -1 is accepted (SQLite: term out of range) |
| O04 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | HAVING on a query with no aggregate and no GROUP BY is accepted (SQLite rejects it) |
| O05 | open | wrong result | yes / yes / yes / yes | json_set does not create the missing objects along a path |
| O06 | open | wrong result | yes / yes / yes / yes | json_set appends when the array index is past the end |
| O07 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | json_set() with no arguments is an error (SQLite returns NULL) |
| O08 | open | wrong result | yes / yes / yes / yes | printf rounds a tie to the even digit (printf('%.0f', 2.5) is '2'); SQLite rounds it up ('3') |
| O09 | open | wrong result | yes / yes / yes / yes | printf prints the exact binary expansion past the 16th significant digit (SQLite pads with zeros) |
| O10 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | INSERT without a rowid into a table whose largest rowid is 9223372036854775807 fails (SQLite accepts it) |
| O11 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | ALTER TABLE ADD COLUMN ... NOT NULL without a default fails on an empty table (SQLite allows it) |
| O12 | open | wrong result | yes / yes / yes / yes | PRAGMA table_info on a view returns no rows |
| O13 | open | wrong result | yes / yes / yes / yes | The data of F11 compared through IN (SELECT ..) gives 1; SQLite gives 0 (the F11 fix does not change it) |
| O14 | open | accepted by one engine, rejected by the other | yes / yes / yes / yes | A string literal after a select item is not accepted as its alias |
| O15 | open | feature missing | no / yes / yes / yes | jsonb() does not exist |
| O16 | open | wrong result | yes / yes / yes / yes | date('-0001-01-01') (a negative year) is NULL |
| O17 | open | wrong result | yes / yes / yes / yes | A date string with leading white space is accepted (SQLite: NULL) |

## F01 (fixed): A real from 1e15 up to (not including) 1e17 renders in scientific notation as text

```sql
SELECT CAST(1e15 AS TEXT);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('1000000000000000.0')`
- minisqlite at `4a5c134`: `1 rows: ('1.0e+15')`
- SQLite 3.50.0 answers differently: `1 rows: ('1.0e+15')` (the same as minisqlite)
- SQLite 3.40.1 answers differently: `1 rows: ('1.0e+15')` (the same as minisqlite)
- minisqlite with the local fix: `1 rows: ('1000000000000000.0')`
- Where in the source: crates/minisqlite-types/src/numeric.rs, real_to_text: fixed notation only while the decimal exponent is below 15

## F02 (fixed): Negative zero renders as '-0.0' in text

```sql
SELECT CAST(-0.0 AS TEXT);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('0.0')`
- minisqlite at `4a5c134`: `1 rows: ('-0.0')`
- minisqlite with the local fix: `1 rows: ('0.0')`
- Where in the source: crates/minisqlite-types/src/numeric.rs, real_to_text

## F03 (fixed): Float arithmetic that produces NaN returns a REAL NaN instead of NULL

```sql
SELECT 9e999-9e999;
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (NULL)`
- minisqlite at `4a5c134`: `1 rows: (nan(real))`
- minisqlite with the local fix: `1 rows: (NULL)`
- Where in the source: crates/minisqlite-expr/src/eval.rs, arith_op: the real branch returns Value::Real(x - y) unchecked

## F04 (fixed): substr() truncates its position and length arguments to 32 bits

```sql
SELECT substr('hello', 2, 4294967297);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('ello')`
- minisqlite at `4a5c134`: `1 rows: ('e')`
- SQLite 3.40.1 answers differently: `1 rows: ('e')` (the same as minisqlite)
- minisqlite with the local fix: `1 rows: ('ello')`
- Where in the source: crates/minisqlite-functions/src/scalar/string/mod.rs, substr_impl: `as i32`, with a comment asking for a check against real SQLite

## F05 (fixed): log10() is one ulp off for exact powers of ten

```sql
SELECT log10(1000);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (3.0(real))`
- minisqlite at `4a5c134`: `1 rows: (2.9999999999999996(real))`
- SQLite 3.40.1 answers differently: `1 rows: (2.9999999999999996(real))` (the same as minisqlite)
- minisqlite with the local fix: `1 rows: (3.0(real))`
- Where in the source: crates/minisqlite-functions/src/scalar/math.rs: ln(x) / LN_10 instead of log10(x)

## F06 (fixed): log2() is one ulp off for exact powers of two

```sql
SELECT log2(2147483648);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (31.0(real))`
- minisqlite at `4a5c134`: `1 rows: (31.000000000000004(real))`
- SQLite 3.40.1 answers differently: `1 rows: (31.000000000000004(real))` (the same as minisqlite)
- minisqlite with the local fix: `1 rows: (31.0(real))`
- Where in the source: crates/minisqlite-functions/src/scalar/math.rs: ln(x) / LN_2 instead of log2(x)

## F07 (fixed): Date functions return a value outside Julian day 0 to 5373484.499999 instead of NULL

```sql
SELECT date('9999-12-31', '+1 day');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (NULL)`
- minisqlite at `4a5c134`: `1 rows: ('10000-01-01')`
- minisqlite with the local fix: `1 rows: (NULL)`
- Where in the source: crates/minisqlite-functions/src/datetime/compute.rs: no range check on the computed instant

## F08 (fixed): date('2023-02-29') returns '2023-02-29' instead of normalising to '2023-03-01'

```sql
SELECT date('2023-02-29');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('2023-03-01')`
- minisqlite at `4a5c134`: `1 rows: ('2023-02-29')`
- SQLite 3.40.1 answers differently: `1 rows: ('2023-02-29')` (the same as minisqlite)
- minisqlite with the local fix: `1 rows: ('2023-03-01')`
- Where in the source: crates/minisqlite-functions/src/datetime/{value,parse,modifier}.rs: comments say SQLite returns an impossible day verbatim

## F09 (fixed): The unixepoch modifier is accepted on a string time-value

```sql
SELECT date('2024-05-15', 'unixepoch');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (NULL)`
- minisqlite at `4a5c134`: `1 rows: ('2024-05-15')`
- minisqlite with the local fix: `1 rows: (NULL)`
- Where in the source: crates/minisqlite-functions/src/datetime/modifier.rs, apply

## F10 (fixed): A space between the time and the time zone makes the date NULL

```sql
SELECT datetime('2024-05-15 12:30:45 +05:30');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('2024-05-15 07:00:45')`
- minisqlite at `4a5c134`: `1 rows: (NULL)`
- minisqlite with the local fix: `1 rows: ('2024-05-15 07:00:45')`
- Where in the source: crates/minisqlite-functions/src/datetime/parse.rs, parse_tz

## F11 (fixed): A TEXT column compared with a typeless column has TEXT affinity applied to the typeless one, so '5' = 5 is true

```sql
CREATE TABLE a(x TEXT);
CREATE TABLE b(y);
INSERT INTO a VALUES('5');
INSERT INTO b VALUES(5);
SELECT count(*) FROM a, b WHERE x = y;
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (0)`
- minisqlite at `4a5c134`: `1 rows: (1)`
- minisqlite with the local fix: `1 rows: (0)`
- Where in the source: crates/minisqlite-plan/src/bind/expr.rs, compare_class: BLOB affinity and no affinity are one class, pinned by a test and three comments

## O01 (open): REPLACE into a NOT NULL column that has a DEFAULT fails instead of using the default

```sql
CREATE TABLE t(id INTEGER PRIMARY KEY, c NOT NULL DEFAULT 5);
REPLACE INTO t(id, c) VALUES(1, NULL);
```

- SQLite 3.54.1 and 3.53.3: `ok`
- minisqlite at `4a5c134`: `error[19] NOT NULL constraint failed: t.c`
- Where in the source: crates/minisqlite-exec/src/ops/constraints.rs, enforce_not_null: a comment calls this a documented interim narrowing because the plan carries no parsed defaults

## O02 (open): A table NATURAL JOINed with itself returns 9 rows, not 3

```sql
CREATE TABLE t(a,b);
INSERT INTO t VALUES(1,2),(1,3),(2,5);
SELECT * FROM t NATURAL JOIN t;
```

- SQLite 3.54.1 and 3.53.3: `3 rows: (1, 2); (1, 3); (2, 5)`
- minisqlite at `4a5c134`: `9 rows: (1, 2); (1, 2); (1, 2); (1, 3); (1, 3); (1, 3); (2, 5); (2, 5); (2, 5)`
- Where in the source: crates/minisqlite-plan/src/compile/from.rs, build_using: both sides resolve to the exposed name t, so the condition is t.a = t.a

## O03 (open): GROUP BY -1 is accepted (SQLite: term out of range)

```sql
SELECT 1 GROUP BY -1;
```

- SQLite 3.54.1 and 3.53.3: `error[1] 1st GROUP BY term out of range - should be between 1 and 1`
- minisqlite at `4a5c134`: `1 rows: (1)`

## O04 (open): HAVING on a query with no aggregate and no GROUP BY is accepted (SQLite rejects it)

```sql
SELECT 10 HAVING 2;
```

- SQLite 3.54.1 and 3.53.3: `error[1] HAVING clause on a non-aggregate query`
- minisqlite at `4a5c134`: `1 rows: (10)`

## O05 (open): json_set does not create the missing objects along a path

```sql
SELECT json_set('{}','$.a.b',1);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('{"a":{"b":1}}')`
- minisqlite at `4a5c134`: `1 rows: ('{}')`

## O06 (open): json_set appends when the array index is past the end

```sql
SELECT json_set('[1]','$[5]',2);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('[1]')`
- minisqlite at `4a5c134`: `1 rows: ('[1,2]')`

## O07 (open): json_set() with no arguments is an error (SQLite returns NULL)

```sql
SELECT json_set();
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (NULL)`
- minisqlite at `4a5c134`: `error[1] wrong number of arguments to function json_set()`

## O08 (open): printf rounds a tie to the even digit (printf('%.0f', 2.5) is '2'); SQLite rounds it up ('3')

```sql
SELECT printf('%.0f',0.5);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('1')`
- minisqlite at `4a5c134`: `1 rows: ('0')`

## O09 (open): printf prints the exact binary expansion past the 16th significant digit (SQLite pads with zeros)

```sql
SELECT printf('%.20f',0.1);
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('0.10000000000000000000')`
- minisqlite at `4a5c134`: `1 rows: ('0.10000000000000000555')`

## O10 (open): INSERT without a rowid into a table whose largest rowid is 9223372036854775807 fails (SQLite accepts it)

```sql
CREATE TABLE t(a INTEGER PRIMARY KEY, b);
INSERT INTO t VALUES(9223372036854775807,'x');
INSERT INTO t(b) VALUES('y');
```

- SQLite 3.54.1 and 3.53.3: `ok`
- minisqlite at `4a5c134`: `error[1] rowid space exhausted (auto-increment past i64::MAX)`

## O11 (open): ALTER TABLE ADD COLUMN ... NOT NULL without a default fails on an empty table (SQLite allows it)

```sql
CREATE TABLE t(a,b);
ALTER TABLE t ADD COLUMN c NOT NULL;
```

- SQLite 3.54.1 and 3.53.3: `ok`
- minisqlite at `4a5c134`: `error[1] Cannot add a NOT NULL column with default value NULL`

## O12 (open): PRAGMA table_info on a view returns no rows

```sql
CREATE TABLE t(a,b);
CREATE VIEW v AS SELECT a AS x, b+1 FROM t;
PRAGMA table_info(v);
```

- SQLite 3.54.1 and 3.53.3: `2 rows: (0, 'x', 'BLOB', 0, NULL, 0); (1, 'b+1', '', 0, NULL, 0)`
- minisqlite at `4a5c134`: `0 rows: `
- SQLite 3.40.1 answers differently: `2 rows: (0, 'x', '', 0, NULL, 0); (1, 'b+1', '', 0, NULL, 0)` (different from minisqlite)

## O13 (open): The data of F11 compared through IN (SELECT ..) gives 1; SQLite gives 0 (the F11 fix does not change it)

```sql
CREATE TABLE a(x TEXT);
CREATE TABLE b(y);
INSERT INTO a VALUES('5');
INSERT INTO b VALUES(5);
SELECT x IN (SELECT y FROM b) FROM a;
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (0)`
- minisqlite at `4a5c134`: `1 rows: (1)`

## O14 (open): A string literal after a select item is not accepted as its alias

```sql
SELECT 100 'a';
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (100)`
- minisqlite at `4a5c134`: `error[1] expected ';' or end of input after statement, near ''a'' (byte offset 11)`

## O15 (open): jsonb() does not exist

```sql
SELECT typeof(jsonb('{}'));
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('blob')`
- minisqlite at `4a5c134`: `error[1] no such function: jsonb`
- SQLite 3.40.1 answers differently: `error[1] no such function: jsonb` (the same as minisqlite)

## O16 (open): date('-0001-01-01') (a negative year) is NULL

```sql
SELECT date('-0001-01-01');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: ('-0001-01-01')`
- minisqlite at `4a5c134`: `1 rows: (NULL)`

## O17 (open): A date string with leading white space is accepted (SQLite: NULL)

```sql
SELECT date(' 2024-05-15');
```

- SQLite 3.54.1 and 3.53.3: `1 rows: (NULL)`
- minisqlite at `4a5c134`: `1 rows: ('2024-05-15')`

