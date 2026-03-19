# Access policy tests

import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.runtime_predictor import RuntimePredictor


class TestAccessPolicies(unittest.TestCase):

    def test_w1c(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=3, reset_value=0xF, sw_access=SwAccess.W1C)
        ])
        model.add_register(reg, "REG")

        pred = RuntimePredictor(model)
        pred.predict_write(0x0, 0x3)
        state = pred.runtime_state.get_register_state(0x0)
        assert state.fields["f0"].mirrored == 0xC

    def test_w1s(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=3, reset_value=0x0, sw_access=SwAccess.W1S)
        ])
        model.add_register(reg, "REG")

        pred = RuntimePredictor(model)
        pred.predict_write(0x0, 0x3)
        state = pred.runtime_state.get_register_state(0x0)
        assert state.fields["f0"].mirrored == 0x3

    def test_rclr(self):
        model = RegisterModel("test")
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=3, reset_value=0xF, sw_access=SwAccess.RCLR)
        ])
        model.add_register(reg, "REG")

        pred = RuntimePredictor(model)
        pred.predict_read(0x0, 0xF)
        state = pred.runtime_state.get_register_state(0x0)
        assert state.fields["f0"].mirrored == 0
