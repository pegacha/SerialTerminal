"""Text-to-bytes conversion and frame assembly shared by every send path."""

import pytest

from serialterminal.utils.payload import build_frame, line_ending_bytes, parse_payload


class TestParsePayload:
    @pytest.mark.parametrize(
        "fmt,text,expected",
        [
            ("hex", "06 07", b"\x06\x07"),
            ("hex", "0x06 0X07", b"\x06\x07"),
            ("hex", "0607", b"\x06\x07"),
            ("hex", " 0a\t0B ", b"\x0a\x0b"),
            ("decimal", "6 7 255", b"\x06\x07\xff"),
            ("binary", "00000110 00000111", b"\x06\x07"),
            ("binary", "1010", b"\x0a"),  # short final group, as before
            ("ascii", "OK", b"OK"),
            ("mystery", "OK", b"OK"),  # unknown formats were always sent as ASCII
            ("hex", "", b""),
            ("ascii", "", b""),
        ],
    )
    def test_valid(self, fmt, text, expected):
        assert parse_payload(text, fmt) == expected

    @pytest.mark.parametrize(
        "fmt,text,message",
        [
            ("hex", "0G", "'G' is not a hex digit"),
            ("hex", "123", "odd number of hex digits"),
            ("decimal", "12 x", "'x' is not a number"),
            ("decimal", "256", "256 is out of range 0-255"),
            ("decimal", "-1", "'-1' is not a number"),
            ("decimal", "²", "'²' is not a number"),
            ("binary", "0102", "'2' is not a binary digit"),
            ("ascii", "café", "'é' is not ASCII"),
        ],
    )
    def test_invalid_reports_a_readable_reason(self, fmt, text, message):
        with pytest.raises(ValueError) as excinfo:
            parse_payload(text, fmt)
        assert str(excinfo.value) == message

    def test_non_string_config_values_are_accepted(self):
        """YAML turns an unquoted `data: 6` into an int."""
        assert parse_payload(6, "decimal") == b"\x06"


class TestBuildFrame:
    def test_checksum_then_line_ending(self):
        assert build_frame("AB", "ascii", "xor8", "crlf") == b"AB\x03\r\n"

    def test_checksum_covers_payload_only(self):
        assert build_frame("01 02", "hex", "sum8") == b"\x01\x02\x03"

    @pytest.mark.parametrize("fmt,text", [("hex", "41"), ("decimal", "65"), ("binary", "01000001")])
    def test_line_ending_never_touches_binary_formats(self, fmt, text):
        assert build_frame(text, fmt, line_ending="crlf") == b"A"

    @pytest.mark.parametrize("eol,expected", [("none", b""), ("cr", b"\r"), ("lf", b"\n"), ("crlf", b"\r\n")])
    def test_each_line_ending(self, eol, expected):
        assert build_frame("X", "ascii", line_ending=eol) == b"X" + expected

    def test_empty_ascii_with_eol_sends_just_the_terminator(self):
        assert build_frame("", "ascii", line_ending="crlf") == b"\r\n"

    def test_unknown_line_ending_rejected(self):
        with pytest.raises(ValueError, match="unknown line ending"):
            line_ending_bytes("crcrlf")
