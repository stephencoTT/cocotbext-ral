"""Unit tests for TransactionLogger."""

import io
import unittest

from cocotbext.ral import RegisterModel, Register, RegisterField, SwAccess
from cocotbext.ral.transaction_logger import TransactionLogger, FieldDetail


class TestTransactionLogger(unittest.TestCase):

    def _make_model(self):
        model = RegisterModel("test")
        reg = Register("SCRATCH_0", address=0x100, size_bits=32, fields=[
            RegisterField("data", lsb=0, msb=31, reset_value=0, sw_access=SwAccess.RW),
        ])
        model.add_register(reg, "block.SCRATCH_0")
        return model, reg

    def test_write_header(self):
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        logger.write_header(
            ral_name="test_ral",
            protocol="axi",
            interface="tb.dut.master",
            model_name="test",
            register_count=10,
        )
        output = buf.getvalue()
        self.assertIn("REGISTER TRANSACTION LOG", output)
        self.assertIn("test_ral", output)
        self.assertIn("AXI", output)
        self.assertIn("tb.dut.master", output)
        self.assertIn("10 registers", output)

    def test_log_write(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        txn = logger.log_write(
            reg=reg,
            address=0x100,
            data=0xDEADBEEF,
            size_bits=32,
            protocol="axi",
            interface="tb.dut.master",
            mirror_before=0x0,
            mirror_after=0xDEADBEEF,
            fields=[FieldDetail("data", 0, 31, 0xDEADBEEF, previous=0x0)],
        )
        output = buf.getvalue()
        self.assertIn("TXN #001", output)
        self.assertIn("WRITE", output)
        self.assertIn("block.SCRATCH_0", output)
        self.assertIn("0x00000100", output.upper().replace("X", "x").replace("0X", "0x") or output)
        self.assertIn("DEADBEEF", output)
        self.assertIn("OK", output)
        self.assertEqual(txn.txn_id, 1)
        self.assertEqual(txn.operation, "WRITE")

    def test_log_read_pass(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        txn = logger.log_read(
            reg=reg,
            address=0x100,
            data=0xDEADBEEF,
            size_bits=32,
            protocol="axi",
            interface="tb.dut.master",
            mirror_value=0xDEADBEEF,
            expected_full=0xDEADBEEF,
            passed=True,
            checking_enabled=True,
            fields=[FieldDetail("data", 0, 31, 0xDEADBEEF, expected=0xDEADBEEF, matched=True)],
        )
        output = buf.getvalue()
        self.assertIn("READ", output)
        self.assertIn("PASS", output)
        self.assertEqual(txn.status.split()[0], "PASS")

    def test_log_read_fail(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        txn = logger.log_read(
            reg=reg,
            address=0x100,
            data=0xCAFEBABE,
            size_bits=32,
            protocol="axi",
            interface="tb.dut.master",
            mirror_value=0xDEADBEEF,
            expected_full=0xDEADBEEF,
            passed=False,
            checking_enabled=True,
            fields=[FieldDetail("data", 0, 31, 0xCAFEBABE, expected=0xDEADBEEF, matched=False)],
            error_messages=["block.SCRATCH_0.data: expected 0xDEADBEEF, got 0xCAFEBABE"],
        )
        output = buf.getvalue()
        self.assertIn("FAIL", output)
        self.assertIn("MISMATCH", output)

    def test_log_read_skip(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        txn = logger.log_read(
            reg=reg,
            address=0x100,
            data=0xAA,
            size_bits=32,
            protocol="axi",
            interface="tb.dut.master",
            mirror_value=0x0,
            expected_full=0x0,
            passed=None,
            checking_enabled=False,
        )
        output = buf.getvalue()
        self.assertIn("SKIP", output)

    def test_log_write_field(self):
        model, reg = self._make_model()
        field_obj = reg.fields[0]
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        txn = logger.log_write_field(
            reg=reg,
            field_obj=field_obj,
            field_value=0x42,
            full_write_value=0x42,
            rmw_read_value=0x0,
            size_bits=32,
            protocol="axi",
            interface="tb.dut.master",
            mirror_before=0x0,
            mirror_after=0x42,
            rmw_safe=True,
        )
        output = buf.getvalue()
        self.assertIn("WRITE_FIELD", output)
        self.assertIn("RMW", output)
        self.assertIn("SAFE", output)
        self.assertIn("data", output)

    def test_summary_counts(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        logger.log_write(reg=reg, address=0x100, data=0x1, size_bits=32,
                         protocol="axi", interface="m", mirror_before=0, mirror_after=1)
        logger.log_write(reg=reg, address=0x100, data=0x2, size_bits=32,
                         protocol="axi", interface="m", mirror_before=1, mirror_after=2)
        logger.log_read(reg=reg, address=0x100, data=0x2, size_bits=32,
                        protocol="axi", interface="m", mirror_value=2,
                        expected_full=2, passed=True, checking_enabled=True)
        logger.log_read(reg=reg, address=0x100, data=0xFF, size_bits=32,
                        protocol="axi", interface="m", mirror_value=2,
                        expected_full=2, passed=False, checking_enabled=True)
        logger.log_read(reg=reg, address=0x100, data=0x0, size_bits=32,
                        protocol="axi", interface="m", mirror_value=2,
                        expected_full=2, passed=None, checking_enabled=False)
        logger.write_summary()
        output = buf.getvalue()
        self.assertIn("Total      : 5", output)
        self.assertIn("Writes     : 2", output)
        self.assertIn("Reads      : 3", output)
        self.assertIn("Passed     : 1", output)
        self.assertIn("Failed     : 1", output)
        self.assertIn("Skipped    : 1", output)

    def test_backdoor_path_shown(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        logger.log_write(
            reg=reg, address=0x100, data=0x1, size_bits=32,
            protocol="axi", interface="m",
            mirror_before=0, mirror_after=1,
            backdoor_path="tb.dut.scratch_reg",
        )
        output = buf.getvalue()
        self.assertIn("Backdoor   : tb.dut.scratch_reg", output)

    def test_sequential_txn_ids(self):
        model, reg = self._make_model()
        buf = io.StringIO()
        logger = TransactionLogger(buf)
        t1 = logger.log_write(reg=reg, address=0x100, data=0x1, size_bits=32,
                              protocol="axi", interface="m", mirror_before=0, mirror_after=1)
        t2 = logger.log_read(reg=reg, address=0x100, data=0x1, size_bits=32,
                             protocol="axi", interface="m", mirror_value=1,
                             expected_full=1, passed=True, checking_enabled=True)
        t3 = logger.log_write(reg=reg, address=0x100, data=0x2, size_bits=32,
                              protocol="axi", interface="m", mirror_before=1, mirror_after=2)
        self.assertEqual(t1.txn_id, 1)
        self.assertEqual(t2.txn_id, 2)
        self.assertEqual(t3.txn_id, 3)

    def test_file_output(self):
        """Test writing to an actual file."""
        import tempfile
        import os
        model, reg = self._make_model()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            path = f.name
        try:
            logger = TransactionLogger(path)
            logger.write_header(ral_name="test", protocol="axi",
                                interface="m", model_name="test", register_count=1)
            logger.log_write(reg=reg, address=0x100, data=0xAB, size_bits=32,
                             protocol="axi", interface="m", mirror_before=0, mirror_after=0xAB)
            logger.write_summary()
            logger.close()
            with open(path) as f:
                content = f.read()
            self.assertIn("REGISTER TRANSACTION LOG", content)
            self.assertIn("TXN #001", content)
            self.assertIn("TRANSACTION SUMMARY", content)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
