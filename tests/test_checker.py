"""Unit tests for Checker scoreboard accumulation and reporting."""

import unittest

from cocotbext.ral import PredictionResult, FieldResult, Checker


class TestChecker(unittest.TestCase):

    def _pass_result(self, name="REG", addr=0x100):
        return PredictionResult(register_name=name, address=addr, passed=True)

    def _fail_result(self, name="REG", addr=0x100, msgs=None):
        return PredictionResult(
            register_name=name,
            address=addr,
            passed=False,
            error_messages=msgs or ["mismatch: expected 0x1, got 0x2"],
        )

    def test_check_pass(self):
        chk = Checker()
        ok = chk.check(self._pass_result())
        self.assertTrue(ok)
        self.assertEqual(chk._total_checks, 1)
        self.assertEqual(chk._passed_checks, 1)
        self.assertEqual(chk._failed_checks, 0)

    def test_check_fail(self):
        chk = Checker()
        ok = chk.check(self._fail_result())
        self.assertFalse(ok)
        self.assertEqual(chk._failed_checks, 1)

    def test_mixed_checks(self):
        chk = Checker()
        chk.check(self._pass_result())
        chk.check(self._pass_result())
        chk.check(self._fail_result())
        chk.check(self._pass_result())
        self.assertEqual(chk._total_checks, 4)
        self.assertEqual(chk._passed_checks, 3)
        self.assertEqual(chk._failed_checks, 1)

    def test_has_errors(self):
        chk = Checker()
        self.assertFalse(chk.has_errors())
        chk.check(self._pass_result())
        self.assertFalse(chk.has_errors())
        chk.check(self._fail_result())
        self.assertTrue(chk.has_errors())

    def test_report_format(self):
        chk = Checker()
        chk.check(self._pass_result())
        chk.check(self._fail_result(msgs=["field X: expected 0xa, got 0xb"]))
        report = chk.report()
        self.assertIn("1 passed", report)
        self.assertIn("1 mismatches", report)
        self.assertIn("2 total", report)
        self.assertIn("field X", report)

    def test_report_no_trigger_words(self):
        """Report summary line must not contain 'fail' or 'error'."""
        chk = Checker()
        chk.check(self._pass_result())
        chk.check(self._fail_result())
        report = chk.report()
        # Check the summary line (first line) specifically
        summary_line = report.split("\n")[0].lower()
        self.assertNotIn("fail", summary_line)
        self.assertNotIn("error", summary_line)

    def test_raise_on_errors_passes(self):
        chk = Checker()
        chk.check(self._pass_result())
        # Should not raise
        chk.raise_on_errors()

    def test_raise_on_errors_raises(self):
        chk = Checker()
        chk.check(self._fail_result())
        with self.assertRaises(AssertionError) as ctx:
            chk.raise_on_errors()
        self.assertIn("1 error", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
