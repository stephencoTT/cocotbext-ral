"""Register transaction logger for cocotbext-ral.

Produces a detailed, grep-friendly log of every front-door register
transaction driven through a RAL instance.  Enabled by passing
``txn_log=True`` (or a file path) when constructing a ``RuntimeRAL``.

The log is optional and has zero overhead when disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, List, Optional, Union

from .register_model import Register, RegisterField
from .version import __version__

def _sim_time_str() -> str:
    """Return the current simulation time as a human-readable string."""
    try:
        from cocotb.utils import get_sim_time
        # Positional unit arg works on both cocotb 1.x (`units=`) and
        # cocotb 2.x (`unit=`), which renamed the keyword.
        t = get_sim_time("ns")
        if t >= 1_000_000:
            return f"{t / 1_000_000:.2f}ms"
        elif t >= 1_000:
            return f"{t / 1_000:.2f}us"
        else:
            return f"{t:.2f}ns"
    except Exception:
        return "?.??ns"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldDetail:
    """Per-field detail for a transaction."""
    name: str
    lsb: int
    msb: int
    value: int
    previous: Optional[int] = None
    expected: Optional[int] = None
    matched: Optional[bool] = None


@dataclass
class Transaction:
    """One register transaction record."""
    txn_id: int
    sim_time: str
    operation: str          # WRITE, READ, WRITE_FIELD, READ_FIELD
    model_path: str         # Hierarchical name from the register model
    address: int
    data: int
    size_bits: int
    protocol: str
    interface: str          # Bus master HDL path
    status: str             # OK, PASS, FAIL, SKIP, ERROR
    mirror_before: int
    mirror_after: int
    fields: List[FieldDetail] = field(default_factory=list)
    # WRITE_FIELD extras
    target_field: str = ""
    field_value: Optional[int] = None
    rmw_read_value: Optional[int] = None
    rmw_mask: Optional[int] = None
    rmw_safe: Optional[bool] = None
    rmw_reasons: List[str] = field(default_factory=list)
    # Bus-level sub-transactions captured during an RMW group (populated on
    # WRITE_FIELD entries when begin_rmw()/end_rmw() wraps the internal read
    # and write-back).
    substeps: List["Transaction"] = field(default_factory=list)
    # Backdoor
    backdoor_path: str = ""
    # Phase annotation
    phase: str = ""
    # Check details for reads
    expected_full: Optional[int] = None
    error_messages: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

_SEPARATOR = "-" * 72


def _substep_summary(txn: Transaction) -> str:
    """Render a compact one-line summary of an RMW sub-transaction."""
    if txn.operation == "READ":
        check = ""
        if txn.status.startswith("PASS"):
            check = "  (PASS)"
        elif txn.status.startswith("FAIL"):
            check = "  (FAIL)"
        elif txn.status.startswith("SKIP"):
            check = "  (SKIP)"
        return (f"READ   @ {txn.sim_time:<10s} 0x{txn.address:08X} "
                f"-> 0x{txn.data:08X}{check}")
    # WRITE
    return (f"WRITE  @ {txn.sim_time:<10s} 0x{txn.address:08X} "
            f"<- 0x{txn.data:08X}")


class TransactionLogger:
    """Accumulates and writes register transaction records to a file.

    Usage::

        logger = TransactionLogger("register_txns.log")
        logger.write_header(ral_name="top", protocol="axi", ...)
        logger.log_write(...)
        logger.log_read(...)
        logger.write_summary()
        logger.close()
    """

    def __init__(self, dest: Union[str, IO] = "register_txns.log"):
        if isinstance(dest, str):
            self._owns_file = True
            self._file: IO = open(dest, "w", encoding="utf-8")
            self._path = dest
        else:
            self._owns_file = False
            self._file = dest
            self._path = getattr(dest, "name", "<stream>")

        self._txn_count = 0
        self._writes = 0
        self._reads = 0
        self._passed = 0
        self._failed = 0
        self._skipped = 0
        self._first_time: Optional[str] = None
        self._last_time: Optional[str] = None
        self._transactions: List[Transaction] = []
        # When non-None, read/write txns are buffered as children of the
        # next WRITE_FIELD entry instead of being emitted standalone.
        self._rmw_substeps: Optional[List[Transaction]] = None

    # ------------------------------------------------------------------
    # Header / footer
    # ------------------------------------------------------------------

    def write_header(
        self,
        ral_name: str = "",
        protocol: str = "",
        interface: str = "",
        model_name: str = "",
        register_count: int = 0,
    ) -> None:
        w = self._file.write
        bar = "=" * 80
        w(f"{bar}\n")
        w(f"REGISTER TRANSACTION LOG -- cocotbext-ral v{__version__}\n")
        w(f"RAL Instance : {ral_name}\n")
        w(f"Protocol     : {protocol.upper()}\n")
        w(f"Interface    : {interface}\n")
        w(f"Model        : {model_name} ({register_count} registers)\n")
        w(f"Started      : {_sim_time_str()}\n")
        w(f"Log File     : {self._path}\n")
        w(f"{bar}\n\n")
        self._file.flush()

    def write_summary(self) -> None:
        w = self._file.write
        bar = "=" * 80
        w(f"\n{bar}\n")
        w("TRANSACTION SUMMARY\n")
        w(f"  Total      : {self._txn_count}\n")
        w(f"  Writes     : {self._writes}\n")
        w(f"  Reads      : {self._reads}\n")
        w(f"  Passed     : {self._passed}\n")
        w(f"  Failed     : {self._failed}\n")
        w(f"  Skipped    : {self._skipped}\n")
        if self._first_time and self._last_time:
            w(f"  Duration   : {self._first_time} - {self._last_time}\n")
        w(f"{bar}\n")
        self._file.flush()

    def close(self) -> None:
        if self._owns_file and self._file and not self._file.closed:
            self._file.close()

    # ------------------------------------------------------------------
    # Transaction logging
    # ------------------------------------------------------------------

    def log_write(
        self,
        reg: Optional[Register],
        address: int,
        data: int,
        size_bits: int,
        protocol: str,
        interface: str,
        mirror_before: int,
        mirror_after: int,
        fields: Optional[List[FieldDetail]] = None,
        backdoor_path: str = "",
        phase: str = "",
    ) -> Transaction:
        sim_time = _sim_time_str()

        txn = Transaction(
            txn_id=0,  # filled in below if emitted standalone
            sim_time=sim_time,
            operation="WRITE",
            model_path=reg.hierarchical_name if reg else f"<unmapped 0x{address:08x}>",
            address=address,
            data=data,
            size_bits=size_bits,
            protocol=protocol.upper(),
            interface=interface,
            status="OK",
            mirror_before=mirror_before,
            mirror_after=mirror_after,
            fields=fields or [],
            backdoor_path=backdoor_path,
            phase=phase,
        )

        if self._rmw_substeps is not None:
            # Buffered as an RMW child; the parent WRITE_FIELD will render it.
            self._rmw_substeps.append(txn)
            return txn

        self._txn_count += 1
        self._writes += 1
        txn.txn_id = self._txn_count
        self._track_time(sim_time)
        self._transactions.append(txn)
        self._emit_write(txn)
        return txn

    def log_read(
        self,
        reg: Optional[Register],
        address: int,
        data: int,
        size_bits: int,
        protocol: str,
        interface: str,
        mirror_value: int,
        expected_full: Optional[int],
        passed: Optional[bool],
        checking_enabled: bool,
        fields: Optional[List[FieldDetail]] = None,
        error_messages: Optional[List[str]] = None,
        backdoor_path: str = "",
        phase: str = "",
    ) -> Transaction:
        sim_time = _sim_time_str()

        if not checking_enabled:
            status = "SKIP  (checking disabled for this register)"
            status_bucket = "skipped"
        elif passed is None:
            status = "UNCHECKED"
            status_bucket = "skipped"
        elif passed:
            status = f"PASS  (expected 0x{expected_full:X}, got 0x{data:X})"
            status_bucket = "passed"
        else:
            status = f"FAIL  (expected 0x{expected_full:X}, got 0x{data:X})"
            status_bucket = "failed"

        txn = Transaction(
            txn_id=0,
            sim_time=sim_time,
            operation="READ",
            model_path=reg.hierarchical_name if reg else f"<unmapped 0x{address:08x}>",
            address=address,
            data=data,
            size_bits=size_bits,
            protocol=protocol.upper(),
            interface=interface,
            status=status,
            mirror_before=mirror_value,
            mirror_after=mirror_value,
            fields=fields or [],
            backdoor_path=backdoor_path,
            phase=phase,
            expected_full=expected_full,
            error_messages=error_messages or [],
        )

        if self._rmw_substeps is not None:
            # Buffered as an RMW child; counters update when the parent emits.
            self._rmw_substeps.append(txn)
            return txn

        self._txn_count += 1
        self._reads += 1
        txn.txn_id = self._txn_count
        self._track_time(sim_time)
        if status_bucket == "passed":
            self._passed += 1
        elif status_bucket == "failed":
            self._failed += 1
        else:
            self._skipped += 1
        self._transactions.append(txn)
        self._emit_read(txn)
        return txn

    def log_write_field(
        self,
        reg: Register,
        field_obj: RegisterField,
        field_value: int,
        full_write_value: int,
        rmw_read_value: int,
        size_bits: int,
        protocol: str,
        interface: str,
        mirror_before: int,
        mirror_after: int,
        rmw_safe: bool,
        rmw_reasons: Optional[List[str]] = None,
        backdoor_path: str = "",
        phase: str = "",
    ) -> Transaction:
        self._txn_count += 1
        self._writes += 1
        sim_time = _sim_time_str()
        self._track_time(sim_time)

        # Consume any buffered RMW sub-transactions so they render as children
        # of this WRITE_FIELD entry.
        substeps = self._rmw_substeps or []
        self._rmw_substeps = None

        txn = Transaction(
            txn_id=self._txn_count,
            sim_time=sim_time,
            operation="WRITE_FIELD (RMW)",
            model_path=reg.hierarchical_name,
            address=reg.address,
            data=full_write_value,
            size_bits=size_bits,
            protocol=protocol.upper(),
            interface=interface,
            status="OK",
            mirror_before=mirror_before,
            mirror_after=mirror_after,
            target_field=field_obj.name,
            field_value=field_value,
            rmw_read_value=rmw_read_value,
            rmw_mask=field_obj.mask << field_obj.lsb,
            rmw_safe=rmw_safe,
            rmw_reasons=rmw_reasons or [],
            substeps=substeps,
            backdoor_path=backdoor_path,
            phase=phase,
        )
        self._transactions.append(txn)
        self._emit_write_field(txn)
        return txn

    # ------------------------------------------------------------------
    # RMW grouping
    # ------------------------------------------------------------------

    def begin_rmw(self) -> None:
        """Start buffering read/write entries as RMW children.

        While a group is active, any call to :meth:`log_read` or
        :meth:`log_write` stores the transaction in an internal buffer
        instead of emitting it standalone. The next call to
        :meth:`log_write_field` consumes the buffer and renders the
        children nested under the field-write summary.

        Typical caller is :class:`RuntimeRAL` — test code does
        not normally invoke this directly.
        """
        self._rmw_substeps = []

    def end_rmw(self) -> None:
        """End the current RMW group without consuming the buffer.

        Use only to clean up when a group is opened but never closed by a
        matching :meth:`log_write_field` (for example, if an exception
        is raised mid-group). Any buffered sub-transactions are discarded.
        """
        self._rmw_substeps = None

    # ------------------------------------------------------------------
    # Phase annotation
    # ------------------------------------------------------------------

    def set_phase(self, phase: str) -> None:
        """Set a phase label that will be attached to subsequent transactions."""
        self._current_phase = phase
        self._file.write(f"\n  [{phase}]\n\n")
        self._file.flush()

    # ------------------------------------------------------------------
    # Emit helpers
    # ------------------------------------------------------------------

    def _track_time(self, sim_time: str) -> None:
        if self._first_time is None:
            self._first_time = sim_time
        self._last_time = sim_time

    def _emit_write(self, txn: Transaction) -> None:
        w = self._file.write
        w(f"--- TXN #{txn.txn_id:03d} @ {txn.sim_time} {_SEPARATOR}\n")
        w(f"  Operation  : {txn.operation}\n")
        w(f"  Model Path : {txn.model_path}\n")
        w(f"  Address    : 0x{txn.address:08X}\n")
        w(f"  Data       : 0x{txn.data:08X}\n")
        w(f"  Size       : {txn.size_bits}-bit\n")
        w(f"  Protocol   : {txn.protocol}\n")
        w(f"  Interface  : {txn.interface}\n")
        if txn.backdoor_path:
            w(f"  Backdoor   : {txn.backdoor_path}\n")
        w(f"  Status     : {txn.status}\n")
        w(f"  Mirror     : 0x{txn.mirror_before:08X} -> 0x{txn.mirror_after:08X}\n")
        if txn.fields:
            w("  Fields:\n")
            for fd in txn.fields:
                prev = f"  (was 0x{fd.previous:X})" if fd.previous is not None else ""
                w(f"    [{fd.msb:2d}:{fd.lsb:2d}] {fd.name:<16s} = 0x{fd.value:X}{prev}\n")
        w("\n")
        self._file.flush()

    def _emit_read(self, txn: Transaction) -> None:
        w = self._file.write
        w(f"--- TXN #{txn.txn_id:03d} @ {txn.sim_time} {_SEPARATOR}\n")
        w(f"  Operation  : {txn.operation}\n")
        w(f"  Model Path : {txn.model_path}\n")
        w(f"  Address    : 0x{txn.address:08X}\n")
        w(f"  Data       : 0x{txn.data:08X}\n")
        w(f"  Size       : {txn.size_bits}-bit\n")
        w(f"  Protocol   : {txn.protocol}\n")
        w(f"  Interface  : {txn.interface}\n")
        if txn.backdoor_path:
            w(f"  Backdoor   : {txn.backdoor_path}\n")
        w(f"  Status     : {txn.status}\n")
        w(f"  Mirror     : 0x{txn.mirror_before:08X}\n")
        if txn.fields:
            w("  Fields:\n")
            for fd in txn.fields:
                if fd.expected is not None:
                    match_str = "PASS" if fd.matched else "MISMATCH"
                    w(f"    [{fd.msb:2d}:{fd.lsb:2d}] {fd.name:<16s} "
                      f"expected=0x{fd.expected:X}  actual=0x{fd.value:X}  {match_str}\n")
                else:
                    w(f"    [{fd.msb:2d}:{fd.lsb:2d}] {fd.name:<16s} "
                      f"actual=0x{fd.value:X}  (not checked)\n")
        if txn.error_messages:
            w("  Errors:\n")
            for msg in txn.error_messages:
                w(f"    - {msg}\n")
        w("\n")
        self._file.flush()

    def _emit_write_field(self, txn: Transaction) -> None:
        w = self._file.write
        w(f"--- TXN #{txn.txn_id:03d} @ {txn.sim_time} {_SEPARATOR}\n")
        w(f"  Operation  : {txn.operation}\n")
        w(f"  Model Path : {txn.model_path}\n")
        w(f"  Address    : 0x{txn.address:08X}\n")
        w(f"  Field      : {txn.target_field}\n")
        w(f"  Field Value: 0x{txn.field_value:X}\n")
        w(f"  Full Write : 0x{txn.data:08X}  "
          f"(read 0x{txn.rmw_read_value:08X}, mask 0x{txn.rmw_mask:08X})\n")
        w(f"  Size       : {txn.size_bits}-bit\n")
        w(f"  Protocol   : {txn.protocol}\n")
        w(f"  Interface  : {txn.interface}\n")
        if txn.backdoor_path:
            w(f"  Backdoor   : {txn.backdoor_path}\n")
        safe_str = "SAFE" if txn.rmw_safe else "UNSAFE"
        if txn.rmw_reasons:
            safe_str += f" ({'; '.join(txn.rmw_reasons)})"
        elif txn.rmw_safe:
            safe_str += " (all neighbors are RW)"
        w(f"  RMW Safety : {safe_str}\n")
        w(f"  Status     : {txn.status}\n")
        w(f"  Mirror     : 0x{txn.mirror_before:08X} -> 0x{txn.mirror_after:08X}\n")
        if txn.substeps:
            w("  Bus traffic:\n")
            for sub in txn.substeps:
                w(f"    {_substep_summary(sub)}\n")
        w("\n")
        self._file.flush()
