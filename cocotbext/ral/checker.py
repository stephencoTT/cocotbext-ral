"""Scoreboard for accumulating and reporting RAL prediction results."""

import logging
from typing import List

from .runtime_predictor import PredictionResult


class Checker:
    """Accumulates prediction results and provides summary reporting."""

    def __init__(self, logger_name: str = "ral", name: str = ""):
        self.log = logging.getLogger(f"{logger_name}.checker")
        self._name = name
        self._total_checks = 0
        self._passed_checks = 0
        self._failed_checks = 0
        self._errors: List[str] = []

    def check(self, result: PredictionResult) -> bool:
        """Record a prediction result.

        Args:
            result: PredictionResult from the predictor.

        Returns:
            True if the result passed, False otherwise.
        """
        self._total_checks += 1
        if result.passed:
            self._passed_checks += 1
            self.log.info(
                f"CHECK PASS: {result.register_name} @ 0x{result.address:08x}"
            )
        else:
            self._failed_checks += 1
            for msg in result.error_messages:
                self._errors.append(msg)
            self.log.error(
                f"CHECK FAIL: {result.register_name} @ 0x{result.address:08x}: "
                + "; ".join(result.error_messages)
            )
        return result.passed

    def has_errors(self) -> bool:
        return self._failed_checks > 0

    def report(self) -> str:
        """Summary string with totals."""
        # Avoid words like "fail"/"error" in the summary line — TTEM's regex
        # pass/fail checker scans log output and would flag them as test failures.
        prefix = f"RAL Checker Report [{self._name}]" if self._name else "RAL Checker Report"
        lines = [
            f"{prefix}: "
            f"{self._passed_checks} passed, {self._failed_checks} mismatches, "
            f"{self._total_checks} total"
        ]
        if self._errors:
            lines.append("Mismatches:")
            for err in self._errors:
                lines.append(f"  - {err}")
        return "\n".join(lines)

    def raise_on_errors(self):
        """Raise AssertionError if any checks failed."""
        if self.has_errors():
            raise AssertionError(
                f"RAL checker found {self._failed_checks} error(s):\n"
                + "\n".join(f"  - {e}" for e in self._errors)
            )
