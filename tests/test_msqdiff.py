"""Tests for the harness itself. They need no Docker and no minisqlite build.

A differential harness is only worth trusting if each way of reporting a
divergence has been seen to fire, and the clean case has been seen to stay quiet.
The stand-in engine below wraps a second real SQLite connection and breaks it in
one chosen way, so each test is a planted defect the harness has to find.
"""

from __future__ import annotations

import unittest

from msqdiff.engines import Oracle
from msqdiff.gen import make_case
from msqdiff.harness import Case, Pair, op_for
from msqdiff.model import SOFT, Result, compare, v_blob, v_int, v_null, v_real, v_text
from msqdiff.check import check_findings
from msqdiff.shrink import order_by_clause, shrink, skeleton, tokens


class StandIn:
    """Same interface as Runner, backed by SQLite, with one planted defect."""

    def __init__(self, defect: str = "", trigger: str = "") -> None:
        self.defect = defect
        self.trigger = trigger.lower()
        self.inner = Oracle()
        self.closed = False

    def reset(self) -> None:
        self.inner.reset()

    def close(self) -> None:
        self.closed = True
        self.inner.close()

    def run(self, op: str, sql: str) -> Result:
        r = self.inner.run(op, sql)
        if not self.defect or self.trigger not in sql.lower():
            return r
        if self.defect == "wrong-value" and r.kind == "rows" and r.rows:
            r.rows = [[v_int(0)] * len(row) for row in r.rows]
        elif self.defect == "swallow-error" and r.kind == "err":
            return Result("ok")
        elif self.defect == "reject" and r.kind != "err":
            return Result("err", message="unsupported", code=1)
        elif self.defect == "panic":
            return Result("panic", message="index out of bounds")
        elif self.defect == "hang":
            return Result("hang", message="no reply")
        elif self.defect == "reverse" and r.kind == "rows":
            r.rows = list(reversed(r.rows))
        elif self.defect == "rename" and r.kind == "rows":
            r.cols = [c + "_x" for c in r.cols]
        elif self.defect == "reword" and r.kind == "err":
            r.message += " (reworded)"
        return r


def pair_with(defect: str = "", trigger: str = "") -> Pair:
    return Pair(runner=StandIn(defect, trigger))


