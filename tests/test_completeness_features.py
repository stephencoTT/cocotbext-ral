"""Unit tests for the broader completeness features.

Covers field enumerations, reset domains, wide-register splitting on narrow
buses, bus-response checking, byte-strobe partial writes, pre/post callbacks,
memory burst access, and per-RAL address offset (multiple maps). Bus behavior
is exercised with recording fake masters -- no simulator needed.
"""

import asyncio
import unittest

from cocotbext.ral import (
    RegisterModel, Register, RegisterField, SwAccess, RuntimeRAL, Memory,
)


def run(coro):
    return asyncio.run(coro)


class RecordingApbMaster:
    """Minimal APB-shaped master: write(addr, value) / read(addr) -> bytes."""

    def __init__(self):
        self.mem = {}
        self.writes = []
        self.reads = []

    async def write(self, addr, value):
        self.writes.append((addr, value))
        self.mem[addr] = value

    async def read(self, addr):
        self.reads.append(addr)
        return self.mem.get(addr, 0).to_bytes(4, "little")


class _Resp:
    def __init__(self, data=b"\x00\x00\x00\x00", resp=0):
        self.data = data
        self.resp = resp


class RecordingAxiMaster:
    """Minimal AXI-Lite-shaped master returning a response object."""

    def __init__(self, resp_code=0):
        self.resp_code = resp_code
        self.mem = {}
        self.writes = []

    async def write(self, addr, data_bytes):
        self.writes.append((addr, bytes(data_bytes)))
        self.mem[addr] = bytes(data_bytes)
        return _Resp(resp=self.resp_code)

    async def read(self, addr, size):
        data = self.mem.get(addr, (0).to_bytes(size, "little"))
        return _Resp(data=data, resp=self.resp_code)


def _simple_model():
    model = RegisterModel("ip")
    model.add_register(Register("R", address=0x0, size_bits=32, fields=[
        RegisterField("v", lsb=0, msb=31, reset_value=0, sw_access=SwAccess.RW),
    ]), "R")
    return model


# ---------------------------------------------------------------------------
# Field enumerations
# ---------------------------------------------------------------------------
class TestFieldEnum(unittest.TestCase):

    def test_enum_value_and_name(self):
        f = RegisterField("mode", 0, 1, sw_access=SwAccess.RW,
                          enum={"OFF": 0, "SLOW": 1, "FAST": 2})
        self.assertEqual(f.enum_value("FAST"), 2)
        self.assertEqual(f.enum_name(2), "FAST")
        self.assertIsNone(f.enum_name(3))
        with self.assertRaises(KeyError):
            f.enum_value("BOGUS")

    def test_no_enum(self):
        f = RegisterField("x", 0, 0, sw_access=SwAccess.RW)
        self.assertIsNone(f.enum_name(0))
        with self.assertRaises(KeyError):
            f.enum_value("anything")

    def _enum_model(self):
        model = RegisterModel("ip")
        model.add_register(Register("CTRL", address=0x0, size_bits=32, fields=[
            RegisterField("mode", lsb=0, msb=1, reset_value=0, sw_access=SwAccess.RW,
                          enum={"OFF": 0, "FAST": 2}),
        ]), "CTRL")
        return model

    def test_write_field_accepts_enum_string(self):
        ral = RuntimeRAL("ip", self._enum_model())
        ral.attach_master(RecordingApbMaster(), protocol="apb")
        run(ral.write_field("CTRL", "mode", "FAST"))
        self.assertEqual(ral.mirror_field("CTRL", "mode"), 2)
        self.assertEqual(run(ral.read_field_name("CTRL", "mode")), "FAST")

    def test_set_field_accepts_enum_string(self):
        ral = RuntimeRAL("ip", self._enum_model())
        m = RecordingApbMaster()
        ral.attach_master(m, protocol="apb")
        ral.set_field("CTRL", "mode", "FAST")
        run(ral.update("CTRL"))
        self.assertEqual(m.writes[-1], (0x0, 2))


