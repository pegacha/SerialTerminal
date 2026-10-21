"""Docklight .ptp import.

The fixtures follow the layout of the sample projects Docklight V2.4 itself
saves (CRLF, cp1252, one value per line, a blank line after each block, two
empty CHANNELALIAS lines), with generic data. The meaning of each field is from
the Docklight V2.4 User Manual; see the module docstring of
serialterminal/utils/docklight_interpreter.py.
"""

import pytest
import yaml

from serialterminal.utils.docklight_interpreter import (
    DocklightConfigInterpreter,
    convert_docklight_config,
    parse_checksum,
)
from serialterminal.utils.payload import build_frame


def comm(port="COM4", baud="19200", parity="0", data_bits="4", stop_bits="0", mode="0"):
    return ["COMMSETTINGS", mode, port, "COM5", baud, parity, "63", data_bits, stop_bits, "0"]


def send(index, name, data, repeat="0", seconds="5", checksum=None):
    block = ["SEND", str(index), name, data, repeat, seconds]
    return block + ([f"CHECKSUM {checksum}"] if checksum else [])


def receive(index, name, data, answer=-1, comment=None, checksum=None):
    block = ["RECEIVE", str(index), name, data, str(answer), "1" if comment else "0",
             f"COMMENT {comment or ''}"]
    if checksum:
        return block + ["1", "1", "0", "1", f"CHECKSUM {checksum}", "0"]
    return block + ["0", "1", "0", "0"]


def ptp(*blocks, version="9"):
    """A project as Docklight writes it."""
    head = [["VERSION", version], comm(), ["COMMDISPLAY", "0"], ["VERSATAP", "0"],
            ["CHANNELALIAS", "", ""]]
    body = [b for b in blocks if b[0] != "COMMSETTINGS"]
    comms = [b for b in blocks if b[0] == "COMMSETTINGS"]
    if comms:
        head[1] = comms[0]
    lines = []
    for block in head + body:
        lines += block + [""]
    return "\r\n".join(lines) + "\r\n"


def load(tmp_path, *blocks, text=None, name="sample.ptp", version="9"):
    path = tmp_path / name
    path.write_bytes((text if text is not None else ptp(*blocks, version=version)).encode("cp1252"))
    interpreter = DocklightConfigInterpreter()
    return interpreter.parse_file(path), interpreter.problems


def problems_about(problems, word):
    return [p for p in problems if word in p]


# ----------------------------------------------------------------------------
# Communication settings
# ----------------------------------------------------------------------------

class TestCommSettings:
    def test_port_baud_and_line_settings(self, tmp_path):
        config, problems = load(tmp_path)
        assert config["serial"] == {"port": "COM4", "baud_rate": 19200, "parity": "E",
                                    "data_bits": "8", "stop_bits": "1"}
        assert problems == []

    @pytest.mark.parametrize("code,parity", [("0", "E"), ("1", "M"), ("2", "N"),
                                             ("3", "O"), ("4", "S")])
    def test_regression_parity_is_read(self, tmp_path, code, parity):
        """REGRESSION: parity was hard-coded to N, so an Even-parity Modbus
        project imported as no parity."""
        config, _ = load(tmp_path, comm(parity=code))
        assert config["serial"]["parity"] == parity

    def test_unknown_codes_are_reported_not_guessed(self, tmp_path):
        config, problems = load(tmp_path, comm(data_bits="3", stop_bits="2"))
        assert (config["serial"]["data_bits"], config["serial"]["stop_bits"]) == ("8", "1")
        assert problems_about(problems, "data bits") and problems_about(problems, "stop bits")

    def test_regression_version_7_numeric_port(self, tmp_path):
        """REGRESSION: VERSION 7 files store the COM number alone; it imported
        as no port."""
        config, _ = load(tmp_path, comm(port="3"), version="7")
        assert config["serial"]["port"] == "COM3"

    def test_version_7_port_names_block_wins(self, tmp_path):
        config, _ = load(tmp_path, comm(port="1"), ["COMMCHANNELS", "COM7", "COM2"], version="7")
        assert config["serial"]["port"] == "COM7"

    def test_tap_port_and_monitoring_mode_are_reported(self, tmp_path):
        config, problems = load(tmp_path, comm(port="VTP0", mode="1"))
        assert config["serial"]["port"] == "none"
        assert problems_about(problems, "Monitoring") and problems_about(problems, "VTP0")

    def test_non_numeric_baud(self, tmp_path):
        config, problems = load(tmp_path, comm(baud="None"))
        assert config["serial"]["baud_rate"] == 9600 and problems_about(problems, "Baud")


