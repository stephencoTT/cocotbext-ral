"""Unit tests for RMW safety assessment."""

import unittest

from cocotbext.ral import Register, RegisterField, SwAccess
from cocotbext.ral.rmw_policy import assess_field_rmw, RmwAssessment


class TestRmwAssessment(unittest.TestCase):

    def test_all_rw_neighbors_is_safe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("data", lsb=8, msb=15, sw_access=SwAccess.RW),
            RegisterField("mask", lsb=16, msb=23, sw_access=SwAccess.RW),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertTrue(result.safe)
        self.assertEqual(len(result.reasons), 0)

    def test_ro_neighbor_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("status", lsb=8, msb=15, sw_access=SwAccess.RO),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertFalse(result.safe)
        self.assertTrue(any("status" in r for r in result.reasons))

    def test_w1c_neighbor_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("irq", lsb=8, msb=15, sw_access=SwAccess.W1C),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertFalse(result.safe)
        self.assertTrue(any("irq" in r for r in result.reasons))

    def test_wo_neighbor_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("cmd", lsb=8, msb=15, sw_access=SwAccess.WO),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertFalse(result.safe)

    def test_w1s_neighbor_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("set_bits", lsb=8, msb=15, sw_access=SwAccess.W1S),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertFalse(result.safe)

    def test_nonexistent_field_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
        ])
        result = assess_field_rmw(reg, "nonexistent")
        self.assertFalse(result.safe)
        self.assertTrue(any("not found" in r for r in result.reasons))

    def test_ro_target_is_unsafe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("status", lsb=0, msb=7, sw_access=SwAccess.RO),
        ])
        result = assess_field_rmw(reg, "status")
        self.assertFalse(result.safe)
        self.assertTrue(any("not writable" in r for r in result.reasons))

    def test_single_rw_field_is_safe(self):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("only", lsb=0, msb=31, sw_access=SwAccess.RW),
        ])
        result = assess_field_rmw(reg, "only")
        self.assertTrue(result.safe)

    def test_woclr_target_is_safe(self):
        """WOCLR (W1C) target with all-RW neighbors should be safe."""
        reg = Register("REG", address=0x0, fields=[
            RegisterField("irq_clear", lsb=0, msb=7, sw_access=SwAccess.WOCLR),
            RegisterField("data", lsb=8, msb=31, sw_access=SwAccess.RW),
        ])
        result = assess_field_rmw(reg, "irq_clear")
        self.assertTrue(result.safe)

    def test_multiple_unsafe_reasons(self):
        """Multiple non-RW neighbors produce multiple reasons."""
        reg = Register("REG", address=0x0, fields=[
            RegisterField("ctrl", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("status", lsb=8, msb=15, sw_access=SwAccess.RO),
            RegisterField("irq", lsb=16, msb=23, sw_access=SwAccess.W1C),
        ])
        result = assess_field_rmw(reg, "ctrl")
        self.assertFalse(result.safe)
        self.assertGreaterEqual(len(result.reasons), 2)


if __name__ == "__main__":
    unittest.main()
