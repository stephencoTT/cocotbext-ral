"""Comprehensive tests for RuntimePredictor covering all access types and edge cases."""

import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.runtime_predictor import RuntimePredictor


class TestRuntimePredictorRW(unittest.TestCase):

    def _make_model(self, sw_access=SwAccess.RW, reset_value=0):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=reset_value, sw_access=sw_access),
        ])
        model.add_register(reg, "block.REG")
        return model

    def test_write_then_read_match(self):
        pred = RuntimePredictor(self._make_model())
        pred.predict_write(0x100, 0xDEADBEEF)
        result = pred.predict_read(0x100, 0xDEADBEEF)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.error_messages), 0)

    def test_write_then_read_mismatch(self):
        pred = RuntimePredictor(self._make_model())
        pred.predict_write(0x100, 0xDEADBEEF)
        result = pred.predict_read(0x100, 0xCAFEBABE)
        self.assertFalse(result.passed)
        self.assertGreater(len(result.error_messages), 0)
        self.assertIn("expected", result.error_messages[0])

    def test_read_at_reset_value(self):
        pred = RuntimePredictor(self._make_model(reset_value=0x42))
        result = pred.predict_read(0x100, 0x42)
        self.assertTrue(result.passed)

    def test_unmapped_write_ignored(self):
        pred = RuntimePredictor(self._make_model())
        # Should not raise
        pred.predict_write(0xDEAD, 0xFF)

    def test_unmapped_read_passes(self):
        pred = RuntimePredictor(self._make_model())
        result = pred.predict_read(0xDEAD, 0xFF)
        self.assertTrue(result.passed)
        self.assertEqual(result.register_name, "<unmapped>")


class TestRuntimePredictorRO(unittest.TestCase):

    def test_ro_write_ignored(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("status", lsb=0, msb=7, reset_value=0x42, sw_access=SwAccess.RO),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xFF)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["status"].mirrored, 0x42)

    def test_ro_not_checked_on_read(self):
        """RO fields are volatile by default, so not checked."""
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("status", lsb=0, msb=7, reset_value=0x42, sw_access=SwAccess.RO),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        result = pred.predict_read(0x100, 0x99)
        self.assertTrue(result.passed)

    def test_ro_non_volatile_checked_at_reset(self):
        """RO + volatile=False enables reset-value check on first read."""
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField(
                "id", lsb=0, msb=31, reset_value=0xDEADBEEF,
                sw_access=SwAccess.RO, volatile=False,
            ),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)

        result = pred.predict_read(0x100, 0xDEADBEEF)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.field_results), 1)
        self.assertTrue(result.field_results[0].matched)

    def test_ro_non_volatile_mismatch_caught(self):
        """RO + volatile=False catches a wrong reset value on read."""
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField(
                "id", lsb=0, msb=31, reset_value=0xDEADBEEF,
                sw_access=SwAccess.RO, volatile=False,
            ),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)

        result = pred.predict_read(0x100, 0x12345678)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.error_messages), 1)
        self.assertIn("expected 0xdeadbeef", result.error_messages[0])
        self.assertIn("got 0x12345678", result.error_messages[0])


class TestRuntimePredictorWO(unittest.TestCase):

    def test_wo_write_updates_state(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("cmd", lsb=0, msb=7, sw_access=SwAccess.WO),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xAB)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["cmd"].mirrored, 0xAB)

    def test_wo_not_checked_on_read(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("cmd", lsb=0, msb=7, sw_access=SwAccess.WO),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xAB)
        result = pred.predict_read(0x100, 0xFF)
        self.assertTrue(result.passed)


class TestRuntimePredictorW1C(unittest.TestCase):

    def test_w1c_clears_bits(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("irq", lsb=0, msb=7, reset_value=0xFF, sw_access=SwAccess.W1C),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0x0F)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["irq"].mirrored, 0xF0)

    def test_w1c_checked_on_read(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("irq", lsb=0, msb=7, reset_value=0xFF, sw_access=SwAccess.W1C),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        result = pred.predict_read(0x100, 0xFF)
        self.assertTrue(result.passed)
        result = pred.predict_read(0x100, 0x00)
        self.assertFalse(result.passed)


class TestRuntimePredictorW1S(unittest.TestCase):

    def test_w1s_sets_bits(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("flags", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.W1S),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0x0F)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["flags"].mirrored, 0x0F)

    def test_w1s_cumulative(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("flags", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.W1S),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0x03)
        pred.predict_write(0x100, 0x0C)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["flags"].mirrored, 0x0F)


class TestRuntimePredictorRCLR(unittest.TestCase):

    def test_rclr_clears_on_read(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("counter", lsb=0, msb=7, reset_value=0xAB, sw_access=SwAccess.RCLR),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        # First read: RCLR fields are volatile by default, so not checked
        pred.predict_read(0x100, 0xAB)
        state = pred.runtime_state.get_register_state(0x100)
        # After read, side effect clears value
        self.assertEqual(state.fields["counter"].mirrored, 0)

    def test_rclr_write_ignored(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("counter", lsb=0, msb=7, reset_value=0xAB, sw_access=SwAccess.RCLR),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xFF)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["counter"].mirrored, 0xAB)


class TestRuntimePredictorRSET(unittest.TestCase):

    def test_rset_sets_all_bits_on_read(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("sticky", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RSET),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        # RSET fields are volatile by default, so read passes regardless
        pred.predict_read(0x100, 0x00)
        state = pred.runtime_state.get_register_state(0x100)
        # After read, side effect sets all bits
        self.assertEqual(state.fields["sticky"].mirrored, 0xFF)

    def test_rset_write_ignored(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("sticky", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RSET),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xFF)
        state = pred.runtime_state.get_register_state(0x100)
        self.assertEqual(state.fields["sticky"].mirrored, 0)


class TestRuntimePredictorMixed(unittest.TestCase):

    def test_mixed_register(self):
        """Register with RW, RO, and W1C fields."""
        model = RegisterModel("test")
        reg = Register("MIXED", address=0x200, fields=[
            RegisterField("ctrl", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("status", lsb=8, msb=15, reset_value=0xAA, sw_access=SwAccess.RO),
            RegisterField("irq", lsb=16, msb=23, reset_value=0xFF, sw_access=SwAccess.W1C),
        ])
        model.add_register(reg, "block.MIXED")
        pred = RuntimePredictor(model)

        pred.predict_write(0x200, 0x00FF5542)
        state = pred.runtime_state.get_register_state(0x200)
        self.assertEqual(state.fields["ctrl"].mirrored, 0x42)
        self.assertEqual(state.fields["status"].mirrored, 0xAA)  # RO unchanged
        self.assertEqual(state.fields["irq"].mirrored, 0x00)  # W1C: 0xFF & ~0xFF = 0

    def test_disable_check_skips_field(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("data", lsb=0, msb=31, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.runtime_state.disable_check(0x100, "data")
        pred.predict_write(0x100, 0xAA)
        result = pred.predict_read(0x100, 0xBB)
        self.assertTrue(result.passed)

    def test_field_results_populated_on_check(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("f0", lsb=0, msb=15, sw_access=SwAccess.RW),
            RegisterField("f1", lsb=16, msb=31, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.REG")
        pred = RuntimePredictor(model)
        pred.predict_write(0x100, 0xAAAABBBB)
        result = pred.predict_read(0x100, 0xCCCCBBBB)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.field_results), 2)
        self.assertEqual(len(result.error_messages), 1)


if __name__ == "__main__":
    unittest.main()
