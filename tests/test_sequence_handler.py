"""Sequence pattern compilation and matching.

Tests marked REGRESSION pin behaviour that was broken before the Phase 1 fixes,
so it is clear why they exist.
"""

import pytest
import yaml

from serialterminal.sequence_handler import ANY_BYTE, ReceiveSequence, SequenceHandler


def seq(**overrides):
    """A minimal valid sequence config, overridable per test."""
    config = {
        "name": "test",
        "receive": {"data": "06", "format": "hex"},
        "send": {"data": "06", "format": "hex"},
    }
    config.update(overrides)
    return ReceiveSequence(config)


class TestHexPatterns:
    def test_exact_bytes_match(self):
        pattern = seq(receive={"data": "3A 41 0D 0A", "format": "hex"})
        assert pattern.matches(bytes.fromhex("3A410D0A"))

    def test_non_matching_bytes_rejected(self):
        pattern = seq(receive={"data": "3A 41", "format": "hex"})
        assert not pattern.matches(bytes.fromhex("3A42"))

    @pytest.mark.parametrize("middle", ["41", "00", "FF", "0A", "0D"])
    def test_wildcard_matches_any_byte(self, middle):
        """?? must cover the whole 0x00-0xFF range, CR and LF included."""
        pattern = seq(receive={"data": "3A ?? 0D 0A", "format": "hex"})
        assert pattern.matches(bytes.fromhex("3A" + middle + "0D0A"))

    def test_matching_is_a_substring_search(self):
        pattern = seq(receive={"data": "0D 0A", "format": "hex"})
        assert pattern.matches(bytes.fromhex("AABB0D0A"))

    def test_lowercase_hex_accepted(self):
        pattern = seq(receive={"data": "3a 0d", "format": "hex"})
        assert pattern.matches(bytes.fromhex("3A0D"))


class TestAsciiPatterns:
    def test_regression_metacharacters_are_literal(self):
        """REGRESSION: the pattern reached re unescaped, so a trailing '$'
        anchored and the sequence matched nothing at all."""
        pattern = seq(
            receive={"data": "PRICE $1.00", "format": "ascii"},
            send={"data": "OK", "format": "ascii"},
        )
        assert pattern.matches(b"PRICE $1.00")

    def test_regression_dot_is_not_a_wildcard(self):
        """REGRESSION: an unescaped '.' in the payload matched any character."""
        pattern = seq(
            receive={"data": "PRICE $1.00", "format": "ascii"},
            send={"data": "OK", "format": "ascii"},
        )
        assert not pattern.matches(b"PRICE $1X00")

    def test_wildcard_still_works(self):
        pattern = seq(
            receive={"data": "ID??", "format": "ascii"},
            send={"data": "OK", "format": "ascii"},
        )
        assert pattern.matches(b"ID7")
        assert pattern.matches(b"IDx")

    @pytest.mark.parametrize("meta", ["*", "+", "(", "[", "|", "^", "\\"])
    def test_other_metacharacters_survive(self, meta):
        pattern = seq(
            receive={"data": "A" + meta + "B", "format": "ascii"},
            send={"data": "", "format": "ascii"},
        )
        assert pattern.matches(("A" + meta + "B").encode("ascii"))


class TestDecimalAndBinaryPatterns:
    def test_decimal_exact(self):
        pattern = seq(receive={"data": "58 65 13 10", "format": "decimal"})
        assert pattern.matches(bytes([58, 65, 13, 10]))

    def test_decimal_wildcard(self):
        pattern = seq(receive={"data": "58 ?? 13", "format": "decimal"})
        assert pattern.matches(bytes([58, 200, 13]))

    def test_binary_exact(self):
        pattern = seq(receive={"data": "00111010 01000001", "format": "binary"})
        assert pattern.matches(bytes([0x3A, 0x41]))

    def test_binary_wildcard(self):
        pattern = seq(receive={"data": "00111010 ????????", "format": "binary"})
        assert pattern.matches(bytes([0x3A, 0x99]))


class TestMalformedInput:
    def test_regression_null_delay_does_not_raise(self):
        """REGRESSION: `delay:` with no value is None in YAML and crashed the
        ms-to-seconds divide, taking the whole sequence list down with it."""
        assert seq(delay=None).delay == 0.0

    @pytest.mark.parametrize(
        "raw,expected",
        [(None, 0.0), ("", 0.0), (0, 0.0), (500, 0.5), ("500", 0.5), (1500, 1.5)],
    )
    def test_delay_coercion(self, raw, expected):
        assert seq(delay=raw).delay == expected

    def test_nonsense_delay_falls_back_to_zero(self):
        assert seq(delay="soon").delay == 0.0

    def test_negative_delay_clamped(self):
        assert seq(delay=-100).delay == 0.0

    def test_unknown_format_yields_no_pattern(self):
        pattern = seq(receive={"data": "06", "format": "octal"})
        assert pattern.pattern is None
        assert not pattern.matches(b"\x06")

    def test_uncompilable_pattern_does_not_raise(self):
        pattern = seq(receive={"data": "ZZ", "format": "hex"})
        assert pattern.pattern is None
        assert not pattern.matches(b"\x00")

    def test_missing_receive_section_does_not_raise(self):
        pattern = ReceiveSequence({"name": "bare"})
        assert not pattern.matches(b"anything")


class TestActiveFlag:
    def test_inactive_sequence_never_matches(self):
        assert not seq(active=False).matches(b"\x06")

    def test_active_defaults_true(self):
        assert seq().active is True


