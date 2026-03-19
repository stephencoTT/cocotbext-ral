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
