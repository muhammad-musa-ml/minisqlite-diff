"""Command line: python -m msqdiff <command>"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

from . import corpus
from .check import check_findings
from .engines import Oracle
from .gen import make_case
from .harness import Case, Pair, op_for
from .model import SOFT
from .shrink import shrink, skeleton


def _ascii(s: str) -> str:
    return s.encode("ascii", "backslashreplace").decode("ascii")


def cmd_corpus(args: argparse.Namespace) -> int:
    cases = [Case(i, s, q, o) for (i, s, q, o) in corpus.all_cases()]
    if args.only:
        cases = [c for c in cases if args.only in c.id or args.only in c.sql]
    pair = Pair()
    found = []
    t0 = time.time()
    for c in cases:
        d = pair.run_case(c, check_columns=not args.no_columns)
        if d is not None:
            found.append((c, d))
    pair.close()
    print(f"sqlite {Oracle.version()} vs minisqlite | corpus cases: {len(cases)} | divergences: {len(found)} | {time.time() - t0:.1f}s")
    by_cat = collections.Counter(d.category for _, d in found)
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"id": c.id, "category": d.category, "setup": c.setup, "sql": d.sql, "sqlite": d.sqlite.brief(20), "minisqlite": d.mini.brief(20)}
            for c, d in found
        ]
        Path(args.out).write_text(json.dumps(rows, indent=1, ensure_ascii=True), encoding="ascii")
    if not args.quiet:
        wanted = set(args.show.split(",")) if args.show else None
        for c, d in found:
            if wanted and d.category not in wanted:
                continue
            print(f"--- {c.id}")
            if c.setup:
                print("    setup: " + "; ".join(c.setup))
            print(_ascii(d.line()))
    return 0


def cmd_fuzz(args: argparse.Namespace) -> int:
    pair = Pair()
    t0 = time.time()
    found: list[tuple[int, Case, str, bool]] = []  # seed, case, category, in_setup
    ignored = collections.Counter()
    seeds = range(args.seed, args.seed + args.count)
    for s in seeds:
        case = make_case(s)
        d = pair.run_case(case, check_columns=False)
        if d is None:
            continue
        if d.category in SOFT:
            ignored[d.category] += 1
            continue
        found.append((s, case, d.category, d.sql != case.sql))
    n_all = len(seeds)
    print(f"sqlite {Oracle.version()} vs minisqlite | fuzz seeds {seeds.start}..{seeds.stop - 1} ({n_all} cases) | behavioural divergences: {len(found)} | "
          f"not counted (wording, ties): {dict(ignored)} | {time.time() - t0:.1f}s")
    by_cat = collections.Counter(c for _, _, c, _ in found)
    for cat, n in by_cat.most_common():
        print(f"  {cat}: {n}")
    clusters: dict[str, dict] = {}
    for s, case, cat, in_setup in found[: args.shrink_limit]:
        small = shrink(pair, case, cat, in_setup, budget=args.budget)
        d = pair.run_case(small, check_columns=False)
        if d is None:
            continue
        key = f"{cat}|{skeleton(d.sql)}"
        entry = clusters.setdefault(key, {"category": cat, "seeds": [], "setup": small.setup, "sql": d.sql, "ordered": small.ordered,
                                          "sqlite": d.sqlite.brief(20), "minisqlite": d.mini.brief(20)})
        entry["seeds"].append(s)
    pair.close()
    print(f"clusters after shrinking {min(len(found), args.shrink_limit)} of {len(found)}: {len(clusters)}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(list(clusters.values()), indent=1, ensure_ascii=True), encoding="ascii")
    for e in sorted(clusters.values(), key=lambda e: (e["category"], e["sql"])):
        print(f"--- [{e['category']}] seeds={e['seeds'][:5]}{'...' if len(e['seeds']) > 5 else ''}")
        for st in e["setup"]:
            print("    " + _ascii(st))
        print("    > " + _ascii(e["sql"]))
        print("    sqlite: " + _ascii(e["sqlite"]))
        print("    mini:   " + _ascii(e["minisqlite"]))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    case = make_case(args.seed)
    pair = Pair()
    for st in case.setup:
        print(_ascii(st))
    print("> " + _ascii(case.sql))
    d = pair.run_case(case, check_columns=False)
    pair.close()
    print("agree" if d is None else _ascii(d.line()))
    return 0


def cmd_try(args: argparse.Namespace) -> int:
    """Run statements on both engines; print what each one answered to the last."""
    pair = Pair()
    pair.fresh()
    for st in args.statements[:-1]:
        d = pair.step(st, False, check_columns=False)
        if d is not None:
            print(_ascii(f"setup differs: {d.line()}"))
    sql = args.statements[-1]
    op = op_for(sql)
    a = pair.oracle.run(op, sql)
    b = pair.runner.run(op, sql)
    pair.close()
    print(_ascii(f"> {sql}"))
    print(_ascii(f"    sqlite {Oracle.version()}: {a.brief(50)}"))
    print(_ascii(f"    minisqlite: {b.brief(50)}"))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Replay findings/findings.json; exit 1 if any row is not what it should be."""
    spec = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    pair = Pair()
    rows = check_findings(pair, spec, args.patched)
    pair.close()
    target = "patched checkout" if args.patched else "pinned checkout"
    print(f"sqlite {Oracle.version()} vs minisqlite ({target}) | findings: {len(rows)}")
    bad = 0
    for r in rows:
        mark = "ok  " if r.ok else "FAIL"
        want = "diverges" if r.expected else "agrees"
        got = "diverges" if r.reproduces else "agrees"
        print(f"  {mark} {r.id} [{r.status}] expected {want}, got {got}")
        if not r.ok:
            bad += 1
            print(_ascii(f"       sqlite:     {r.sqlite.brief(5)}"))
            print(_ascii(f"       minisqlite: {r.mini.brief(5)}"))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        out = [
            {"id": r.id, "status": r.status, "reproduces": r.reproduces, "sqlite": r.sqlite.brief(20), "minisqlite": r.mini.brief(20),
             "sqlite_answer": r.sqlite.answer(20), "minisqlite_answer": r.mini.answer(20)}
            for r in rows
        ]
        Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=True), encoding="ascii")
    print(f"{len(rows) - bad} of {len(rows)} as expected")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="msqdiff")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("check", help="replay the recorded findings and compare with what each should do")
    k.add_argument("--findings", default="findings/findings.json")
    k.add_argument("--patched", action="store_true", help="the runner is the patched checkout: fixed findings must agree")
    k.add_argument("--out", default="", help="write the measured answers as JSON")
    k.set_defaults(fn=cmd_check)
    t = sub.add_parser("try", help="run statements on both engines and print both answers to the last one")
    t.add_argument("statements", nargs="+")
    t.set_defaults(fn=cmd_try)
    c = sub.add_parser("corpus", help="run the fixed corpus")
    c.add_argument("--only", default="")
    c.add_argument("--out", default="")
    c.add_argument("--quiet", action="store_true")
    c.add_argument("--show", default="", help="comma-separated categories to print")
    c.add_argument("--no-columns", action="store_true", help="skip column-name comparison")
    c.set_defaults(fn=cmd_corpus)
    f = sub.add_parser("fuzz", help="run seeded random cases")
    f.add_argument("--seed", type=int, default=0)
    f.add_argument("--count", type=int, default=1000)
    f.add_argument("--out", default="")
    f.add_argument("--shrink-limit", type=int, default=60)
    f.add_argument("--budget", type=int, default=500)
    f.set_defaults(fn=cmd_fuzz)
    r = sub.add_parser("replay", help="print and run one seed")
    r.add_argument("seed", type=int)
    r.set_defaults(fn=cmd_replay)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
