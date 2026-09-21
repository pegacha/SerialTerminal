"""Docklight .ptp import.

CAVEAT: no real Docklight file was available when these were written, so the
fixtures below are reconstructed from the parser's own field layout. They are
characterization tests - they pin what the parser currently does and will catch
a regression, but they do not prove the layout matches real Docklight output.
Re-check them against a genuine .ptp before trusting the importer with one.
"""

import pytest
import yaml

from serialterminal.utils.docklight_interpreter import (
    DocklightConfigInterpreter,
    convert_docklight_config,
)

COMM_SECTION = """COMMSETTINGS
0
COM4
COM5
9600
pad1
pad2
pad3
pad4
pad5"""

SEND_PING = """SEND
0
Ping
50 49 4E 47 0D 0A
1
0.06"""

SEND_STATUS = """SEND
1
Status
3A 53 54 0D 0A
0
0"""

RECEIVE_ACK = """RECEIVE
0
Ack
06 ## 0D 0A
0
0
COMMENT Got an ack %_D(4,2)
flag1
flag2
flag3"""

RECEIVE_NO_REPLY = """RECEIVE
1
Notice
07 0D 0A
-1
0
flag1
flag2
flag3"""


def write_ptp(tmp_path, *sections, name="sample.ptp"):
    path = tmp_path / name
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def full_config(tmp_path):
    path = write_ptp(tmp_path, COMM_SECTION, SEND_PING, SEND_STATUS,
                     RECEIVE_ACK, RECEIVE_NO_REPLY)
    return DocklightConfigInterpreter().parse_file(path)


class TestCommSettings:
    def test_port_and_baud_extracted(self, full_config):
        assert full_config["serial"]["port"] == "COM4"
        assert full_config["serial"]["baud_rate"] == 9600

    def test_line_settings_default_to_8n1(self, full_config):
        """Docklight encodes these differently; the parser does not read them."""
        serial = full_config["serial"]
        assert (serial["parity"], serial["data_bits"], serial["stop_bits"]) == ("N", "8", "1")

    def test_non_com_port_becomes_none(self, tmp_path):
        section = COMM_SECTION.replace("COM4", "/dev/ttyUSB0")
        config = DocklightConfigInterpreter().parse_file(write_ptp(tmp_path, section))
        assert config["serial"]["port"] == "none"


class TestButtons:
    def test_all_sends_become_buttons(self, full_config):
        assert [b["label"] for b in full_config["buttons"]] == ["Ping", "Status"]

    def test_ids_are_unique_and_index_based(self, full_config):
        ids = [b["id"] for b in full_config["buttons"]]
        assert ids == ["docklight-send-0", "docklight-send-1"]
        assert len(set(ids)) == len(ids)

    def test_message_and_format_preserved(self, full_config):
        ping = full_config["buttons"][0]
        assert ping["message"] == "50 49 4E 47 0D 0A"
        assert ping["format"] == "hex"

    def test_repeat_seconds_become_milliseconds(self, full_config):
        assert full_config["buttons"][0]["repeat"] == 60

    def test_repeat_zero_when_disabled(self, full_config):
        assert full_config["buttons"][1]["repeat"] == 0

    def test_repeat_ignored_when_flag_off_despite_interval(self, tmp_path):
        section = SEND_STATUS.replace("0\n0", "0\n1.5")
        config = DocklightConfigInterpreter().parse_file(write_ptp(tmp_path, section))
        assert config["buttons"][0]["repeat"] == 0

    def test_non_numeric_interval_does_not_raise(self, tmp_path):
        section = SEND_PING.replace("0.06", "not-a-number")
        config = DocklightConfigInterpreter().parse_file(write_ptp(tmp_path, section))
        assert config["buttons"][0]["repeat"] == 0


class TestSequences:
    def test_all_receives_become_sequences(self, full_config):
        assert [s["name"] for s in full_config["sequences"]] == ["Ack", "Notice"]

    def test_hash_markers_convert_to_wildcards(self, full_config):
        assert full_config["sequences"][0]["receive"]["data"] == "06 ?? 0D 0A"

    def test_triggered_button_becomes_the_response(self, full_config):
        ack = full_config["sequences"][0]
        assert ack["send"]["data"] == full_config["buttons"][0]["message"]

    def test_negative_trigger_means_no_response(self, full_config):
        assert full_config["sequences"][1]["send"]["data"] == ""

    def test_out_of_range_trigger_means_no_response(self, tmp_path):
        section = RECEIVE_ACK.replace("06 ## 0D 0A\n0", "06 ## 0D 0A\n99")
        config = DocklightConfigInterpreter().parse_file(write_ptp(tmp_path, section))
        assert config["sequences"][0]["send"]["data"] == ""

    def test_comment_is_captured(self, full_config):
        assert full_config["sequences"][0]["comment"].startswith("Got an ack")

    def test_docklight_placeholders_are_replaced(self, full_config):
        comment = full_config["sequences"][0]["comment"]
        assert "%_D" not in comment
        assert "[VALUE]" in comment

    def test_comment_falls_back_to_name(self, full_config):
        assert full_config["sequences"][1]["comment"] == "Notice"

    def test_sequences_are_active_by_default(self, full_config):
        assert all(s["active"] for s in full_config["sequences"])


class TestImportedConfigIsUsable:
    def test_output_passes_the_app_validator(self, full_config):
        from serialterminal.ui.app import TUIApp

        is_valid, error = TUIApp.validate_config(None, full_config)
        assert is_valid, error

    def test_sequences_compile_and_match(self, full_config):
        from serialterminal.sequence_handler import SequenceHandler

        handler = SequenceHandler(config_data=full_config["sequences"])
        assert handler.skipped == 0
        assert handler.check_data(bytes.fromhex("06FF0D0A")).name == "Ack"

    def test_buttons_round_trip_through_yaml(self, full_config, tmp_path):
        path = tmp_path / "out.yml"
        path.write_text(yaml.dump(full_config), encoding="utf-8")
        assert yaml.safe_load(path.read_text()) == full_config


class TestMalformedFiles:
    def test_truncated_section_raises_rather_than_importing_partially(self, tmp_path):
        """The parser indexes fixed offsets with no bounds checking. A truncated
        file must fail outright - the caller discards the result - rather than
        yielding a half-built config."""
        path = write_ptp(tmp_path, "SEND\n0\nPing")
        with pytest.raises(IndexError):
            DocklightConfigInterpreter().parse_file(path)

    def test_non_numeric_index_raises(self, tmp_path):
        path = write_ptp(tmp_path, SEND_PING.replace("SEND\n0", "SEND\nX"))
        with pytest.raises(ValueError):
            DocklightConfigInterpreter().parse_file(path)

    def test_empty_file_yields_empty_config(self, tmp_path):
        config = DocklightConfigInterpreter().parse_file(write_ptp(tmp_path, ""))
        assert config["buttons"] == []
        assert config["sequences"] == []


class TestConvertHelper:
    def test_writes_yaml_to_the_requested_path(self, tmp_path, capsys):
        source = write_ptp(tmp_path, COMM_SECTION, SEND_PING)
        target = tmp_path / "converted.yml"
        config = convert_docklight_config(str(source), str(target))
        assert target.exists()
        assert yaml.safe_load(target.read_text())["buttons"] == config["buttons"]