# ----------------------------------------------------------------------------
# Send sequences -> buttons
# ----------------------------------------------------------------------------

class TestButtons:
    def test_plain_send(self, tmp_path):
        config, problems = load(tmp_path, send(0, "Ping", "50 49 4E 47 0D 0A"))
        assert config["buttons"] == [{
            "id": "docklight-send-0", "label": "Ping", "message": "50 49 4E 47 0D 0A",
            "format": "hex", "tooltip": "Send Ping", "repeat": 0}]
        assert problems == []

    def test_repeat_seconds_become_milliseconds(self, tmp_path):
        config, _ = load(tmp_path, send(0, "Poll", "01", repeat="1", seconds=".06"))
        assert config["buttons"][0]["repeat"] == 60

    def test_interval_ignored_when_repeat_is_off(self, tmp_path):
        config, _ = load(tmp_path, send(0, "Poll", "01", repeat="0", seconds="1.5"))
        assert config["buttons"][0]["repeat"] == 0

    def test_regression_modbus_checksum_is_kept(self, tmp_path):
        """REGRESSION: CHECKSUM lines were ignored, so a Modbus button sent its
        00 00 placeholder instead of the CRC. Docklight writes the CRC over the
        placeholder; SerialTerminal appends it - same bytes on the wire."""
        config, problems = load(tmp_path, send(0, "Write register", "01 06 01 02 00 07 00 00",
                                               checksum="CRC-MODBUS L # little endian"))
        button = config["buttons"][0]
        assert (button["message"], button["checksum"]) == ("01 06 01 02 00 07", "crc16_modbus")
        assert build_frame(button["message"], "hex", button["checksum"]) == \
            bytes.fromhex("01 06 01 02 00 07 68 34")
        assert problems == []

    @pytest.mark.parametrize("spec,expected,size", [
        ("CRC-CCITT", "crc16_ccitt", 2),
        ("CRC:16,1021,FFFF,0000,No,No", "crc16_ccitt", 2),
        ("CRC:16,8005,FFFF,0000,Yes,Yes L", "crc16_modbus", 2),
        ("MOD256", "sum8", 1),
        ("XOR", "xor8", 1),
        ("LRC", "lrc8", 1),
        ("-MOD256", "lrc8", 1),
        ("(1, -3) CRC-MODBUS L @ -2", "crc16_modbus", 2),  # Docklight's defaults, spelled out
    ])
    def test_checksums_that_map(self, spec, expected, size):
        assert parse_checksum(f"CHECKSUM {spec} # comment") == (expected, size)

    @pytest.mark.parametrize("spec,reason", [
        ("CRC-MODBUS", "high byte first"),        # big endian: SerialTerminal's is low first
        ("CRC-CCITT L", "low byte first"),
        ("CRC-32", "isn't available"),
        ("LRC-ASCII", "isn't available"),
        ("MOD256 A", "ASCII"),
        ("(3, -3) CRC-MODBUS L", "not the whole frame"),
        ("CRC-MODBUS L @ -3", "not at the end"),
    ])
    def test_checksums_that_dont_map_leave_the_button_out(self, tmp_path, spec, reason):
        config, problems = load(tmp_path, send(0, "Frame", "01 02 03 00 00", checksum=spec))
        assert config["buttons"] == []
        assert problems_about(problems, reason)

    def test_parameter_wildcards_leave_the_button_out(self, tmp_path):
        config, problems = load(tmp_path, send(0, "Read slave ?", "?? 04 00 01 00 01"))
        assert config["buttons"] == [] and problems_about(problems, "parameters")

    def test_function_characters_leave_the_button_out(self, tmp_path):
        config, problems = load(tmp_path, send(0, "Toggle RTS", "!! 40 01 02"))
        assert config["buttons"] == [] and problems_about(problems, "function characters")

    def test_empty_name(self, tmp_path):
        config, _ = load(tmp_path, send(0, "", "01"), send(1, "Next", "02"))
        assert [b["label"] for b in config["buttons"]] == ["Send 0", "Next"]