# ---------------------------------------------------------------------------
# Reset domains
# ---------------------------------------------------------------------------
class TestResetDomains(unittest.TestCase):

    def _model(self):
        model = RegisterModel("ip")
        model.add_register(Register("R", address=0x0, size_bits=32, fields=[
            RegisterField("f", lsb=0, msb=3, reset_value=0x3, sw_access=SwAccess.RW,
                          resets={"soft": 0xF}),
        ]), "R")
        return model

    def test_field_and_register_reset_value_for(self):
        model = self._model()
        f = model.get_register("R").get_field("f")
        self.assertEqual(f.reset_value_for(), 0x3)
        self.assertEqual(f.reset_value_for("soft"), 0xF)
        self.assertEqual(f.reset_value_for("missing"), 0x3)  # falls back
        self.assertEqual(model.get_register("R").reset_domains(), ["soft"])

    def test_ral_reset_by_domain(self):
        ral = RuntimeRAL("ip", self._model())
        self.assertEqual(ral.mirror_field("R", "f"), 0x3)
        ral.set_predicted("R", 0x0)
        ral.reset()
        self.assertEqual(ral.mirror_field("R", "f"), 0x3)
        ral.set_predicted("R", 0x0)
        ral.reset(domain="soft")
        self.assertEqual(ral.mirror_field("R", "f"), 0xF)


# ---------------------------------------------------------------------------
# Wide registers on a narrow bus
# ---------------------------------------------------------------------------
class TestWideRegister(unittest.TestCase):

    def _model(self):
        model = RegisterModel("ip")
        model.add_register(Register("WIDE", address=0x10, size_bits=64, fields=[
            RegisterField("data", lsb=0, msb=63, reset_value=0, sw_access=SwAccess.RW),
        ]), "WIDE")
        return model

    def test_apb_splits_into_words(self):
        m = RecordingApbMaster()
        ral = RuntimeRAL("ip", self._model(), data_width=4)
        ral.attach_master(m, protocol="apb")
        run(ral.write("WIDE", 0x1122334455667788))
        self.assertEqual(m.writes, [(0x10, 0x55667788), (0x14, 0x11223344)])
        self.assertEqual(run(ral.read("WIDE")), 0x1122334455667788)


# ---------------------------------------------------------------------------
# Bus response checking
# ---------------------------------------------------------------------------
class TestBusResponse(unittest.TestCase):

    def test_error_response_raises_when_enabled(self):
        ral = RuntimeRAL("ip", _simple_model(), check_response=True)
        ral.attach_master(RecordingAxiMaster(resp_code=2), protocol="axil")
        with self.assertRaises(RuntimeError):
            run(ral.write("R", 0x1))

    def test_ok_response_passes(self):
        ral = RuntimeRAL("ip", _simple_model(), check_response=True)
        ral.attach_master(RecordingAxiMaster(resp_code=0), protocol="axil")
        run(ral.write("R", 0x1))  # no raise

    def test_not_checked_by_default(self):
        ral = RuntimeRAL("ip", _simple_model())
        ral.attach_master(RecordingAxiMaster(resp_code=2), protocol="axil")
        run(ral.write("R", 0x1))  # no raise

    def test_error_logged_not_raised_when_configured(self):
        ral = RuntimeRAL("ip", _simple_model(), check_response=True,
                         raise_on_bus_error=False)
        ral.attach_master(RecordingAxiMaster(resp_code=3), protocol="axil")
        run(ral.write("R", 0x1))  # logs, does not raise


