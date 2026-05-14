"""Unit tests for loading RegisterModels from SystemRDL source."""

import os
import tempfile
import unittest

import pytest

# Skip the entire module if systemrdl-compiler isn't installed.
pytest.importorskip("systemrdl")

from cocotbext.ral import SwAccess
from cocotbext.ral.adapters.rdl_loader import load_rdl


def _compile_rdl(source: str):
    """Write `source` to a temp .rdl file and return the loaded RegisterModel."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".rdl", delete=False
    )
    try:
        tmp.write(source)
        tmp.close()
        return load_rdl(tmp.name)
    finally:
        os.unlink(tmp.name)


class TestRdlLoaderBasic(unittest.TestCase):

    def test_addrmap_reg_field_hierarchy(self):
        model = _compile_rdl("""
            addrmap ip {
                reg {
                    regwidth = 32;
                    field { sw = rw; hw = r; } enable[0:0] = 0;
                    field { sw = rw; hw = r; } mode[3:1] = 3'h2;
                } CTRL @ 0x000;
            };
        """)
        regs = model.all_registers()
        self.assertEqual(len(regs), 1)
        ctrl = regs[0]
        self.assertEqual(ctrl.name, "CTRL")
        self.assertEqual(ctrl.address, 0x000)
        self.assertEqual(ctrl.size_bits, 32)
        self.assertEqual(len(ctrl.fields), 2)
        enable = ctrl.get_field("enable")
        mode = ctrl.get_field("mode")
        self.assertEqual((enable.lsb, enable.msb), (0, 0))
        self.assertEqual((mode.lsb, mode.msb), (1, 3))
        self.assertEqual(mode.reset_value, 0x2)


class TestRdlLoaderSwAccess(unittest.TestCase):

    def test_sw_access_mapping(self):
        model = _compile_rdl("""
            addrmap ip {
                reg {
                    regwidth = 32;
                    field { sw = rw; hw = r; } a[0:0] = 0;
                    field { sw = r;  hw = w; } b[1:1] = 0;
                    field { sw = w;  hw = r; } c[2:2] = 0;
                    field { sw = rw; hw = r; woclr; } d[3:3] = 0;
                } R @ 0x000;
            };
        """)
        r = model.all_registers()[0]
        self.assertEqual(r.get_field("a").sw_access, SwAccess.RW)
        self.assertEqual(r.get_field("b").sw_access, SwAccess.RO)
        self.assertEqual(r.get_field("c").sw_access, SwAccess.WO)
        self.assertEqual(r.get_field("d").sw_access, SwAccess.WOCLR)


class TestRdlLoaderResetValues(unittest.TestCase):

    def test_reset_values_propagate(self):
        model = _compile_rdl("""
            addrmap ip {
                reg {
                    regwidth = 32;
                    field { sw = rw; hw = r; } a[7:0]   = 8'hAB;
                    field { sw = rw; hw = r; } b[15:8]  = 8'hCD;
                    field { sw = rw; hw = r; } c[31:16] = 16'hBEEF;
                } R @ 0x000;
            };
        """)
        r = model.all_registers()[0]
        self.assertEqual(r.get_field("a").reset_value, 0xAB)
        self.assertEqual(r.get_field("b").reset_value, 0xCD)
        self.assertEqual(r.get_field("c").reset_value, 0xBEEF)
        # Composite reset for whole register
        self.assertEqual(r.reset_value, 0xBEEFCDAB)


class TestRdlLoaderDontCompare(unittest.TestCase):
    """`dontcompare = true` in RDL must load as volatile=True so the
    predictor skips read-checks on that field. Conversely, no annotation
    leaves volatile inferred from access type.
    """

    def test_rw_default_is_not_volatile(self):
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = rw; hw = r; } x[31:0] = 0;
                } R @ 0x0;
            };
        """)
        f = model.all_registers()[0].get_field("x")
        self.assertFalse(f.volatile)

    def test_rw_with_dontcompare_is_volatile(self):
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = rw; hw = r; dontcompare; } x[31:0] = 0;
                } R @ 0x0;
            };
        """)
        f = model.all_registers()[0].get_field("x")
        self.assertTrue(f.volatile)

    def test_ro_default_is_volatile(self):
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = r; hw = w; } x[31:0] = 32'hDEADBEEF;
                } R @ 0x0;
            };
        """)
        f = model.all_registers()[0].get_field("x")
        self.assertTrue(f.volatile)

    def test_ro_with_explicit_dontcompare_false_is_not_volatile(self):
        """`dontcompare = false` on an RO field opts it into read-checking."""
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = r; hw = w; dontcompare = false; }
                        x[31:0] = 32'hDEADBEEF;
                } R @ 0x0;
            };
        """)
        f = model.all_registers()[0].get_field("x")
        self.assertFalse(f.volatile)

    def test_rw_with_explicit_dontcompare_false_stays_checked(self):
        """`dontcompare = false` on RW is a no-op (RW is already checked)."""
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = rw; hw = r; dontcompare = false; } x[31:0] = 0;
                } R @ 0x0;
            };
        """)
        f = model.all_registers()[0].get_field("x")
        self.assertFalse(f.volatile)