# ----------------------------------------------------------------------------
# Receive sequences -> sequences
# ----------------------------------------------------------------------------

class TestSequences:
    def test_answer_and_comment(self, tmp_path):
        config, problems = load(tmp_path, send(0, "Pong", "50 4F 4E 47"),
                                receive(0, "Ping received", "50 49 4E 47", answer=0,
                                        comment='"Ping" received'))
        [sequence] = config["sequences"]
        assert sequence["receive"] == {"data": "50 49 4E 47", "format": "hex"}
        assert sequence["send"] == {"data": "50 4F 4E 47", "format": "hex"}
        assert sequence["comment"] == '"Ping" received'
        assert problems == []

    def test_answer_carries_the_buttons_checksum(self, tmp_path):
        config, _ = load(tmp_path, send(0, "Reply", "01 03 00 00", checksum="CRC-MODBUS L"),
                         receive(0, "Request", "01 03", answer=0))
        assert config["sequences"][0]["send"] == {"data": "01 03", "format": "hex",
                                                  "checksum": "crc16_modbus"}

    def test_answer_to_a_left_out_button_is_reported(self, tmp_path):
        config, problems = load(tmp_path, send(0, "Param", "?? 01"),
                                receive(0, "Request", "01 03", answer=0))
        assert config["sequences"][0]["send"]["data"] == ""
        assert problems_about(problems, "without its answer")

    def test_regression_hash_is_not_turned_into_question_mark(self, tmp_path):
        """REGRESSION: '##' (zero or one byte) became '??' (exactly one), so
        variable-length patterns stopped matching. At either end it changes
        nothing and is dropped; inside a pattern it can't be expressed."""
        config, problems = load(tmp_path, receive(0, "Ends", "## 06 0D 0A ## ##"),
                                receive(1, "Inside", "06 ## 0D 0A"))
        assert [s["receive"]["data"] for s in config["sequences"]] == ["06 0D 0A"]
        assert problems_about(problems, "Inside")

    @pytest.mark.parametrize("data", ["&& 02 01 03", "!! 01", "!! ^^ 01 01", "~~ 1B", "%% 01"])
    def test_regression_function_characters_leave_the_sequence_out(self, tmp_path, data):
        """REGRESSION: pauses, handshake signals and bit masks were copied into
        the pattern as if they were data."""
        config, problems = load(tmp_path, receive(0, "Special", data))
        assert config["sequences"] == [] and problems_about(problems, "function characters")

    def test_checksum_placeholders_match_any_value(self, tmp_path):
        config, problems = load(tmp_path, receive(0, "Answer", "?? 04 02 ?? ?? 00 00",
                                                  checksum="CRC-MODBUS L"))
        assert config["sequences"][0]["receive"]["data"] == "?? 04 02 ?? ?? ?? ??"
        assert problems_about(problems, "isn't checked")

    def test_comment_off_uses_the_name(self, tmp_path):
        config, _ = load(tmp_path, receive(0, "Notice", "07"))
        assert config["sequences"][0]["comment"] == "Notice"

    def test_comment_macros_become_readable(self, tmp_path):
        config, _ = load(tmp_path, receive(0, "Temp", "54 3D ?? ??",
                                           comment="%_L%_T New %_N = %_A(3, -1) %_H %_S"))
        assert config["sequences"][0]["comment"] == "New Temp = [VALUE] [VALUE]"

    def test_sequences_are_active(self, tmp_path):
        config, _ = load(tmp_path, receive(0, "A", "06"))
        assert config["sequences"][0]["active"] is True


