"""Unit tests for RuntimeState, RegisterState, and FieldState."""

import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.state import RuntimeState, RegisterState, FieldState


class TestFieldState(unittest.TestCase):

    def test_default_values(self):
        fs = FieldState(mirrored=0xAB, desired=0xAB)
        self.assertEqual(fs.mirrored, 0xAB)
        self.assertEqual(fs.desired, 0xAB)
        self.assertTrue(fs.check_enabled)
        self.assertFalse(fs.dirty)

    def test_reset(self):
        fs = FieldState(mirrored=0xFF, desired=0xEE, check_enabled=False, dirty=True)
        fs.reset(0x42)
        self.assertEqual(fs.mirrored, 0x42)
        self.assertEqual(fs.desired, 0x42)
        self.assertFalse(fs.dirty)


class TestRegisterState(unittest.TestCase):

    def _make_reg_state(self):
        fields = {
            "low": FieldState(mirrored=0x11, desired=0x11),
            "high": FieldState(mirrored=0x22, desired=0x22),
        }
        rs = RegisterState(fields=fields)
        specs = {
            "low": RegisterField("low", lsb=0, msb=7, reset_value=0x11),
            "high": RegisterField("high", lsb=8, msb=15, reset_value=0x22),
        }
        rs.attach_specs(specs)
        return rs

    def test_predicted_value(self):
        rs = self._make_reg_state()
        self.assertEqual(rs.predicted_value, 0x2211)

    def test_reset(self):
        rs = self._make_reg_state()
        rs.fields["low"].mirrored = 0xFF
        rs.fields["high"].mirrored = 0xFF
        rs.reset()
        self.assertEqual(rs.fields["low"].mirrored, 0x11)
        self.assertEqual(rs.fields["high"].mirrored, 0x22)


class TestRuntimeState(unittest.TestCase):

    def _make_model(self):
        model = RegisterModel("test")
        reg = Register("CTRL", address=0x100, fields=[
            RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("mode", lsb=1, msb=3, reset_value=5, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.CTRL")
        return model

    def test_get_register_state_by_address(self):
        state = RuntimeState(self._make_model())
        rs = state.get_register_state(0x100)
        self.assertIsNotNone(rs)
        self.assertIn("enable", rs.fields)
        self.assertIn("mode", rs.fields)

    def test_get_register_state_by_name(self):
        state = RuntimeState(self._make_model())
        rs = state.get_register_state("CTRL")
        self.assertIsNotNone(rs)

    def test_get_register_state_unknown(self):
        state = RuntimeState(self._make_model())
        self.assertIsNone(state.get_register_state(0xDEAD))

    def test_initial_state_matches_reset(self):
        state = RuntimeState(self._make_model())
        rs = state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 0)
        self.assertEqual(rs.fields["mode"].mirrored, 5)

    def test_set_field_mirrored(self):
        state = RuntimeState(self._make_model())
        state.set_field_mirrored(0x100, "enable", 1)
        rs = state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 1)
        self.assertEqual(rs.fields["enable"].desired, 1)

    def test_set_field_mirrored_masks_value(self):
        state = RuntimeState(self._make_model())
        # "enable" is 1 bit wide, writing 0xFF should mask to 1
        state.set_field_mirrored(0x100, "enable", 0xFF)
        rs = state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 1)

    def test_set_field_mirrored_unknown_register(self):
        state = RuntimeState(self._make_model())
        with self.assertRaises(KeyError):
            state.set_field_mirrored(0xDEAD, "enable", 1)

    def test_set_field_mirrored_unknown_field(self):
        state = RuntimeState(self._make_model())
        with self.assertRaises(KeyError):
            state.set_field_mirrored(0x100, "nonexistent", 1)

    def test_disable_check_all_fields(self):
        state = RuntimeState(self._make_model())
        state.disable_check(0x100)
        rs = state.get_register_state(0x100)
        for fs in rs.fields.values():
            self.assertFalse(fs.check_enabled)

    def test_disable_check_single_field(self):
        state = RuntimeState(self._make_model())
        state.disable_check(0x100, "enable")
        rs = state.get_register_state(0x100)
        self.assertFalse(rs.fields["enable"].check_enabled)
        self.assertTrue(rs.fields["mode"].check_enabled)

    def test_enable_check(self):
        state = RuntimeState(self._make_model())
        state.disable_check(0x100)
        state.enable_check(0x100)
        rs = state.get_register_state(0x100)
        for fs in rs.fields.values():
            self.assertTrue(fs.check_enabled)

    def test_enable_check_single_field(self):
        state = RuntimeState(self._make_model())
        state.disable_check(0x100)
        state.enable_check(0x100, "mode")
        rs = state.get_register_state(0x100)
        self.assertFalse(rs.fields["enable"].check_enabled)
        self.assertTrue(rs.fields["mode"].check_enabled)

    def test_disable_check_unknown_register(self):
        state = RuntimeState(self._make_model())
        with self.assertRaises(KeyError):
            state.disable_check(0xDEAD)

    def test_disable_check_unknown_field(self):
        state = RuntimeState(self._make_model())
        with self.assertRaises(KeyError):
            state.disable_check(0x100, "nonexistent")

    def test_reset(self):
        state = RuntimeState(self._make_model())
        state.set_field_mirrored(0x100, "enable", 1)
        state.set_field_mirrored(0x100, "mode", 7)
        state.reset()
        rs = state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 0)
        self.assertEqual(rs.fields["mode"].mirrored, 5)

    def test_sync_from_legacy_model(self):
        model = self._make_model()
        state = RuntimeState(model)
        # Modify legacy model directly
        reg = model.get_register(0x100)
        reg.fields[0].predicted_value = 1  # enable
        reg.fields[0].check_enabled = False
        state.sync_from_legacy_model()
        rs = state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 1)
        self.assertFalse(rs.fields["enable"].check_enabled)

    def test_sync_to_legacy_model(self):
        model = self._make_model()
        state = RuntimeState(model)
        state.set_field_mirrored(0x100, "enable", 1)
        state.disable_check(0x100, "mode")
        state.sync_to_legacy_model()
        reg = model.get_register(0x100)
        self.assertEqual(reg.fields[0].predicted_value, 1)
        self.assertFalse(reg.fields[1].check_enabled)


if __name__ == "__main__":
    unittest.main()
