"""Unit tests for volatile policy helpers."""

import unittest

from cocotbext.ral import RegisterField, SwAccess
from cocotbext.ral.state import FieldState
from cocotbext.ral.volatile_policy import (
    is_field_volatile,
    check_allowed,
    VolatileMixin,
)


class TestVolatileFunctions(unittest.TestCase):

    def test_rw_field_not_volatile_by_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW)
        self.assertFalse(is_field_volatile(f))

    def test_ro_field_volatile_by_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RO)
        self.assertTrue(is_field_volatile(f))

    def test_explicit_volatile_overrides_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW, volatile=True)
        self.assertTrue(is_field_volatile(f))

    def test_explicit_non_volatile_overrides_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RO, volatile=False)
        self.assertFalse(is_field_volatile(f))

    def test_rclr_field_volatile_by_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RCLR)
        self.assertTrue(is_field_volatile(f))

    def test_rset_field_volatile_by_default(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RSET)
        self.assertTrue(is_field_volatile(f))

    def test_check_allowed_non_volatile_enabled(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW)
        state = FieldState(mirrored=0, desired=0, check_enabled=True)
        self.assertTrue(check_allowed(f, state))

    def test_check_allowed_volatile_disabled(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW, volatile=True)
        state = FieldState(mirrored=0, desired=0, check_enabled=True)
        self.assertFalse(check_allowed(f, state))

    def test_check_allowed_non_volatile_disabled(self):
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW)
        state = FieldState(mirrored=0, desired=0, check_enabled=False)
        self.assertFalse(check_allowed(f, state))


class TestVolatileMixin(unittest.TestCase):

    def test_mixin_delegates_to_functions(self):
        mixin = VolatileMixin()
        f_rw = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW)
        f_ro = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RO)
        self.assertFalse(mixin.is_volatile(f_rw))
        self.assertTrue(mixin.is_volatile(f_ro))

    def test_mixin_check_allowed(self):
        mixin = VolatileMixin()
        f = RegisterField("f", lsb=0, msb=7, sw_access=SwAccess.RW)
        state = FieldState(mirrored=0, desired=0, check_enabled=True)
        self.assertTrue(mixin.check_allowed(f, state))


if __name__ == "__main__":
    unittest.main()