class TestResponseBytes:
    @pytest.mark.parametrize(
        "fmt,data,expected",
        [
            ("hex", "06 07", b"\x06\x07"),
            ("hex", "0x06", b"\x06"),
            ("decimal", "6 7", b"\x06\x07"),
            ("binary", "00000110", b"\x06"),
            ("ascii", "OK", b"OK"),
        ],
    )
    def test_formats(self, fmt, data, expected):
        assert seq(send={"data": data, "format": fmt}).get_response_bytes() == expected

    def test_bad_response_returns_empty_rather_than_raising(self):
        assert seq(send={"data": "ZZ", "format": "hex"}).get_response_bytes() == b""

    def test_checksum_appended_to_response(self):
        send = {"data": "01 03 00 00 00 0A", "format": "hex", "checksum": "crc16_modbus"}
        assert seq(send=send).get_response_bytes() == bytes.fromhex("01030000000AC5CD")

    def test_line_ending_appended_to_ascii_response(self):
        send = {"data": "OK", "format": "ascii", "line_ending": "crlf"}
        assert seq(send=send).get_response_bytes() == b"OK\r\n"

    def test_unknown_checksum_gives_empty_response_not_a_crash(self):
        send = {"data": "06", "format": "hex", "checksum": "crc99"}
        assert seq(send=send).get_response_bytes() == b""


class TestSequenceHandler:
    def test_regression_one_bad_entry_keeps_the_rest(self):
        """REGRESSION: the whole load loop sat inside a single try, so one
        malformed entry discarded every sequence defined after it."""
        handler = SequenceHandler(
            config_data=[
                {
                    "name": "bad",
                    "delay": object(),
                    "receive": {"data": "06", "format": "hex"},
                },
                {
                    "name": "good",
                    "receive": {"data": "07", "format": "hex"},
                    "send": {"data": "07", "format": "hex"},
                },
            ]
        )
        assert [s.name for s in handler.sequences] == ["bad", "good"]

    def test_non_dict_entries_are_skipped_and_counted(self):
        handler = SequenceHandler(
            config_data=[
                {"name": "ok", "receive": {"data": "06", "format": "hex"}},
                "garbage",
                None,
            ]
        )
        assert len(handler.sequences) == 1
        assert handler.skipped == 2

    def test_non_list_section_is_reported(self):
        handler = SequenceHandler(config_data={"not": "a list"})
        assert handler.sequences == []
        assert handler.skipped == 1

    def test_empty_config_is_not_an_error(self):
        handler = SequenceHandler(config_data=[])
        assert handler.sequences == []
        assert handler.skipped == 0

    def test_check_data_returns_first_active_match(self):
        handler = SequenceHandler(
            config_data=[
                {
                    "name": "off",
                    "active": False,
                    "receive": {"data": "06", "format": "hex"},
                    "send": {"data": "01", "format": "hex"},
                },
                {
                    "name": "on",
                    "receive": {"data": "06", "format": "hex"},
                    "send": {"data": "02", "format": "hex"},
                },
            ]
        )
        assert handler.check_data(b"\x06").name == "on"

    def test_check_data_returns_none_when_nothing_matches(self):
        handler = SequenceHandler(
            config_data=[{"name": "a", "receive": {"data": "06", "format": "hex"}}]
        )
        assert handler.check_data(b"\xff") is None

    def test_get_active_sequences_filters_inactive(self):
        handler = SequenceHandler(
            config_data=[
                {"name": "on", "receive": {"data": "06", "format": "hex"}},
                {"name": "off", "active": False, "receive": {"data": "07", "format": "hex"}},
            ]
        )
        assert [s.name for s in handler.get_active_sequences()] == ["on"]

    def test_toggle_sequence(self):
        handler = SequenceHandler(
            config_data=[{"name": "a", "receive": {"data": "06", "format": "hex"}}]
        )
        assert handler.toggle_sequence("a") is False
        assert handler.toggle_sequence("a") is True
        assert handler.toggle_sequence("missing") is False

    def test_reload_replaces_previous_sequences(self):
        handler = SequenceHandler(
            config_data=[{"name": "first", "receive": {"data": "06", "format": "hex"}}]
        )
        handler.reload_sequences(
            [{"name": "second", "receive": {"data": "07", "format": "hex"}}]
        )
        assert [s.name for s in handler.sequences] == ["second"]

    def test_loads_from_yaml_file(self, tmp_path):
        path = tmp_path / "seq.yml"
        path.write_text(
            yaml.dump(
                {
                    "sequences": [
                        {
                            "name": "from-file",
                            "receive": {"data": "06", "format": "hex"},
                            "send": {"data": "06", "format": "hex"},
                        }
                    ]
                }
            )
        )
        handler = SequenceHandler(config_path=str(path))
        assert [s.name for s in handler.sequences] == ["from-file"]

    def test_file_loading_also_isolates_bad_entries(self, tmp_path):
        path = tmp_path / "seq.yml"
        path.write_text(
            yaml.dump(
                {
                    "sequences": [
                        "garbage",
                        {"name": "good", "receive": {"data": "06", "format": "hex"}},
                    ]
                }
            )
        )
        handler = SequenceHandler(config_path=str(path))
        assert [s.name for s in handler.sequences] == ["good"]
        assert handler.skipped == 1

    def test_missing_file_is_not_an_error(self, tmp_path):
        handler = SequenceHandler(config_path=str(tmp_path / "nope.yml"))
        assert handler.sequences == []

    def test_unreadable_file_is_not_an_error(self, tmp_path):
        path = tmp_path / "bad.yml"
        path.write_text("{[not valid yaml")
        handler = SequenceHandler(config_path=str(path))
        assert handler.sequences == []


def test_any_byte_constant_is_a_character_class():
    """Guards the escaping that a shell heredoc once mangled into a real NUL."""
    assert ANY_BYTE == r"[\x00-\xFF]"
    assert "\x00" not in ANY_BYTE
