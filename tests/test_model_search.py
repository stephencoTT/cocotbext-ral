"""Unit tests for RegisterModel search / grouping helpers."""

import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess


def _make_dma_model(n_engines: int = 4) -> RegisterModel:
    """Build a model with N DMA engines each exposing CTRL/STATUS/ADDR."""
    model = RegisterModel("chip")
    for i in range(n_engines):
        base = 0x1000 + i * 0x100
        model.add_register(
            Register(
                "CTRL", address=base + 0x0, size_bits=32,
                fields=[
                    RegisterField("enable", lsb=0, msb=0,
                                  sw_access=SwAccess.RW),
                    RegisterField("mode",   lsb=1, msb=2,
                                  sw_access=SwAccess.RW),
                ],
            ),
            hierarchical_name=f"chip.DMA{i}.CTRL",
        )
        model.add_register(
            Register(
                "STATUS", address=base + 0x4, size_bits=32,
                fields=[
                    RegisterField("busy",      lsb=0, msb=0,
                                  sw_access=SwAccess.RO),
                    RegisterField("error",     lsb=1, msb=1,
                                  sw_access=SwAccess.W1C),
                ],
            ),
            hierarchical_name=f"chip.DMA{i}.STATUS",
        )
        model.add_register(
            Register(
                "ADDR", address=base + 0x8, size_bits=32,
                fields=[
                    RegisterField("addr", lsb=0, msb=31,
                                  sw_access=SwAccess.RW),
                ],
            ),
            hierarchical_name=f"chip.DMA{i}.ADDR",
        )
    # Add one unrelated register so prefix filtering matters.
    model.add_register(
        Register(
            "MISC", address=0x9000, size_bits=32,
            fields=[RegisterField("data", 0, 31, sw_access=SwAccess.RW)],
        ),
        hierarchical_name="chip.MISC",
    )
    return model


class TestFindRegisters(unittest.TestCase):

    def test_glob_matches_all_dma_ctrl(self):
        model = _make_dma_model(n_engines=4)
        regs = model.find_registers(name="chip.DMA*.CTRL")
        self.assertEqual(len(regs), 4)
        self.assertEqual(
            [r.hierarchical_name for r in regs],
            ["chip.DMA0.CTRL", "chip.DMA1.CTRL",
             "chip.DMA2.CTRL", "chip.DMA3.CTRL"],
        )

    def test_address_sorted(self):
        model = _make_dma_model(n_engines=4)
        regs = model.find_registers(name="chip.DMA*.CTRL")
        addrs = [r.address for r in regs]
        self.assertEqual(addrs, sorted(addrs))

    def test_regex(self):
        model = _make_dma_model(n_engines=8)
        regs = model.find_registers(regex=r"DMA[0-3]\.STATUS")
        self.assertEqual(len(regs), 4)
        for r in regs:
            self.assertIn(".STATUS", r.hierarchical_name)

    def test_hierarchy_prefix(self):
        model = _make_dma_model(n_engines=4)
        regs = model.find_registers(hierarchy_prefix="chip.DMA2")
        self.assertEqual(len(regs), 3)
        for r in regs:
            self.assertTrue(r.hierarchical_name.startswith("chip.DMA2."))

    def test_access_filter_any_field(self):
        model = _make_dma_model(n_engines=2)
        # STATUS has a W1C field, CTRL/ADDR do not.
        regs = model.find_registers(access=SwAccess.W1C)
        self.assertEqual({r.name for r in regs}, {"STATUS"})

    def test_predicate(self):
        model = _make_dma_model(n_engines=2)
        regs = model.find_registers(predicate=lambda r: r.name == "ADDR")
        self.assertEqual(len(regs), 2)
        self.assertTrue(all(r.name == "ADDR" for r in regs))

    def test_combined_filters(self):
        model = _make_dma_model(n_engines=4)
        regs = model.find_registers(
            name="chip.DMA*.CTRL",
            hierarchy_prefix="chip.DMA1",
        )
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0].hierarchical_name, "chip.DMA1.CTRL")

    def test_name_and_regex_mutually_exclusive(self):
        model = _make_dma_model(n_engines=1)
        with self.assertRaises(ValueError):
            model.find_registers(name="*", regex=".*")

    def test_no_match_returns_empty(self):
        model = _make_dma_model(n_engines=2)
        self.assertEqual(model.find_registers(name="NOPE.*"), [])


class TestFindFields(unittest.TestCase):

    def test_by_access(self):
        model = _make_dma_model(n_engines=3)
        fields = model.find_fields(access=SwAccess.RO)
        self.assertEqual(len(fields), 3)
        for reg, fld in fields:
            self.assertEqual(fld.name, "busy")

    def test_by_name_glob(self):
        model = _make_dma_model(n_engines=2)
        fields = model.find_fields(name="enable")
        self.assertEqual(len(fields), 2)
        self.assertTrue(all(f.name == "enable" for _, f in fields))

    def test_by_reg_name(self):
        model = _make_dma_model(n_engines=4)
        fields = model.find_fields(reg_name="chip.DMA*.STATUS")
        # 4 engines * 2 status fields = 8
        self.assertEqual(len(fields), 8)

    def test_combined(self):
        model = _make_dma_model(n_engines=4)
        fields = model.find_fields(
            reg_name="chip.DMA*.STATUS",
            access=SwAccess.W1C,
        )
        self.assertEqual(len(fields), 4)
        self.assertTrue(all(f.name == "error" for _, f in fields))

    def test_sort_by_addr_then_lsb(self):
        model = _make_dma_model(n_engines=2)
        fields = model.find_fields(reg_name="chip.DMA0.CTRL")
        lsbs = [f.lsb for _, f in fields]
        self.assertEqual(lsbs, sorted(lsbs))


class TestGroupBy(unittest.TestCase):

    def test_group_by_engine_prefix(self):
        model = _make_dma_model(n_engines=3)
        groups = model.group_by(
            lambda r: r.hierarchical_name.split(".")[1] if "." in r.hierarchical_name else "_",
        )
        # 3 DMA engines plus MISC bucket
        self.assertIn("DMA0", groups)
        self.assertIn("DMA1", groups)
        self.assertIn("DMA2", groups)
        self.assertEqual(len(groups["DMA0"]), 3)

    def test_within_group_sorted_by_addr(self):
        model = _make_dma_model(n_engines=1)
        groups = model.group_by(lambda r: r.name)
        for regs in groups.values():
            addrs = [r.address for r in regs]
            self.assertEqual(addrs, sorted(addrs))


if __name__ == "__main__":
    unittest.main()
