"""Unit tests for RuntimeRAL construction and state-only helpers.

These tests avoid cocotb entirely by not attaching a master or invoking
any async bus methods.
"""

import unittest

from cocotbext.ral import (
    RegisterModel, Register, RegisterField, SwAccess, RuntimeRAL,
)


def _make_model() -> RegisterModel:
    model = RegisterModel("ip")
    ctrl = Register("CTRL", address=0x100, fields=[
        RegisterField("enable", lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RW),
        RegisterField("mode",   lsb=1, msb=3, reset_value=5, sw_access=SwAccess.RW),
    ])
    stat = Register("STAT", address=0x104, fields=[
        RegisterField("busy",  lsb=0, msb=0, reset_value=0, sw_access=SwAccess.RO),
    ])
    model.add_register(ctrl, "block.CTRL")
    model.add_register(stat, "block.STAT")
    return model


class TestRuntimeRALReset(unittest.TestCase):

    def test_reset_restores_every_mirror_to_reset_value(self):
        ral = RuntimeRAL("ip", _make_model())
        # Corrupt the mirror.
        ral.runtime_state.set_field_mirrored(0x100, "enable", 1)
        ral.runtime_state.set_field_mirrored(0x100, "mode",   7)
        # Sanity before.
        rs = ral.runtime_state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 1)
        self.assertEqual(rs.fields["mode"].mirrored,   7)

        ral.reset()

        rs = ral.runtime_state.get_register_state(0x100)
        self.assertEqual(rs.fields["enable"].mirrored, 0)
        self.assertEqual(rs.fields["mode"].mirrored,   5)
        self.assertFalse(rs.fields["enable"].dirty)

    def test_reset_is_idempotent(self):
        ral = RuntimeRAL("ip", _make_model())
        ral.reset()
        ral.reset()
        rs = ral.runtime_state.get_register_state(0x100)
        self.assertEqual(rs.fields["mode"].mirrored, 5)


class TestRuntimeRALCheckToggles(unittest.TestCase):

    def test_disable_check_all_then_enable_all(self):
        ral = RuntimeRAL("ip", _make_model())
        ral.disable_check_all()
        for reg in ral.model.all_registers():
            rs = ral.runtime_state.get_register_state(reg.address)
            for fs in rs.fields.values():
                self.assertFalse(fs.check_enabled)

        ral.enable_check_all()
        for reg in ral.model.all_registers():
            rs = ral.runtime_state.get_register_state(reg.address)
            for fs in rs.fields.values():
                self.assertTrue(fs.check_enabled)


class TestRuntimeRALBulkAttachRequired(unittest.TestCase):
    """write / read / write_pattern must raise if no master is attached.

    Search utilities on the model still work without a master, though,
    so tests that only use the register search APIs don't need a bus.
    """

    def test_write_without_master_raises(self):
        import asyncio
        ral = RuntimeRAL("ip", _make_model())
        with self.assertRaises(RuntimeError):
            asyncio.run(ral.write(0x100, 0x1))

    def test_search_works_without_master(self):
        ral = RuntimeRAL("ip", _make_model())
        regs = ral.model.find_registers(name="block.*")
        self.assertEqual(len(regs), 2)


if __name__ == "__main__":
    unittest.main()
