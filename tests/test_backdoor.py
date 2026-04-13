"""Unit tests for BackdoorResolver variants."""

import unittest

from cocotbext.ral import Register, RegisterField, SwAccess
from cocotbext.ral.backdoor import (
    BackdoorResolver,
    MappingBackdoorResolver,
    PrefixBackdoorResolver,
)


class TestBackdoorResolver(unittest.TestCase):

    def _make_reg(self, hdl_path="", field_hdl_path=""):
        return Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=7, hdl_path=field_hdl_path),
        ], hdl_path=hdl_path)

    def test_base_resolver_returns_register_hdl_path(self):
        reg = self._make_reg(hdl_path="tb.dut.ctrl_reg")
        resolver = BackdoorResolver()
        self.assertEqual(resolver.resolve_register_path(reg), "tb.dut.ctrl_reg")

    def test_base_resolver_returns_none_for_no_path(self):
        reg = self._make_reg()
        resolver = BackdoorResolver()
        self.assertIsNone(resolver.resolve_register_path(reg))

    def test_base_resolver_returns_field_hdl_path(self):
        reg = self._make_reg(field_hdl_path="tb.dut.ctrl_reg.f0")
        resolver = BackdoorResolver()
        field = reg.get_field("f0")
        self.assertEqual(resolver.resolve_field_path(reg, field), "tb.dut.ctrl_reg.f0")

    def test_base_resolver_returns_none_for_no_field_path(self):
        reg = self._make_reg()
        resolver = BackdoorResolver()
        field = reg.get_field("f0")
        self.assertIsNone(resolver.resolve_field_path(reg, field))


class TestPrefixBackdoorResolver(unittest.TestCase):

    def _make_reg(self, hdl_path="", field_hdl_path=""):
        reg = Register("REG", address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=7, hdl_path=field_hdl_path),
        ], hdl_path=hdl_path)
        reg.hierarchical_name = "block.REG"
        return reg

    def test_prefix_prepended_to_register_path(self):
        reg = self._make_reg(hdl_path="ctrl_reg")
        resolver = PrefixBackdoorResolver(prefix="tb.dut.tile_3_4")
        self.assertEqual(resolver.resolve_register_path(reg), "tb.dut.tile_3_4.ctrl_reg")

    def test_prefix_prepended_to_field_path(self):
        reg = self._make_reg(field_hdl_path="ctrl_reg.f0")
        resolver = PrefixBackdoorResolver(prefix="tb.dut.tile_3_4")
        field = reg.get_field("f0")
        self.assertEqual(resolver.resolve_field_path(reg, field), "tb.dut.tile_3_4.ctrl_reg.f0")

    def test_prefix_not_doubled(self):
        """If the path already starts with the prefix, don't double it."""
        reg = self._make_reg(hdl_path="tb.dut.tile_3_4.ctrl_reg")
        resolver = PrefixBackdoorResolver(prefix="tb.dut.tile_3_4")
        self.assertEqual(resolver.resolve_register_path(reg), "tb.dut.tile_3_4.ctrl_reg")

    def test_prefix_returns_none_for_no_path(self):
        reg = self._make_reg()
        resolver = PrefixBackdoorResolver(prefix="tb.dut")
        self.assertIsNone(resolver.resolve_register_path(reg))

    def test_empty_prefix(self):
        reg = self._make_reg(hdl_path="ctrl_reg")
        resolver = PrefixBackdoorResolver(prefix="")
        self.assertEqual(resolver.resolve_register_path(reg), "ctrl_reg")


class TestMappingBackdoorResolver(unittest.TestCase):

    def _make_reg(self, name="REG", hdl_path=""):
        reg = Register(name, address=0x0, fields=[
            RegisterField("f0", lsb=0, msb=7),
        ], hdl_path=hdl_path)
        reg.hierarchical_name = f"block.{name}"
        return reg

    def test_mapping_overrides_register_path(self):
        reg = self._make_reg(hdl_path="original.path")
        resolver = MappingBackdoorResolver(
            register_paths={"block.REG": "mapped.path.ctrl_reg"},
            field_paths={},
        )
        self.assertEqual(resolver.resolve_register_path(reg), "mapped.path.ctrl_reg")

    def test_mapping_falls_back_to_spec_path(self):
        reg = self._make_reg(hdl_path="original.path")
        resolver = MappingBackdoorResolver(
            register_paths={},
            field_paths={},
        )
        self.assertEqual(resolver.resolve_register_path(reg), "original.path")

    def test_mapping_overrides_field_path(self):
        reg = self._make_reg()
        resolver = MappingBackdoorResolver(
            register_paths={},
            field_paths={"block.REG.f0": "mapped.field.path"},
        )
        field = reg.get_field("f0")
        self.assertEqual(resolver.resolve_field_path(reg, field), "mapped.field.path")

    def test_mapping_falls_back_to_none_for_field(self):
        reg = self._make_reg()
        resolver = MappingBackdoorResolver(
            register_paths={},
            field_paths={},
        )
        field = reg.get_field("f0")
        self.assertIsNone(resolver.resolve_field_path(reg, field))


if __name__ == "__main__":
    unittest.main()
