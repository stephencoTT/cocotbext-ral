"""Passive AMBA bus monitors that observe transactions and feed the predictor.

Supports APB, AXI-Lite, and full AXI protocols. Each monitor watches bus
activity without driving any signals and updates the RAL predictor/checker
on every observed transaction.
"""

import logging

import cocotb
from cocotb.triggers import RisingEdge

from .predictor import Predictor
from .checker import Checker


class ApbRalMonitor:
    """Passive APB bus monitor.

    Samples APB signals on the rising clock edge when psel & penable & pready
    are all asserted. Feeds observed writes to the predictor and checks
    observed reads.
    """

    def __init__(self, bus, clock, predictor: Predictor, checker: Checker, name: str = ""):
        self.bus = bus
        self.clock = clock
        self.predictor = predictor
        self.checker = checker
        self.log = logging.getLogger(f"ral.{name}.apb_monitor" if name else "ral.apb_monitor")
        self._running = True
        self._task = cocotb.start_soon(self._monitor_loop())

    async def _monitor_loop(self):
        while self._running:
            await RisingEdge(self.clock)
            try:
                psel = int(self.bus.psel.value)
                penable = int(self.bus.penable.value) if hasattr(self.bus, 'penable') else 1
                pready = int(self.bus.pready.value)
            except (AttributeError, ValueError):
                continue

            if not (psel and penable and pready):
                continue

            addr = int(self.bus.paddr.value)
            pwrite = int(self.bus.pwrite.value)
            reg = self.predictor.model.get_register_by_address(addr)
            if reg is None:
                continue

            if pwrite:
                wdata = int(self.bus.pwdata.value)
                self.log.info(f"APB Write: {reg.hierarchical_name} @ 0x{addr:08x} = 0x{wdata:08x}")
                self.predictor.predict_write(addr, wdata)
            else:
                rdata = int(self.bus.prdata.value)
                self.log.info(f"APB Read:  {reg.hierarchical_name} @ 0x{addr:08x} -> 0x{rdata:08x}")
                result = self.predictor.predict_read(addr, rdata)
                self.checker.check(result)

    def stop(self):
        """Stop the monitor coroutine."""
        self._running = False


class AxiLiteRalMonitor:
    """Passive AXI-Lite bus monitor using cocotbext channel monitors.

    Correlates AW+W channels for writes and AR+R channels for reads.
    """

    def __init__(self, bus, clock, reset, predictor: Predictor, checker: Checker, name: str = ""):
        self.predictor = predictor
        self.checker = checker
        self.log = logging.getLogger(f"ral.{name}.axil_monitor" if name else "ral.axil_monitor")
        self._running = True

        # Import channel monitors (not exported from cocotbext.axi __init__)
        from cocotbext.axi.axil_channels import (
            AxiLiteAWMonitor,
            AxiLiteWMonitor,
            AxiLiteARMonitor,
            AxiLiteRMonitor,
        )

        self._aw_mon = AxiLiteAWMonitor(bus.write.aw, clock, reset)
        self._w_mon = AxiLiteWMonitor(bus.write.w, clock, reset)
        self._ar_mon = AxiLiteARMonitor(bus.read.ar, clock, reset)
        self._r_mon = AxiLiteRMonitor(bus.read.r, clock, reset)

        self._write_task = cocotb.start_soon(self._write_correlator())
        self._read_task = cocotb.start_soon(self._read_correlator())

    async def _write_correlator(self):
        """Match AW + W channel transactions for writes."""
        while self._running:
            aw_txn = await self._aw_mon.recv()
            w_txn = await self._w_mon.recv()
            addr = int(aw_txn.awaddr)
            data = int.from_bytes(bytes(w_txn.wdata), byteorder="little")
            reg = self.predictor.model.get_register_by_address(addr)
            if reg is None:
                continue
            self.log.info(f"AXI-Lite Write: {reg.hierarchical_name} @ 0x{addr:08x} = 0x{data:08x}")
            self.predictor.predict_write(addr, data)

    async def _read_correlator(self):
        """Match AR + R channel transactions for reads."""
        while self._running:
            ar_txn = await self._ar_mon.recv()
            r_txn = await self._r_mon.recv()
            addr = int(ar_txn.araddr)
            data = int.from_bytes(bytes(r_txn.rdata), byteorder="little")
            reg = self.predictor.model.get_register_by_address(addr)
            if reg is None:
                continue
            self.log.info(f"AXI-Lite Read:  {reg.hierarchical_name} @ 0x{addr:08x} -> 0x{data:08x}")
            result = self.predictor.predict_read(addr, data)
            self.checker.check(result)

    def stop(self):
        """Stop the monitor coroutines."""
        self._running = False


