"""Unit tests for loading RegisterModels from JSON register files."""

import json
import os
import tempfile
import unittest

from cocotbext.ral.adapters.json_loader import load_json
from cocotbext.ral import SwAccess


class TestJsonLoaderSynthetic(unittest.TestCase):

    def test_synthetic_json(self):
        """Load a minimal synthetic JSON, verify structure."""
        data = {
            "type": "addrmap",
            "inst_name": "test_ip",
            "addr_offset": 0,
            "children": [
                {
                    "type": "regfile",
                    "inst_name": "regs",
                    "addr_offset": 256,
                    "children": [
                        {
                            "type": "reg",
                            "inst_name": "CTRL",
                            "addr_offset": 0,
                            "regsize": 32,
                            "desc": "Control register",
                            "children": [
                                {
                                    "type": "field",
                                    "inst_name": "enable",
                                    "lsb": 0,
                                    "msb": 0,
                                    "reset": 0,
                                    "sw_access": "rw",
                                    "woclr": 0,
                                },
                                {
                                    "type": "field",
                                    "inst_name": "status",
                                    "lsb": 1,
                                    "msb": 1,
                                    "reset": 1,
                                    "sw_access": "r",
                                    "woclr": 0,
                                },
                                {
                                    "type": "field",
                                    "inst_name": "clear",
                                    "lsb": 8,
                                    "msb": 15,
                                    "reset": 255,
                                    "sw_access": "rw",
                                    "woclr": 1,
                                },
                            ],
                        },
                        {
                            "type": "reg",
                            "inst_name": "DATA",
                            "addr_offset": 4,
                            "regsize": 32,
                            "desc": "Data register",
                            "children": [
                                {
                                    "type": "field",
                                    "inst_name": "value",
                                    "lsb": 0,
                                    "msb": 31,
                                    "reset": 0,
                                    "sw_access": "rw",
                                    "woclr": 0,
                                }
                            ],
                        },
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            model = load_json(tmp_path, model_name="synthetic")
            self.assertEqual(model.name, "synthetic")
            self.assertEqual(model.register_count, 2)

            # Verify address accumulation: regfile base=256, CTRL offset=0, DATA offset=4
            ctrl = model.get_register("CTRL")
            self.assertIsNotNone(ctrl)
            self.assertEqual(ctrl.address, 256)

            data_reg = model.get_register("DATA")
            self.assertIsNotNone(data_reg)
            self.assertEqual(data_reg.address, 260)

            # Verify field access types
            enable = ctrl.get_field("enable")
            self.assertEqual(enable.sw_access, SwAccess.RW)
            status = ctrl.get_field("status")
            self.assertEqual(status.sw_access, SwAccess.RO)
            clear = ctrl.get_field("clear")
            self.assertEqual(clear.sw_access, SwAccess.WOCLR)
            self.assertEqual(clear.reset_value, 0xFF)
        finally:
            os.unlink(tmp_path)


class TestJsonLoaderSideEffects(unittest.TestCase):
    """woclr / woset / rclr / rset via boolean flags and onwrite/onread."""

    def _load(self, fields):
        data = {
            "type": "addrmap", "inst_name": "ip", "addr_offset": 0,
            "children": [{
                "type": "reg", "inst_name": "R", "addr_offset": 0,
                "regsize": 32, "children": fields,
            }],
        }
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        try:
            json.dump(data, tmp)
            tmp.close()
            return load_json(tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_flag_and_onwrite_onread_forms(self):
        model = self._load([
            {"type": "field", "inst_name": "a", "lsb": 0, "msb": 0, "sw_access": "rw", "woclr": 1},
            {"type": "field", "inst_name": "b", "lsb": 1, "msb": 1, "sw_access": "rw", "woset": 1},
            {"type": "field", "inst_name": "c", "lsb": 2, "msb": 2, "sw_access": "r",  "rclr": 1},
            {"type": "field", "inst_name": "d", "lsb": 3, "msb": 3, "sw_access": "r",  "rset": 1},
            {"type": "field", "inst_name": "e", "lsb": 4, "msb": 4, "sw_access": "rw", "onwrite": "woset"},
            {"type": "field", "inst_name": "f", "lsb": 5, "msb": 5, "sw_access": "r",  "onread": "rclr"},
        ])
        reg = model.all_registers()[0]
        acc = {fld.name: fld.sw_access for fld in reg.fields}
        self.assertEqual(acc["a"], SwAccess.W1C)
        self.assertEqual(acc["b"], SwAccess.W1S)
        self.assertEqual(acc["c"], SwAccess.RCLR)
        self.assertEqual(acc["d"], SwAccess.RSET)
        self.assertEqual(acc["e"], SwAccess.W1S)
        self.assertEqual(acc["f"], SwAccess.RCLR)

    def test_enum_and_counter(self):
        model = self._load([
            {"type": "field", "inst_name": "mode", "lsb": 0, "msb": 1, "sw_access": "rw",
             "encode": {"OFF": 0, "FAST": 2}},
            {"type": "field", "inst_name": "cnt", "lsb": 2, "msb": 9, "sw_access": "r",
             "counter": 1},
        ])
        reg = model.all_registers()[0]
        mode = reg.get_field("mode")
        cnt = reg.get_field("cnt")
        self.assertEqual(mode.enum, {"OFF": 0, "FAST": 2})
        self.assertTrue(cnt.is_counter)
        self.assertTrue(cnt.is_volatile)


if __name__ == "__main__":
    unittest.main()
