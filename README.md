# minisqlite-diff

This project runs the same SQL on [cursor/minisqlite](https://github.com/cursor/minisqlite) and on SQLite, and reports where the answers differ. It has a corpus of 956 hand-written statements, a seeded random generator, a shrinker that cuts a differing statement down to a few tokens, and a command that replays 28 recorded findings.

It is an independent project. It is not affiliated with Cursor, and Cursor has not reviewed it. It was written with Claude Code, an AI coding assistant, and every number below comes from running the commands in this repository.

## Why

Cursor's post [Agent swarms and the new model economics](https://cursor.com/blog/agent-swarm-model-economics) (Wilson Lin, 20 July 2026) describes a swarm that wrote SQLite in Rust from the SQLite documentation and was graded against sqllogictest. The code of the solo Opus 4.8 run is public as cursor/minisqlite. The post says its authors had not yet done a deeper manual analysis of that code, that the solo runs were graded only informally, and ends: "Take your own look, and tell us what you find."

[Issue #1](https://github.com/cursor/minisqlite/issues/1) on that repository points out that sqllogictest and SQLite's own TCL test suite are very different bars. minisqlite's README says that its in-repository tests take every expected value from the SQLite documentation, that they never run a `sqlite3` binary, and that differential testing against real SQLite happens outside the repository. This project is a differential test written from the outside: SQLite itself decides what the right answer is.

## Results

Measured on 2026-10-29 against cursor/minisqlite at commit `4a5c1341fdde38beaf438e0241c9f45833c4b870`, the head of `main`: three commits, all of 17 July 2026. The numbers come from [results/](results/).

| | SQLite 3.54.1 | SQLite 3.53.3 | SQLite 3.50.0 |
|---|---|---|---|
| Corpus statements (of 956) that differ in behaviour | 58 | 58 | 54 |
| Fuzz cases (seeds 0 to 29999) that differ in behaviour | 1,162 | 1,162 | 1,124 |
| &nbsp;&nbsp;of which the rows differ / one engine rejects what the other accepts | 696 / 466 | 696 / 466 | 700 / 424 |
| Fuzz cases that differ only in error text / error code (not counted) | 1,414 / 104 | 1,414 / 104 | 1,412 / 104 |
| minisqlite panics or hangs, corpus and fuzz together | 0 | 0 | 0 |

minisqlite's `sqlite_version()` reports 3.50.0, while a comment in its source cites a documentation change of 3.52.0, so the newer releases are measured as well as 3.50.0. Of the 58 corpus differences on 3.54.1, 56 appear against 3.53.3 too; the other two on each side are statements on which the two SQLite releases answer differently (`results/corpus-summary.txt`). The first 150 fuzz differences of each of the six shards were shrunk; 899 of those 900 cases still differed afterwards and fell into 789 distinct statement shapes (statements that differ only in their literals count once).

[findings/FINDINGS.md](findings/FINDINGS.md) lists 28 minimal repros. Replayed on 3.54.1 and 3.53.3, all 28 differ from minisqlite; on 3.50.0, 27 do; on the Debian SQLite 3.40.1, 22 do (`results/release-matrix.txt`). The ones that depend on the release are the float-to-text case F01, which agrees with minisqlite on 3.40.1 and 3.50.0 and differs on 3.53.3 and 3.54.1, and F04, F05, F06, F08 and O15, which agree on 3.40.1 only. Six that differ on all four releases:

| Statement | SQLite | minisqlite |
|---|---|---|
| `SELECT 9e999-9e999` | `NULL` | a NaN real |
| `SELECT datetime('2024-05-15 12:30:45 +05:30')` | `'2024-05-15 07:00:45'` | `NULL` |
| `SELECT json_set('{}','$.a.b',1)` | `'{"a":{"b":1}}'` | `'{}'` |
| `SELECT printf('%.0f',0.5)` | `'1'` | `'0'` |
| `SELECT * FROM t NATURAL JOIN t` (3 rows in `t`) | 3 rows | 9 rows |
| `SELECT count(*) FROM a, b WHERE x = y` (`x` is a TEXT column holding `'5'`, `y` a column without a type holding `5`) | `0` | `1` |

The last row contradicts a comment in minisqlite's source that warns against changing this behaviour; every SQLite release measured here returns 0.

Eleven of the findings (F01 to F11) are fixed on a local branch with regression tests, and with those fixes the fuzz run on 3.54.1 shows 566 differences instead of 1,162. That branch is not published because cursor/minisqlite has no licence file. The other 17 findings are open.

## Run it

Docker is needed for the two engines; the harness tests need only Python 3.10 or newer.

```
python scripts/fetch_minisqlite.py
docker build -t msqdiff:3541 .
docker run --rm msqdiff:3541 check
docker run --rm msqdiff:3541 corpus --no-columns --quiet
docker run --rm msqdiff:3541 fuzz --seed 0 --count 5000
docker run --rm msqdiff:3541 try "SELECT log10(1000)"
python -m unittest discover -s tests
```

`fetch_minisqlite.py` clones cursor/minisqlite at the pinned commit into `vendor/`. The image compiles SQLite from the official amalgamation; for the default release, 3.54.1, it compares the archive's SHA3-256 with the value given on sqlite.org before building. Another release is a build argument:

```
docker build -t msqdiff:3533 --build-arg SQLITE_NUM=3530300 --build-arg SQLITE_SHA3= .
docker build -t msqdiff:3500 --build-arg SQLITE_YEAR=2025 --build-arg SQLITE_NUM=3500000 --build-arg SQLITE_SHA3= .
```

`scripts/run_shards.ps1` runs the fuzzer as parallel containers from PowerShell, and `scripts/summarize_fuzz.py` and `scripts/compare_corpus.py` produce the summaries in `results/`.

## How a difference is decided

Each case is some setup statements followed by one statement. Both engines start from an empty in-memory database and run the same statements.

- Values are compared exactly. The integer 1 and the real 1.0 are different values, a real is compared by its IEEE-754 bit pattern (so `-0.0` differs from `0.0`), and text and blobs are compared byte for byte.
- Rows are compared as a multiset, except for a statement with a top-level `ORDER BY`, where the order counts. Rows that tie under the `ORDER BY` may come in either order: 0, 0.0 and -0.0 tie, and so do text values that differ only in ASCII case or trailing spaces, because a column may use `COLLATE NOCASE` or `COLLATE RTRIM`. A `LIMIT` whose cut falls inside a group of tied rows may return either member; such cases are counted separately and not reported (none occurred in the 30,000 seeds).
- A statement that one engine runs and the other rejects is a difference.
- Error text, error codes and result-column names are not counted. SQLite does not specify result-column names for expressions without an alias, and minisqlite's source says that what matters is success or failure, not the exact wording of an error.

## What these numbers do not show

- **The generator is not a sample of real programs.** Its literals come from short lists that include `1e15`, `1e16`, `9223372036854775807` and similar boundary values, and it picks column types and collations at random. A count of 1,162 means that many generated statements hit a difference, not how often a real program would.
- **The answer depends on the SQLite release.** Run against the SQLite 3.40.1 that the Debian base image ships, the same corpus shows 85 differences in behaviour instead of 58, and only 31 of them are also differences against 3.54.1; many of the rest are functions that 3.40.1 lacks, such as `unhex`, `concat` and `timediff` (`results/corpus-system-sqlite.txt` has the command and the comparison). That is why the image builds a pinned release, and why a difference is listed as a finding only when 3.54.1 and 3.53.3 agree with each other and disagree with minisqlite. The hash of the 3.54.1 archive was compared with the one on sqlite.org. For 3.53.3 and 3.50.0 the hash is printed in the build log but not compared, because sqlite.org lists only the latest release. The 3.50.0 and 3.40.1 columns of `findings/` and `results/` are recorded measurements; the continuous-integration workflow runs 3.54.1 and 3.53.3 only.
- **A difference is not always a defect.** Some findings are missing features (`jsonb()` does not exist). The source locations in `FINDINGS.md` were read for the findings that have one; the others are differences in behaviour that I did not trace.
- **Much is not covered.** Every database is in memory and every case uses one connection. File-format compatibility with `sqlite3`, journal and WAL recovery, concurrent access, performance, and the sqllogictest suite are not tested, and neither is any statement the corpus and the generator do not produce.
- **Only the pinned commit was tested.** Later commits may differ.

## Layout

| Path | Contents |
|---|---|
| `msqdiff/` | the harness: result model and comparison rules, the two engines, generator, shrinker, corpus, `check` |
| `runner/` | `msq-runner`, a small Rust driver that exposes `minisqlite::Connection` over standard input and output |
| `findings/` | `findings.json` (the repros), `measured_*.json` (what each engine answered), `FINDINGS.md` (generated by `scripts/make_findings_md.py`) |
| `results/` | the summaries behind the table above |
| `tests/` | tests of the harness, using stand-in engines with planted defects |
| `Dockerfile`, `.github/workflows/ci.yml` | the image and the checks run on every push |

## Licence

MIT, see [LICENSE](LICENSE). cursor/minisqlite carries no licence file, so its source is not included here and is fetched at build time.