# ---------------------------------------------------------------------------
# Byte-strobe partial writes
# ---------------------------------------------------------------------------
class TestPartialWrite(unittest.TestCase):

    def _model(self):
        model = RegisterModel("ip")
        model.add_register(Register("R", address=0x0, size_bits=32, fields=[
            RegisterField("b0", lsb=0, msb=7, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("b1", lsb=8, msb=15, reset_value=0, sw_access=SwAccess.RW),
            RegisterField("nib", lsb=16, msb=19, reset_value=0, sw_access=SwAccess.RW),
        ]), "R")
        return model

    def test_byte_aligned_partial_write_skips_rmw(self):
        m = RecordingAxiMaster()
        ral = RuntimeRAL("ip", self._model())
        ral.attach_master(m, protocol="axil")
        run(ral.write_field("R", "b1", 0xAB, partial=True))
        # One byte written at byte offset 1, no read-modify-write.
        self.assertEqual(m.writes, [(0x1, b"\xab")])
        self.assertEqual(ral.mirror_field("R", "b1"), 0xAB)

    def test_non_byte_aligned_partial_falls_back_to_rmw(self):
        m = RecordingAxiMaster()
        ral = RuntimeRAL("ip", self._model())
        ral.attach_master(m, protocol="axil")
        # 'nib' is 4 bits wide -> not byte-sized -> normal RMW (a read happens).
        run(ral.write_field("R", "nib", 0x5, partial=True))
        self.assertEqual(ral.mirror_field("R", "nib"), 0x5)
        self.assertTrue(m.writes, "a write-back should have occurred")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
class TestCallbacks(unittest.TestCase):

    def test_pre_post_hooks_fire(self):
        events = []
        ral = RuntimeRAL("ip", _simple_model())
        ral.attach_master(RecordingApbMaster(), protocol="apb")
        ral.add_callback("pre_write", lambda r, t, v: events.append(("pre_write", t, v)))
        ral.add_callback("post_write", lambda r, t, v: events.append(("post_write", t, v)))
        ral.add_callback("pre_read", lambda r, t, v: events.append(("pre_read", t, v)))
        ral.add_callback("post_read", lambda r, t, v: events.append(("post_read", t, v)))

        run(ral.write("R", 0x5))
        run(ral.read("R"))

        self.assertEqual(events[0], ("pre_write", "R", 0x5))
        self.assertEqual(events[1], ("post_write", "R", 0x5))
        self.assertEqual(events[2], ("pre_read", "R", None))
        self.assertEqual(events[3], ("post_read", "R", 0x5))

    def test_unknown_event_rejected(self):
        ral = RuntimeRAL("ip", _simple_model())
        with self.assertRaises(ValueError):
            ral.add_callback("on_explode", lambda *a: None)


# ---------------------------------------------------------------------------
# Memory burst
# ---------------------------------------------------------------------------
class TestMemoryBurst(unittest.TestCase):

    def _ral(self):
        model = RegisterModel("ip")
        model.add_memory(Memory("buf", base_address=0x1000, size_bytes=64), "buf")
        ral = RuntimeRAL("ip", model)
        return ral

    def test_write_and_read_block(self):
        m = RecordingApbMaster()
        ral = self._ral()
        ral.attach_master(m, protocol="apb")
        mem = ral.get_memory("buf")
        run(mem.write_block(0, [0xA, 0xB, 0xC]))
        self.assertEqual(m.writes, [(0x1000, 0xA), (0x1004, 0xB), (0x1008, 0xC)])
        self.assertEqual(run(mem.read_block(0, 3)), [0xA, 0xB, 0xC])


# ---------------------------------------------------------------------------
# Address offset (multiple maps)
# ---------------------------------------------------------------------------
class TestAddressOffset(unittest.TestCase):

    def test_offset_applied_to_bus_addresses(self):
        m = RecordingApbMaster()
        ral = RuntimeRAL("ip", _simple_model(), address_offset=0x8000)
        ral.attach_master(m, protocol="apb")
        run(ral.write("R", 0x5))
        self.assertEqual(m.writes, [(0x8000, 0x5)])
        # mirror stays keyed on the model address, independent of the offset.
        self.assertEqual(ral.mirror("R"), 0x5)

    def test_two_rals_one_model_distinct_maps(self):
        model = _simple_model()
        ma, mb = RecordingApbMaster(), RecordingApbMaster()
        ral_a = RuntimeRAL("a", model, address_offset=0x0)
        ral_b = RuntimeRAL("b", model, address_offset=0x10000)
        ral_a.attach_master(ma, protocol="apb")
        ral_b.attach_master(mb, protocol="apb")
        run(ral_a.write("R", 0xAA))
        run(ral_b.write("R", 0xBB))
        self.assertEqual(ma.writes, [(0x0, 0xAA)])
        self.assertEqual(mb.writes, [(0x10000, 0xBB)])
        # Independent runtime state per RAL.
        self.assertEqual(ral_a.mirror("R"), 0xAA)
        self.assertEqual(ral_b.mirror("R"), 0xBB)


if __name__ == "__main__":
    unittest.main()
