"""Unit tests for RegisterField, Register, RegisterBlock, RegisterModel, and SwAccess."""

import unittest

from cocotbext.ral import RegisterField, Register, RegisterBlock, RegisterModel, SwAccess


class TestRegisterField(unittest.TestCase):

    def test_field_construction(self):
        f = RegisterField("data", lsb=8, msb=15, reset_value=0xAB, sw_access=SwAccess.RW)
        self.assertEqual(f.name, "data")
        self.assertEqual(f.lsb, 8)
        self.assertEqual(f.msb, 15)
        self.assertEqual(f.width, 8)
        self.assertEqual(f.mask, 0xFF)
        self.assertEqual(f.reset_value, 0xAB)

    def test_field_sw_access_properties(self):
        cases = [
            (SwAccess.RW,    True,  True,  False),
            (SwAccess.RO,    False, False, True),
            (SwAccess.WO,    False, True,  False),
            (SwAccess.WOCLR, True,  True,  False),
        ]
        for access, checkable, writable, volatile in cases:
            with self.subTest(access=access):
                f = RegisterField("f", lsb=0, msb=0, sw_access=access)
                self.assertEqual(f.is_checkable_on_read, checkable)
                self.assertEqual(f.is_writable, writable)
                self.assertEqual(f.is_volatile, volatile)

    def test_field_mask_computation(self):
        self.assertEqual(RegisterField("b0", 0, 0).mask, 1)
        self.assertEqual(RegisterField("byte", 0, 7).mask, 0xFF)
        self.assertEqual(RegisterField("word", 0, 31).mask, 0xFFFFFFFF)


class TestRegister(unittest.TestCase):

    def _make_register(self):
        """Create a register with two RW fields: low[7:0]=0x11, high[15:8]=0x22."""
        fields = [
            RegisterField("low", lsb=0, msb=7, reset_value=0x11),
            RegisterField("high", lsb=8, msb=15, reset_value=0x22),
        ]
        return Register("SCRATCH", address=0x1000, size_bits=32, fields=fields)

    def test_register_reset_value(self):
        reg = self._make_register()
        self.assertEqual(reg.reset_value, 0x2211)

    def test_register_get_field(self):
        reg = self._make_register()
        self.assertIsNotNone(reg.get_field("low"))
        self.assertEqual(reg.get_field("low").name, "low")
        self.assertIsNone(reg.get_field("nonexistent"))

    def test_register_writable_mask(self):
        fields = [
            RegisterField("rw", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("ro", lsb=8, msb=15, sw_access=SwAccess.RO),
        ]
        reg = Register("REG", address=0, fields=fields)
        self.assertEqual(reg.get_writable_mask(), 0xFF)

    def test_register_checkable_mask(self):
        fields = [
            RegisterField("rw", lsb=0, msb=7, sw_access=SwAccess.RW),
            RegisterField("wo", lsb=8, msb=15, sw_access=SwAccess.WO),
            RegisterField("woclr", lsb=16, msb=23, sw_access=SwAccess.WOCLR),
        ]
        reg = Register("REG", address=0, fields=fields)
        # RW + WOCLR are checkable, WO is not
        self.assertEqual(reg.get_checkable_mask(), 0xFF00FF)

    def test_register_has_backdoor(self):
        reg = self._make_register()
        self.assertFalse(reg.has_backdoor)
        reg.hdl_path = "tb.dut.reg"
        self.assertTrue(reg.has_backdoor)

    def test_register_has_backdoor_via_field(self):
        reg = self._make_register()
        self.assertFalse(reg.has_backdoor)
        reg.fields[0].hdl_path = "tb.dut.reg.low"
        self.assertTrue(reg.has_backdoor)


class TestRegisterBlock(unittest.TestCase):

    def test_block_add_register(self):
        block = RegisterBlock("smu", base_address=0x1000)
        reg = Register("SCRATCH", address=0x1000, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=0),
        ])
        block.add_register(reg)
        self.assertIn(0x1000, block.registers)
        self.assertIs(block.registers[0x1000], reg)


class TestRegisterModel(unittest.TestCase):

    def _make_model(self):
        model = RegisterModel(name="test_model")
        r0 = Register("SCRATCH_0", address=0x100, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=0),
        ])
        r1 = Register("SCRATCH_1", address=0x104, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=0),
        ])
        model.add_register(r0, hierarchical_name="smu.noc2axi.SCRATCH_0")
        model.add_register(r1, hierarchical_name="smu.noc2axi.SCRATCH_1")
        return model

    def test_model_add_and_lookup_by_address(self):
        model = self._make_model()
        reg = model.get_register(0x100)
        self.assertIsNotNone(reg)
        self.assertEqual(reg.name, "SCRATCH_0")

    def test_model_lookup_by_hierarchical_name(self):
        model = self._make_model()
        reg = model.get_register("smu.noc2axi.SCRATCH_0")
        self.assertIsNotNone(reg)
        self.assertEqual(reg.address, 0x100)

    def test_model_lookup_by_leaf_name(self):
        model = self._make_model()
        reg = model.get_register("SCRATCH_0")
        self.assertIsNotNone(reg)
        self.assertEqual(reg.address, 0x100)

    def test_model_suffix_match(self):
        model = self._make_model()
        # suffix match: "noc2axi.SCRATCH_0" should match "smu.noc2axi.SCRATCH_0"
        reg = model.get_register("noc2axi.SCRATCH_0")
        self.assertIsNotNone(reg)
        self.assertEqual(reg.address, 0x100)

    def test_model_ambiguous_leaf_returns_first(self):
        model = RegisterModel(name="ambig")
        r0 = Register("SCRATCH", address=0x100, fields=[
            RegisterField("d", lsb=0, msb=31),
        ])
        r1 = Register("SCRATCH", address=0x200, fields=[
            RegisterField("d", lsb=0, msb=31),
        ])
        model.add_register(r0, hierarchical_name="block_a.SCRATCH")
        model.add_register(r1, hierarchical_name="block_b.SCRATCH")
        # Leaf "SCRATCH" was indexed at first registration; block_a wins.
        result = model.get_register("SCRATCH")
        self.assertIsNotNone(result)
        self.assertEqual(result.address, 0x100)

    def test_model_summary(self):
        model = self._make_model()
        s = model.summary()
        self.assertIn("test_model", s)
        self.assertIn("SCRATCH_0", s)
        self.assertTrue(len(s) > 0)

    def test_model_all_registers(self):
        model = self._make_model()
        regs = model.all_registers()
        self.assertEqual(len(regs), 2)
        # Verify deduplicated (no aliases from name index)
        addresses = [r.address for r in regs]
        self.assertEqual(len(addresses), len(set(addresses)))

    def test_model_register_count(self):
        model = self._make_model()
        self.assertEqual(model.register_count, 2)


if __name__ == "__main__":
    unittest.main()
