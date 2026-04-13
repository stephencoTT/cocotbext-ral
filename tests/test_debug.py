"""Unit tests for debug helpers (dump_state, diff_state)."""

import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.state import RuntimeState
from cocotbext.ral.debug import dump_state, diff_state


class TestDumpState(unittest.TestCase):

    def _make_state(self):
        model = RegisterModel("test")
        reg = Register("CTRL", address=0x100, fields=[
            RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("mode", lsb=1, msb=3, reset_value=0x5, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.CTRL")
        return RuntimeState(model)

    def test_dump_includes_address(self):
        state = self._make_state()
        output = dump_state(state)
        self.assertIn("0x00000100", output)

    def test_dump_includes_field_names(self):
        state = self._make_state()
        output = dump_state(state)
        self.assertIn("enable", output)
        self.assertIn("mode", output)

    def test_dump_includes_mirrored_values(self):
        state = self._make_state()
        output = dump_state(state)
        self.assertIn("mirrored=", output)
        self.assertIn("desired=", output)
        self.assertIn("check=", output)

    def test_dump_reflects_state_changes(self):
        state = self._make_state()
        state.set_field_mirrored(0x100, "enable", 1)
        output = dump_state(state)
        self.assertIn("mirrored=0x1", output)

    def test_dump_empty_model(self):
        model = RegisterModel("empty")
        state = RuntimeState(model)
        output = dump_state(state)
        self.assertEqual(output, "")


class TestDiffState(unittest.TestCase):

    def _make_state(self):
        model = RegisterModel("test")
        reg = Register("CTRL", address=0x100, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=0xAB, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.CTRL")
        return RuntimeState(model)

    def test_diff_shows_expected_and_actual(self):
        state = self._make_state()
        output = diff_state(state, 0xFF, 0x100)
        self.assertIn("expected=0xab", output)
        self.assertIn("actual=0xff", output)

    def test_diff_unmapped_address(self):
        state = self._make_state()
        output = diff_state(state, 0xFF, 0xDEAD)
        self.assertEqual(output, "<no state>")

    def test_diff_includes_field_name(self):
        state = self._make_state()
        output = diff_state(state, 0x0, 0x100)
        self.assertIn("data", output)


if __name__ == "__main__":
    unittest.main()