class TestRdlLoaderAddressing(unittest.TestCase):

    def test_nested_regfile_addresses(self):
        model = _compile_rdl("""
            addrmap ip {
                regfile {
                    reg { regwidth = 32;
                        field { sw = rw; hw = r; } v[31:0] = 0;
                    } A @ 0x000;
                    reg { regwidth = 32;
                        field { sw = rw; hw = r; } v[31:0] = 0;
                    } B @ 0x004;
                } group @ 0x100;
            };
        """)
        addrs = sorted(r.address for r in model.all_registers())
        # 0x100 (regfile base) + 0x000/0x004 (reg offsets)
        self.assertEqual(addrs, [0x100, 0x104])


class TestRdlLoaderArrays(unittest.TestCase):

    def test_array_registers_unrolled(self):
        model = _compile_rdl("""
            addrmap ip {
                reg { regwidth = 32;
                    field { sw = rw; hw = r; } v[31:0] = 0;
                } R[4] @ 0x000;
            };
        """)
        regs = sorted(model.all_registers(), key=lambda r: r.address)
        # Array of 4 registers, default stride = regwidth/8 = 4 bytes
        self.assertEqual(len(regs), 4)
        self.assertEqual([r.address for r in regs], [0x0, 0x4, 0x8, 0xC])
        # Each indexed copy has a distinct hierarchical name
        names = [r.hierarchical_name for r in regs]
        self.assertEqual(len(set(names)), 4)


class TestRdlLoaderMemory(unittest.TestCase):

    def test_mem_node_becomes_memory(self):
        model = _compile_rdl("""
            addrmap ip {
                external mem {
                    memwidth = 32;
                    mementries = 16;
                } sram @ 0x1000;
            };
        """)
        mems = model.all_memories()
        self.assertEqual(len(mems), 1)
        sram = mems[0]
        self.assertEqual(sram.base_address, 0x1000)
        # 16 entries × 32 bits = 64 bytes
        self.assertEqual(sram.size_bytes, 64)


class TestRdlLoaderHierarchicalNaming(unittest.TestCase):

    def test_hierarchical_name_includes_regfile(self):
        model = _compile_rdl("""
            addrmap ip {
                regfile {
                    reg { regwidth = 32;
                        field { sw = rw; hw = r; } v[31:0] = 0;
                    } CTRL @ 0x000;
                } block @ 0x100;
            };
        """)
        reg = model.get_register(0x100)
        self.assertIsNotNone(reg)
        self.assertIn("block", reg.hierarchical_name)
        self.assertIn("CTRL", reg.hierarchical_name)


if __name__ == "__main__":
    unittest.main()