class CompareRules(unittest.TestCase):
    def test_identical_results_agree(self) -> None:
        a = Result("rows", ["x"], [[v_int(1)], [v_int(2)]])
        b = Result("rows", ["x"], [[v_int(2)], [v_int(1)]])
        self.assertIsNone(compare("q", False, a, b))

    def test_row_order_matters_only_under_order_by(self) -> None:
        a = Result("rows", ["x"], [[v_int(1)], [v_int(2)]])
        b = Result("rows", ["x"], [[v_int(2)], [v_int(1)]])
        self.assertEqual(compare("q", True, a, b).category, "row-order")

    def test_rows_that_tie_under_order_by_may_come_in_either_order(self) -> None:
        # 0, 0.0 and -0.0 compare equal, so ORDER BY leaves their relative order open.
        a = Result("rows", ["x"], [[v_int(0)], [v_real(0.0)], [v_real(-0.0)]])
        b = Result("rows", ["x"], [[v_real(-0.0)], [v_int(0)], [v_real(0.0)]])
        self.assertIsNone(compare("q", True, a, b))
        # The same holds for text that only a NOCASE or RTRIM collation would tell apart.
        c = Result("rows", ["x"], [[v_text("a")], [v_text("A ")]])
        d = Result("rows", ["x"], [[v_text("A ")], [v_text("a")]])
        self.assertIsNone(compare("q", True, c, d))

    def test_a_tie_does_not_hide_a_real_order_difference(self) -> None:
        a = Result("rows", ["x"], [[v_int(0)], [v_real(0.0)], [v_int(1)]])
        b = Result("rows", ["x"], [[v_int(1)], [v_real(0.0)], [v_int(0)]])
        self.assertEqual(compare("q", True, a, b).category, "row-order")

    def test_integer_and_real_that_differ_are_not_a_tie(self) -> None:
        # 2**53 + 1 has no exact double, so it is a different number from 2**53 as a real.
        big = 2**53
        a = Result("rows", ["x"], [[v_int(big + 1)], [v_real(float(big))]])
        b = Result("rows", ["x"], [[v_real(float(big))], [v_int(big + 1)]])
        self.assertEqual(compare("q", True, a, b).category, "row-order")

    def test_text_integer_blob_and_null_are_never_tied_with_each_other(self) -> None:
        for first, second in (
            (v_text("1"), v_int(1)),
            (v_blob(b"1"), v_text("1")),
            (v_null(), v_int(0)),
            (v_null(), v_text("")),
            (v_null(), v_blob(b"")),
            (v_text("a"), v_text("b")),
            (v_text("a"), v_text("a b")),
            (v_blob(b"\x00"), v_blob(b"\x01")),
        ):
            a = Result("rows", ["x"], [[first], [second]])
            b = Result("rows", ["x"], [[second], [first]])
            self.assertEqual(compare("q", True, a, b).category, "row-order", (first, second))

    def test_integer_and_real_are_different_values(self) -> None:
        a = Result("rows", ["x"], [[v_int(1)]])
        b = Result("rows", ["x"], [[v_real(1.0)]])
        self.assertEqual(compare("q", False, a, b).category, "rows")

    def test_negative_zero_differs_from_zero(self) -> None:
        a = Result("rows", ["x"], [[v_real(0.0)]])
        b = Result("rows", ["x"], [[v_real(-0.0)]])
        self.assertEqual(compare("q", False, a, b).category, "rows")

    def test_text_versus_integer(self) -> None:
        a = Result("rows", ["x"], [[v_text("1")]])
        b = Result("rows", ["x"], [[v_int(1)]])
        self.assertEqual(compare("q", False, a, b).category, "rows")

    def test_accept_versus_reject(self) -> None:
        ok = Result("rows", ["x"], [[v_int(1)]])
        bad = Result("err", message="boom", code=1)
        self.assertEqual(compare("q", False, ok, bad).category, "accept-reject")
        self.assertEqual(compare("q", False, bad, ok).category, "accept-reject")

    def test_wording_only_differences_are_their_own_category(self) -> None:
        a = Result("err", message="no such table: t", code=1)
        b = Result("err", message="unknown table t", code=1)
        self.assertEqual(compare("q", False, a, b).category, "error-text")
        c = Result("err", message="no such table: t", code=19)
        self.assertEqual(compare("q", False, a, c).category, "error-code")

    def test_panic_and_hang_win_over_everything(self) -> None:
        a = Result("rows", ["x"], [[v_int(1)]])
        self.assertEqual(compare("q", False, a, Result("panic", message="x")).category, "panic")
        self.assertEqual(compare("q", False, a, Result("hang", message="x")).category, "hang")

    def test_a_limit_that_cuts_a_group_of_tied_rows_may_return_either_member(self) -> None:
        a = Result("rows", ["x"], [[v_int(0)]])
        b = Result("rows", ["x"], [[v_real(0.0)]])
        self.assertEqual(compare("SELECT x FROM t ORDER BY 1 LIMIT 1", True, a, b).category, "limit-tie")
        self.assertEqual(compare("select x from t order by 1 limit 1 offset 2", True, a, b).category, "limit-tie")
        self.assertIn("limit-tie", SOFT)

    def test_without_a_limit_the_same_two_answers_are_a_real_difference(self) -> None:
        a = Result("rows", ["x"], [[v_int(0)]])
        b = Result("rows", ["x"], [[v_real(0.0)]])
        self.assertEqual(compare("SELECT x FROM t ORDER BY 1", True, a, b).category, "rows")
        # the word inside a string literal is not a LIMIT
        self.assertEqual(compare("SELECT 'LIMIT' FROM t ORDER BY 1", True, a, b).category, "rows")

    def test_a_limit_does_not_hide_different_values(self) -> None:
        a = Result("rows", ["x"], [[v_int(0)]])
        b = Result("rows", ["x"], [[v_int(1)]])
        self.assertEqual(compare("SELECT x FROM t ORDER BY 1 LIMIT 1", True, a, b).category, "rows")
        c = Result("rows", ["x"], [[v_int(0)], [v_int(0)]])
        self.assertEqual(compare("SELECT x FROM t ORDER BY 1 LIMIT 2", True, a, c).category, "rows")

    def test_answer_leaves_out_column_names(self) -> None:
        r = Result("rows", ["a very long expression text"], [[v_int(1)], [v_text("x")]])
        self.assertEqual(r.answer(), "2 rows: (1); ('x')")
        self.assertNotIn("expression", r.answer())
        self.assertEqual(Result("err", message="boom", code=1).answer(), "error[1] boom")
        self.assertEqual(Result("ok").answer(), "ok")
        many = Result("rows", ["x"], [[v_int(i)] for i in range(8)])
        self.assertEqual(many.answer(3), "8 rows: (0); (1); (2) ... +5 rows")

    def test_ok_and_empty_rows_are_the_same(self) -> None:
        self.assertIsNone(compare("q", False, Result("ok"), Result("rows", [], [])))


