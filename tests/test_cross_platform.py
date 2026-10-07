"""Behaviour that differs between Windows, macOS and Linux.

CI runs the whole suite on all three; these tests pin the platform-specific
branches by simulating each platform, so they're exercised everywhere.
"""

from pathlib import Path

import pytest
import serial
import yaml

from serialterminal import path_setup
from serialterminal.ui.app import connection_hint
from serialterminal.utils.docklight_interpreter import DocklightConfigInterpreter
from tests.conftest import MINIMAL_CONFIG


class TestConnectionHints:
    def test_linux_permission_denied_explains_the_dialout_group(self):
        error = serial.SerialException(13, "could not open port /dev/ttyUSB0: [Errno 13] Permission denied")
        hint = connection_hint(error, platform="linux")
        assert "dialout" in hint and "uucp" in hint

    def test_macos_busy_port_mentions_cu_devices(self):
        error = serial.SerialException(16, "could not open port /dev/tty.usbserial: [Errno 16] Resource busy")
        assert "/dev/cu." in connection_hint(error, platform="darwin")

    def test_windows_access_denied_means_port_in_use(self):
        error = serial.SerialException("could not open port 'COM4': PermissionError(13, 'Access is denied.', None, 5)")
        assert "another program" in connection_hint(error, platform="win32")

    @pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
    def test_vanished_port(self, platform):
        error = serial.SerialException("could not open port /dev/ttyUSB9: [Errno 2] No such file or directory")
        assert "Refresh" in connection_hint(error, platform=platform)

    def test_unrecognised_errors_get_no_guess(self):
        assert connection_hint(serial.SerialException("something else"), platform="linux") is None

    async def test_hint_is_logged_on_a_failed_connect(self, write_config, make_app, monkeypatch):
        from textual.widgets import Select

        write_config(MINIMAL_CONFIG)
        app = make_app()

        def refuse(*args, **kwargs):
            raise serial.SerialException(13, "could not open port /dev/ttyUSB0: Permission denied")

        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one("#serial-port-select", Select)
            select.set_options([("No port", "none"), ("/dev/ttyUSB0", "/dev/ttyUSB0")])
            select.value = "/dev/ttyUSB0"
            monkeypatch.setattr(app.serial_conn, "connect", refuse)
            monkeypatch.setattr("sys.platform", "linux")
            app._connect_serial()
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "Permission denied" in text and "dialout" in text


class TestStateFileLocation:
    def test_macos_uses_application_support(self, monkeypatch, tmp_path):
        monkeypatch.setattr(path_setup.sys, "platform", "darwin")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert path_setup._state_file() == (
            tmp_path / "Library" / "Application Support" / "SerialTerminal" / "state.yml")

    def test_linux_follows_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setattr(path_setup.sys, "platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        assert path_setup._state_file() == tmp_path / "state" / "serialterminal" / "state.yml"

    def test_windows_uses_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(path_setup.sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert path_setup._state_file() == tmp_path / "SerialTerminal" / "state.yml"


class TestEncodings:
    PTP = "SEND\n0\n{label}\n50 49 4E 47\n0\n0\n"

    def test_regression_windows_ansi_ptp_imports_everywhere(self, tmp_path):
        """REGRESSION: .ptp files are written in the Windows ANSI code page;
        reading them with the platform default raised UnicodeDecodeError on
        macOS and Linux as soon as a label had an accent."""
        path = tmp_path / "pt.ptp"
        path.write_bytes(self.PTP.format(label="Configuração").encode("cp1252"))
        config = DocklightConfigInterpreter().parse_file(path)
        assert config["buttons"][0]["label"] == "Configuração"

    def test_utf8_ptp_still_imports(self, tmp_path):
        path = tmp_path / "pt.ptp"
        path.write_text(self.PTP.format(label="Configuração"), encoding="utf-8")
        assert DocklightConfigInterpreter().parse_file(path)["buttons"][0]["label"] == "Configuração"

    async def test_non_ascii_labels_survive_a_save(self, write_config, make_app, isolated_cwd):
        config = dict(MINIMAL_CONFIG, buttons=[{"id": "c", "label": "Ação µs", "message": "X"}])
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.save_config()
        reloaded = yaml.safe_load((isolated_cwd / "project.yml").read_text(encoding="utf-8"))
        assert reloaded["buttons"][0]["label"] == "Ação µs"


class TestKeys:
    async def test_regression_import_has_a_key_terminals_can_send(self, write_config, make_app):
        """REGRESSION: Ctrl+I and Tab are the same byte (0x09) in a terminal, so
        on macOS and Linux Ctrl+I moved focus instead of importing."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+t")
            await pilot.pause(0.3)
            assert type(app.screen).__name__ == "CompactFileOpen"

    def test_no_binding_relies_on_a_key_terminals_conflate(self):
        """Ctrl+I = Tab, Ctrl+M = Enter, Ctrl+[ = Esc, Ctrl+H = Backspace on
        most terminals - none may be a binding's only key."""
        from serialterminal.ui.app import TUIApp

        conflated = {"ctrl+i", "ctrl+m", "ctrl+left_square_bracket", "ctrl+h"}
        for binding in TUIApp.BINDINGS:
            keys = {k.strip() for k in binding.key.split(",")}
            assert keys - conflated, f"{binding.action} is only reachable via {keys}"