class AxiRalMonitor:
    """Passive full AXI bus monitor using cocotbext channel monitors.

    Handles burst transactions and ID-based matching.
    """

    def __init__(self, bus, clock, reset, predictor: Predictor, checker: Checker, name: str = ""):
        self.predictor = predictor
        self.checker = checker
        self.log = logging.getLogger(f"ral.{name}.axi_monitor" if name else "ral.axi_monitor")
        self._running = True

        from cocotbext.axi.axi_channels import (
            AxiAWMonitor,
            AxiWMonitor,
            AxiARMonitor,
            AxiRMonitor,
        )

        self._aw_mon = AxiAWMonitor(bus.write.aw, clock, reset)
        self._w_mon = AxiWMonitor(bus.write.w, clock, reset)
        self._ar_mon = AxiARMonitor(bus.read.ar, clock, reset)
        self._r_mon = AxiRMonitor(bus.read.r, clock, reset)

        self._write_task = cocotb.start_soon(self._write_correlator())
        self._read_task = cocotb.start_soon(self._read_correlator())

    async def _write_correlator(self):
        """Match AW + W beats for write bursts."""
        while self._running:
            aw_txn = await self._aw_mon.recv()
            addr = int(aw_txn.awaddr)
            burst_len = int(aw_txn.awlen) + 1  # AWLEN is 0-based
            burst_size = 1 << int(aw_txn.awsize)  # bytes per beat

            # Collect all W beats for this burst
            burst_data = bytearray()
            for i in range(burst_len):
                w_txn = await self._w_mon.recv()
                beat_bytes = bytes(w_txn.wdata)[:burst_size]
                burst_data.extend(beat_bytes)

            # Process each register-sized chunk
            offset = 0
            while offset < len(burst_data):
                chunk = burst_data[offset:offset + burst_size]
                data = int.from_bytes(chunk, byteorder="little")
                current_addr = addr + offset
                reg = self.predictor.model.get_register_by_address(current_addr)
                if reg is not None:
                    self.log.info(f"AXI Write: {reg.hierarchical_name} @ 0x{current_addr:08x} = 0x{data:08x}")
                    self.predictor.predict_write(current_addr, data, size_bytes=burst_size)
                offset += burst_size

    async def _read_correlator(self):
        """Match AR + R beats for read bursts."""
        while self._running:
            ar_txn = await self._ar_mon.recv()
            addr = int(ar_txn.araddr)
            burst_len = int(ar_txn.arlen) + 1
            burst_size = 1 << int(ar_txn.arsize)

            # Collect all R beats
            offset = 0
            for i in range(burst_len):
                r_txn = await self._r_mon.recv()
                beat_bytes = bytes(r_txn.rdata)[:burst_size]
                data = int.from_bytes(beat_bytes, byteorder="little")
                current_addr = addr + offset
                reg = self.predictor.model.get_register_by_address(current_addr)
                if reg is not None:
                    self.log.info(f"AXI Read:  {reg.hierarchical_name} @ 0x{current_addr:08x} -> 0x{data:08x}")
                    result = self.predictor.predict_read(
                        current_addr, data, size_bytes=burst_size
                    )
                    self.checker.check(result)
                offset += burst_size

    def stop(self):
        """Stop the monitor coroutines."""
        self._running = False