class PlantedDefects(unittest.TestCase):
    """Each planted defect must be reported, in the right category."""

    SETUP = ["CREATE TABLE t(a, b)", "INSERT INTO t VALUES(1, 'x'), (2, 'y')"]

    def run_defect(self, defect: str, sql: str, ordered: bool = False, columns: bool = False):
        pair = pair_with(defect, "from t")
        try:
            return pair.run_case(Case("c", self.SETUP, sql, ordered), check_columns=columns)
        finally:
            pair.close()

    def test_clean_engine_reports_nothing(self) -> None:
        pair = pair_with()
        d = pair.run_case(Case("c", self.SETUP, "SELECT a, b FROM t WHERE a > 0"))
        pair.close()
        self.assertIsNone(d)

    def test_wrong_value(self) -> None:
        d = self.run_defect("wrong-value", "SELECT a, b FROM t")
        self.assertEqual(d.category, "rows")

    def test_swallowed_error(self) -> None:
        d = self.run_defect("swallow-error", "SELECT nosuch FROM t")
        self.assertEqual(d.category, "accept-reject")

    def test_spurious_rejection(self) -> None:
        d = self.run_defect("reject", "SELECT a FROM t")
        self.assertEqual(d.category, "accept-reject")

    def test_panic(self) -> None:
        self.assertEqual(self.run_defect("panic", "SELECT a FROM t").category, "panic")

    def test_hang(self) -> None:
        self.assertEqual(self.run_defect("hang", "SELECT a FROM t").category, "hang")

    def test_order_by_violation(self) -> None:
        d = self.run_defect("reverse", "SELECT a FROM t ORDER BY a", ordered=True)
        self.assertEqual(d.category, "row-order")

    def test_unordered_query_ignores_row_order(self) -> None:
        self.assertIsNone(self.run_defect("reverse", "SELECT a FROM t", ordered=False))

    def test_column_names_only_checked_when_asked(self) -> None:
        self.assertIsNone(self.run_defect("rename", "SELECT a FROM t", columns=False))
        self.assertEqual(self.run_defect("rename", "SELECT a FROM t", columns=True).category, "columns")

    def test_defect_in_setup_is_reported_against_the_setup_statement(self) -> None:
        pair = pair_with("reject", "insert into t")
        d = pair.run_case(Case("c", self.SETUP, "SELECT 1"))
        pair.close()
        self.assertEqual(d.category, "accept-reject")
        self.assertTrue(d.sql.startswith("INSERT"))


