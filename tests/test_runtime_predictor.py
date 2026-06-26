import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.experimental import RuntimePredictor


class TestRuntimePredictor(unittest.TestCase):

    def test_basic_rw(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RW)
        ])
        model.add_register(reg, "REG")

        pred = RuntimePredictor(model)

        pred.predict_write(0x0, 0xAA)
        result = pred.predict_read(0x0, 0xAA)

        assert result.passed

    def test_disable_check(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RW)
        ])
        model.add_register(reg, "REG")

        pred = RuntimePredictor(model)
        state = pred.runtime_state

        state.disable_check(0x0, "f0")

        pred.predict_write(0x0, 0xAA)
        result = pred.predict_read(0x0, 0xBB)

        assert result.passed


class TestApplyExternalRead(unittest.TestCase):
    """notify_external_read path: apply read side-effects without a bus read."""

    def _model(self):
        model = RegisterModel("test")
        model.add_register(Register("REG", address=0x0, fields=[
            RegisterField("cnt",  lsb=0,  msb=7,  reset_value=0, sw_access=SwAccess.RCLR),
            RegisterField("stk",  lsb=8,  msb=15, reset_value=0, sw_access=SwAccess.RSET),
            RegisterField("keep", lsb=16, msb=23, reset_value=0, sw_access=SwAccess.RW),
        ]), "REG")
        return model

    def test_applies_read_side_effects(self):
        pred = RuntimePredictor(self._model())
        st = pred.runtime_state
        st.set_field_mirrored(0x0, "cnt", 0xAB)
        st.set_field_mirrored(0x0, "stk", 0x00)
        st.set_field_mirrored(0x0, "keep", 0x5A)

        pred.apply_external_read(0x0)

        rs = st.get_register_state(0x0)
        self.assertEqual(rs.fields["cnt"].mirrored, 0x00)    # RCLR -> cleared
        self.assertEqual(rs.fields["stk"].mirrored, 0xFF)    # RSET -> all-1s
        self.assertEqual(rs.fields["keep"].mirrored, 0x5A)   # RW -> unchanged

    def test_unmapped_address_is_noop(self):
        pred = RuntimePredictor(self._model())
        pred.apply_external_read(0xDEAD)  # must not raise
