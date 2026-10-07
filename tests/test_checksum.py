"""Checksum algorithms, pinned to published check values."""

import pytest

from serialterminal.utils.checksum import CHECKSUMS, checksum_bytes

CHECK_INPUT = b"123456789"


class TestCatalogueCheckValues:
    """The CRC catalogue's check value is the CRC of b"123456789"."""

    def test_crc16_modbus(self):
        # Check 0x4B37, sent low byte first.
        assert checksum_bytes(CHECK_INPUT, "crc16_modbus") == b"\x37\x4B"

    def test_crc16_ccitt_false(self):
        # Check 0x29B1, sent high byte first.
        assert checksum_bytes(CHECK_INPUT, "crc16_ccitt") == b"\x29\xB1"

    def test_modbus_frame_known_good(self):
        # Read holding registers, slave 1, addr 0, count 10: a textbook frame
        # whose CRC is C5 CD on the wire.
        assert checksum_bytes(bytes.fromhex("01030000000A"), "crc16_modbus") == b"\xC5\xCD"


class TestSimpleChecksums:
    def test_sum8_wraps(self):
        assert checksum_bytes(b"\xFF\x02", "sum8") == b"\x01"

    def test_xor8(self):
        assert checksum_bytes(b"\x01\x02\x04", "xor8") == b"\x07"

    @pytest.mark.parametrize("data", [b"", b"\x01", b"\x10\x20\x30", bytes(range(256))])
    def test_lrc8_makes_the_sum_zero(self, data):
        assert (sum(data) + checksum_bytes(data, "lrc8")[0]) & 0xFF == 0


class TestKinds:
    @pytest.mark.parametrize("kind", ["none", None, ""])
    def test_none_appends_nothing(self, kind):
        assert checksum_bytes(b"abc", kind) == b""

    def test_unknown_kind_is_a_value_error_naming_the_options(self):
        with pytest.raises(ValueError, match="crc16_modbus"):
            checksum_bytes(b"abc", "crc99")

    @pytest.mark.parametrize("kind", list(CHECKSUMS))
    def test_every_kind_handles_empty_input(self, kind):
        checksum_bytes(b"", kind)  # must not raise