class FindingsCheck(unittest.TestCase):
    """`check` replays recorded findings; a planted defect decides who reproduces."""

    SPEC = [
        {"id": "F00", "status": "fixed", "setup": ["CREATE TABLE t(a)", "INSERT INTO t VALUES(1)"], "sql": "SELECT a FROM t"},
        {"id": "O00", "status": "open", "setup": ["CREATE TABLE t(a)", "INSERT INTO t VALUES(2)"], "sql": "SELECT a FROM t"},
        {"id": "E00", "status": "open", "setup": ["CREATE TABLE t(a)"], "sql": "SELECT nosuch FROM t"},
    ]

    def rows(self, defect: str, patched: bool):
        pair = pair_with(defect, "from t")
        try:
            return {r.id: r for r in check_findings(pair, self.SPEC, patched)}
        finally:
            pair.close()

    def test_pinned_checkout_must_reproduce_every_finding(self) -> None:
        r = self.rows("wrong-value", patched=False)
        self.assertTrue(r["F00"].reproduces and r["F00"].ok)
        self.assertTrue(r["O00"].reproduces and r["O00"].ok)

    def test_a_finding_that_no_longer_diverges_is_reported_as_not_ok(self) -> None:
        r = self.rows("", patched=False)
        self.assertFalse(r["F00"].reproduces)
        self.assertFalse(r["F00"].ok)
        self.assertFalse(r["O00"].ok)

    def test_patched_checkout_must_agree_on_fixed_findings_only(self) -> None:
        r = self.rows("", patched=True)
        self.assertTrue(r["F00"].ok)  # fixed, and it agrees
        self.assertFalse(r["O00"].ok)  # open, but it no longer diverges: a change to look at

    def test_a_fix_that_did_not_take_is_reported(self) -> None:
        r = self.rows("wrong-value", patched=True)
        self.assertTrue(r["F00"].reproduces)
        self.assertFalse(r["F00"].ok)
        self.assertTrue(r["O00"].ok)

    def test_a_difference_in_error_wording_alone_is_not_a_finding(self) -> None:
        r = self.rows("reword", patched=False)
        self.assertFalse(r["E00"].reproduces)
        self.assertFalse(r["E00"].ok)

    def test_a_rejection_that_one_engine_swallows_reproduces(self) -> None:
        r = self.rows("swallow-error", patched=False)
        self.assertTrue(r["E00"].reproduces and r["E00"].ok)

    def test_each_finding_starts_from_an_empty_database(self) -> None:
        # F00 and O00 both create t; the second would fail if F00's table were still there.
        r = self.rows("wrong-value", patched=False)
        self.assertEqual(r["O00"].sqlite.rows, [[v_int(2)]])


