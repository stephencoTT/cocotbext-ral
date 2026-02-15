"""Unit tests for Predictor with all SwAccess types."""

import unittest

from cocotbext.ral import RegisterField, Register, RegisterModel, SwAccess
from cocotbext.ral import Predictor, PredictionResult, FieldResult


class TestPredictor(unittest.TestCase):

    def _make_rw_model(self, reset_value=0):
        """Model with one 32-bit RW register at address 0x100."""
        model = RegisterModel(name="test")
        reg = Register("SCRATCH", address=0x100, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=reset_value, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, hierarchical_name="block.SCRATCH")
        return model

    def test_rw_write_then_read(self):
        model = self._make_rw_model()
        pred = Predictor(model)
        pred.predict_write(0x100, 0xDEADBEEF)
        result = pred.predict_read(0x100, 0xDEADBEEF)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.error_messages), 0)

    def test_rw_write_then_read_mismatch(self):
        model = self._make_rw_model()
        pred = Predictor(model)
        pred.predict_write(0x100, 0xDEADBEEF)
        result = pred.predict_read(0x100, 0xCAFEBABE)
        self.assertFalse(result.passed)
        self.assertGreater(len(result.error_messages), 0)

    def test_ro_field_ignored_on_write(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("ro_f", lsb=0, msb=31, reset_value=0x42, sw_access=SwAccess.RO),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        pred.predict_write(0x100, 0xFFFFFFFF)
        # RO field prediction unchanged
        self.assertEqual(reg.fields[0].predicted_value, 0x42)

    def test_ro_field_not_checked_on_read(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("ro_f", lsb=0, msb=31, reset_value=0x42, sw_access=SwAccess.RO),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        # Read any value — RO field is not checked
        result = pred.predict_read(0x100, 0x99999999)
        self.assertTrue(result.passed)

    def test_wo_field_updates_on_write(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("wo_f", lsb=0, msb=31, reset_value=0, sw_access=SwAccess.WO),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        pred.predict_write(0x100, 0xBEEF)
        self.assertEqual(reg.fields[0].predicted_value, 0xBEEF)

    def test_wo_field_not_checked_on_read(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("wo_f", lsb=0, msb=31, reset_value=0, sw_access=SwAccess.WO),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        pred.predict_write(0x100, 0xBEEF)
        # WO not checked on read — any value passes
        result = pred.predict_read(0x100, 0x12345678)
        self.assertTrue(result.passed)

    def test_woclr_write_clears_bits(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("status", lsb=0, msb=7, reset_value=0xFF, sw_access=SwAccess.WOCLR),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        # Write 0x0F: bits 0-3 written as 1 → clear those in predicted
        pred.predict_write(0x100, 0x0F)
        self.assertEqual(reg.fields[0].predicted_value, 0xF0)

    def test_woclr_checked_on_read(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("status", lsb=0, msb=7, reset_value=0xFF, sw_access=SwAccess.WOCLR),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        # No write — predicted is still 0xFF
        result = pred.predict_read(0x100, 0xFF)
        self.assertTrue(result.passed)
        result = pred.predict_read(0x100, 0x00)
        self.assertFalse(result.passed)

    def test_mixed_access_register(self):
        model = RegisterModel(name="test")
        reg = Register("MIXED", address=0x200, fields=[
            RegisterField("rw_f", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("ro_f", lsb=8, msb=15, reset_value=0xAA, sw_access=SwAccess.RO),
            RegisterField("wo_f", lsb=16, msb=23, reset_value=0, sw_access=SwAccess.WO),
        ])
        model.add_register(reg, hierarchical_name="block.MIXED")
        pred = Predictor(model)

        # Write all fields
        pred.predict_write(0x200, 0x00BBCC55)
        # RW updated, RO unchanged, WO updated
        self.assertEqual(reg.fields[0].predicted_value, 0x55)  # rw_f
        self.assertEqual(reg.fields[1].predicted_value, 0xAA)  # ro_f (unchanged)
        self.assertEqual(reg.fields[2].predicted_value, 0xBB)  # wo_f

        # Read: RW checked, RO not checked, WO not checked
        result = pred.predict_read(0x200, 0x00FF0055)
        self.assertTrue(result.passed)

    def test_unmapped_address_write(self):
        model = self._make_rw_model()
        pred = Predictor(model)
        # Should not crash
        pred.predict_write(0xDEAD, 0x12345678)

    def test_unmapped_address_read(self):
        model = self._make_rw_model()
        pred = Predictor(model)
        result = pred.predict_read(0xDEAD, 0x12345678)
        self.assertTrue(result.passed)
        self.assertEqual(result.register_name, "<unmapped>")

    def test_multiple_fields_partial_match(self):
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("f0", lsb=0, msb=15, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("f1", lsb=16, msb=31, reset_value=0, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        pred.predict_write(0x100, 0xAAAABBBB)
        # Read with f0 correct but f1 wrong
        result = pred.predict_read(0x100, 0xCCCCBBBB)
        self.assertFalse(result.passed)
        self.assertEqual(len(result.error_messages), 1)  # only f1 mismatches

    def test_field_result_details(self):
        model = self._make_rw_model()
        pred = Predictor(model)
        pred.predict_write(0x100, 0xABCD)
        result = pred.predict_read(0x100, 0xABCD)
        self.assertEqual(len(result.field_results), 1)
        fr = result.field_results[0]
        self.assertEqual(fr.field_name, "data")
        self.assertEqual(fr.expected, 0xABCD)
        self.assertEqual(fr.actual, 0xABCD)
        self.assertTrue(fr.matched)

    def test_check_enabled_disable_field(self):
        """Disabling check_enabled on a field skips it during predict_read."""
        model = self._make_rw_model()
        pred = Predictor(model)
        pred.predict_write(0x100, 0xAAAA)

        # Disable checking on the field
        reg = model.get_register(0x100)
        reg.fields[0].check_enabled = False

        # Read a mismatched value — should still pass because checking is disabled
        result = pred.predict_read(0x100, 0xBBBB)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.field_results), 0)

    def test_check_enabled_reenable_field(self):
        """Re-enabling check_enabled restores checking."""
        model = self._make_rw_model()
        pred = Predictor(model)
        pred.predict_write(0x100, 0xAAAA)

        reg = model.get_register(0x100)
        reg.fields[0].check_enabled = False
        result = pred.predict_read(0x100, 0xBBBB)
        self.assertTrue(result.passed)

        # Re-enable and check again — mismatch should be caught
        reg.fields[0].check_enabled = True
        result = pred.predict_read(0x100, 0xBBBB)
        self.assertFalse(result.passed)

    def test_check_enabled_mixed_fields(self):
        """Only disabled fields are skipped; enabled fields still checked."""
        model = RegisterModel(name="test")
        reg = Register("REG", address=0x100, fields=[
            RegisterField("f0", lsb=0, msb=15, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("f1", lsb=16, msb=31, reset_value=0, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, hierarchical_name="block.REG")
        pred = Predictor(model)
        pred.predict_write(0x100, 0xAAAABBBB)

        # Disable f1 only
        reg.fields[1].check_enabled = False

        # f0 correct, f1 wrong — should pass because f1 is disabled
        result = pred.predict_read(0x100, 0xCCCCBBBB)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.field_results), 1)  # only f0 checked


if __name__ == "__main__":
    unittest.main()