# ----------------------------------------------------------------------------
# The result works in the app
# ----------------------------------------------------------------------------

@pytest.fixture
def modbus_project(tmp_path):
    return load(tmp_path,
                send(0, "Read register", "01 03 00 00 00 01 00 00", checksum="CRC-MODBUS L"),
                send(1, "Pong", "50 4F 4E 47", repeat="1", seconds="1"),
                receive(0, "Ping", "50 49 4E 47", answer=1, comment="ping"),
                receive(1, "Register answer", "01 03 02 ?? ?? 00 00", checksum="CRC-MODBUS L"))[0]


class TestImportedConfigIsUsable:
    def test_passes_the_app_validator(self, modbus_project):
        from serialterminal.ui.app import TUIApp
        assert TUIApp.validate_config(None, modbus_project) == (True, "")

    def test_sequences_compile_and_match(self, modbus_project):
        from serialterminal.sequence_handler import SequenceHandler

        handler = SequenceHandler(config_data=modbus_project["sequences"])
        assert handler.skipped == 0
        assert handler.check_data(bytes.fromhex("010302ABCD1234")).name == "Register answer"
        assert handler.check_data(b"xxPINGxx").name == "Ping"

    def test_no_ui_section(self, modbus_project):
        """The theme lives in settings.yml; an import used to add ui: nord."""
        assert "ui" not in modbus_project

    def test_round_trips_through_yaml(self, modbus_project, tmp_path):
        path = tmp_path / "out.yml"
        path.write_text(yaml.dump(modbus_project), encoding="utf-8")
        assert yaml.safe_load(path.read_text()) == modbus_project


class TestFileHandling:
    def test_empty_names_and_channel_aliases_do_not_break_blocks(self, tmp_path):
        """CHANNELALIAS is two (usually empty) lines, and a name can be empty:
        reading "until the blank line" ended those blocks early."""
        config, _ = load(tmp_path, send(0, "", "01"), receive(0, "", "02"))
        assert len(config["buttons"]) == 1 and len(config["sequences"]) == 1

    def test_lf_line_endings_and_utf8_also_read(self, tmp_path):
        text = ptp(send(0, "Configuração", "01")).replace("\r\n", "\n")
        path = tmp_path / "x.ptp"
        path.write_text(text, encoding="utf-8")
        config = DocklightConfigInterpreter().parse_file(path)
        assert config["buttons"][0]["label"] == "Configuração"

    def test_truncated_block_raises_rather_than_importing_partially(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, text="SEND\r\n0\r\n")

    def test_non_numeric_index_raises(self, tmp_path):
        with pytest.raises(ValueError):
            load(tmp_path, send("X", "Ping", "01"))

    def test_empty_file_yields_empty_config(self, tmp_path):
        config, problems = load(tmp_path, text="")
        assert config == {"buttons": [], "sequences": []} and problems == []


class TestConvertHelper:
    def test_writes_yaml_and_lists_problems(self, tmp_path, capsys):
        source = tmp_path / "in.ptp"
        source.write_bytes(ptp(send(0, "Ping", "50"), send(1, "Param", "??")).encode("cp1252"))
        target = tmp_path / "converted.yml"
        config = convert_docklight_config(str(source), str(target))
        assert yaml.safe_load(target.read_text())["buttons"] == config["buttons"]
        assert "Param" in capsys.readouterr().out


class TestImportInTheApp:
    async def test_problems_are_shown_after_importing(self, write_config, make_app,
                                                      isolated_cwd):
        from tests.conftest import MINIMAL_CONFIG
        write_config(MINIMAL_CONFIG)
        source = isolated_cwd / "bench.ptp"
        source.write_bytes(ptp(send(0, "Ping", "50"), send(1, "Param", "?? 01")).encode("cp1252"))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.import_config_file(source)
            for _ in range(40):
                await pilot.pause(0.05)
                if app.query("#docklight-send-0"):
                    break
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "Docklight import: 1 item(s) to check" in text
            assert "Button 'Param' not imported" in text
            assert app.query("#docklight-send-0")
            assert (isolated_cwd / "project.backup.yml").exists()