class Shrinker(unittest.TestCase):
    def test_reduces_to_the_statement_that_triggers_the_defect(self) -> None:
        pair = pair_with("wrong-value", "substr(")
        big = Case(
            "c",
            ["CREATE TABLE t(a, b)", "INSERT INTO t VALUES(1, 'hello')", "INSERT INTO t VALUES(2, 'world')", "CREATE INDEX i ON t(a)"],
            "SELECT a + 1, upper(b), substr(b, 2, 3), length(b) * 2 FROM t WHERE a > 0 AND b <> 'zz' ORDER BY 1",
            True,
        )
        d = pair.run_case(big)
        self.assertEqual(d.category, "rows")
        small = shrink(pair, big, "rows", False, budget=400)
        pair.close()
        self.assertIn("substr(", small.sql.lower())
        self.assertLess(len(small.sql), len(big.sql) // 2)
        self.assertLess(len(small.setup), len(big.setup))

    def test_never_returns_a_case_that_no_longer_diverges(self) -> None:
        pair = pair_with("wrong-value", "length(")
        big = Case("c", ["CREATE TABLE t(a)", "INSERT INTO t VALUES('abc')"], "SELECT length(a), upper(a) FROM t")
        small = shrink(pair, big, "rows", False, budget=200)
        d = pair.run_case(small)
        pair.close()
        self.assertIsNotNone(d)
        self.assertEqual(d.category, "rows")

    def test_a_row_order_case_keeps_its_order_by(self) -> None:
        # Without its ORDER BY the query has no defined order, so a difference in order
        # would no longer be a finding.
        pair = pair_with("reverse", "from t")
        big = Case("c", ["CREATE TABLE t(a)", "INSERT INTO t VALUES(1), (2), (3)"], "SELECT a, a + 1 FROM t ORDER BY 1, 2", True)
        d = pair.run_case(big)
        self.assertEqual(d.category, "row-order")
        small = shrink(pair, big, "row-order", False, budget=400)
        pair.close()
        self.assertEqual(order_by_clause(small.sql), "ORDER BY 1, 2")
        self.assertEqual(len(small.setup), 2)

    def test_a_row_order_case_keeps_every_sort_key(self) -> None:
        # Dropping one key would leave rows that tie on the rest in an open order.
        pair = pair_with("reverse", "from t")
        big = Case("c", ["CREATE TABLE t(a, b)", "INSERT INTO t VALUES(1, 1), (1, 2)"], "SELECT a, b FROM t ORDER BY 1, 2", True)
        small = shrink(pair, big, "row-order", False, budget=400)
        pair.close()
        self.assertEqual(order_by_clause(small.sql), "ORDER BY 1, 2")

    def test_order_by_clause_looks_only_at_the_top_level(self) -> None:
        self.assertEqual(order_by_clause("SELECT a FROM t ORDER  BY  a DESC  LIMIT 2"), "ORDER BY a DESC LIMIT 2")
        self.assertIsNone(order_by_clause("SELECT a FROM (SELECT a FROM t ORDER BY a)"))
        self.assertIsNone(order_by_clause("SELECT sum(a) OVER (ORDER BY id) FROM t"))
        self.assertIsNone(order_by_clause("SELECT 'ORDER BY a' FROM t"))
        self.assertEqual(
            order_by_clause("SELECT sum(a) OVER (ORDER BY id), a FROM t UNION ALL SELECT 1, 2 ORDER BY 1"),
            "ORDER BY 1",
        )

    def test_tokenizer_round_trips(self) -> None:
        sql = "SELECT 'it''s', x'00ff', 1.5e3, a->>'$.b' FROM t -- no comment handling needed"
        self.assertEqual("".join(tokens(sql)), sql)

    def test_skeleton_ignores_literal_values_only(self) -> None:
        self.assertEqual(skeleton("SELECT substr('abc', 2)"), skeleton("SELECT substr('xyz', 9)"))
        self.assertNotEqual(skeleton("SELECT substr('abc', 2)"), skeleton("SELECT instr('abc', 2)"))


class Generator(unittest.TestCase):
    def test_same_seed_same_case(self) -> None:
        a, b = make_case(123), make_case(123)
        self.assertEqual((a.setup, a.sql, a.ordered), (b.setup, b.sql, b.ordered))

    def test_different_seeds_differ(self) -> None:
        self.assertNotEqual(make_case(1).sql, make_case(2).sql)

    def test_most_generated_statements_are_valid_sqlite(self) -> None:
        ok = 0
        n = 300
        for seed in range(n):
            case = make_case(seed)
            con = Oracle()
            good = True
            for st in case.setup:
                r = con.run(op_for(st), st)
                if r.kind == "err" and "syntax" in r.message:
                    good = False
            r = con.run(op_for(case.sql), case.sql)
            if r.kind == "err" and "syntax" in r.message:
                good = False
            con.close()
            ok += good
        self.assertGreaterEqual(ok, int(n * 0.97), f"only {ok}/{n} generated cases were free of syntax errors")

    def test_limit_always_comes_with_a_total_order(self) -> None:
        for seed in range(400):
            case = make_case(seed)
            if " LIMIT " in case.sql and "OVER" not in case.sql:
                self.assertIn(" ORDER BY ", case.sql)
                self.assertTrue(case.ordered)


if __name__ == "__main__":
    unittest.main()
