"""Log line formatting for each notation."""

import re

import pytest

from utils.formatting import (
    format_log_message,
    format_log_message_ascii,
    format_log_message_binary,
    format_log_message_decimal,
    format_log_message_hex,
    timestamp,
)

ALL_FORMATTERS = [
    format_log_message,
    format_log_message_ascii,
    format_log_message_hex,
    format_log_message_decimal,
    format_log_message_binary,
]

STAMP = "12:34:56.789"


def test_timestamp_shape():
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}\.\d{3}", timestamp())


@pytest.mark.parametrize("formatter", ALL_FORMATTERS)
def test_supplied_stamp_is_used_verbatim(formatter):
    """REGRESSION: each formatter called datetime.now() itself, so one frame
    was stamped four times and the tabs disagreed about when it arrived."""
    assert formatter(b"\x41", STAMP).startswith("[" + STAMP + "] ")


@pytest.mark.parametrize("formatter", ALL_FORMATTERS)
def test_stamp_is_generated_when_omitted(formatter):
    assert re.match(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\] ", formatter(b"\x41"))


@pytest.mark.parametrize("formatter", ALL_FORMATTERS)
def test_str_input_passes_through(formatter):
    assert formatter("hello", STAMP) == "[" + STAMP + "] hello"


@pytest.mark.parametrize("formatter", ALL_FORMATTERS)
def test_empty_bytes_do_not_raise(formatter):
    assert formatter(b"", STAMP).startswith("[" + STAMP + "]")


class TestHex:
    def test_uppercase_space_separated_pairs(self):
        assert format_log_message_hex(b"\x00\x0a\xff", STAMP) == "[" + STAMP + "] 00 0A FF"


class TestDecimal:
    def test_space_separated_decimal(self):
        assert format_log_message_decimal(b"\x00\x0a\xff", STAMP) == "[" + STAMP + "] 0 10 255"


class TestBinary:
    def test_zero_padded_octets(self):
        assert format_log_message_binary(b"\x00\x06", STAMP) == "[" + STAMP + "] 00000000 00000110"


class TestAscii:
    def test_printable_characters_pass_through(self):
        assert format_log_message_ascii(b"OK", STAMP) == "[" + STAMP + "] OK"

    @pytest.mark.parametrize(
        "byte,name",
        [(0x00, "<NUL>"), (0x02, "<STX>"), (0x03, "<ETX>"), (0x06, "<ACK>"),
         (0x15, "<NAK>"), (0x1B, "<ESC>"), (0x7F, "<DEL>")],
    )
    def test_control_characters_are_named(self, byte, name):
        assert name in format_log_message_ascii(bytes([byte]), STAMP)

    def test_high_bytes_shown_as_escapes(self):
        assert "\\xff" in format_log_message_ascii(b"\xff", STAMP)

    def test_crlf_splits_into_continuation_lines(self):
        out = format_log_message_ascii(b"A\r\nB", STAMP)
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0] == "[" + STAMP + "] A"
        assert lines[1].strip() == "B"
        assert STAMP not in lines[1], "continuation lines are indented, not restamped"

    def test_bare_lf_also_splits(self):
        assert len(format_log_message_ascii(b"A\nB", STAMP).split("\n")) == 2


class TestGenericFormatter:
    def test_bytes_render_as_bare_hex(self):
        assert format_log_message(b"\x0a\xff", STAMP) == "[" + STAMP + "] 0aff"
