"""Control-character shortcuts (Settings > Keyboard) and <CR>-style names."""

import pytest
import yaml
from textual.widgets import DataTable, Input, Select, TextArea

from serialterminal.sequence_handler import SequenceHandler
from serialterminal.ui.control_keys import (
    DEFAULT_SHORTCUTS, ControlKeysScreen, KeyCaptureScreen, clean_shortcuts, pretty_key,
    reserved_keys, shortcut_problem,
)
from serialterminal.utils.payload import control_text, expand_control_names
from tests.conftest import MINIMAL_CONFIG
from tests.test_connection_flow import FakePort, install, offer_ports


class TestNames:
    def test_expand(self):
        assert expand_control_names("AT<CR><lf>") == "AT\r\n"
        assert expand_control_names("<STX>1<ETX>") == "\x021\x03"

    def test_other_brackets_are_kept(self):
        assert expand_control_names("<HTML> a<b") == "<HTML> a<b"

    @pytest.mark.parametrize("fmt,text", [("ascii", "<CR>"), ("hex", "0D"),
                                          ("decimal", "13"), ("binary", "00001101")])
    def test_control_text(self, fmt, text):
        assert control_text(13, fmt) == text

    def test_ascii_receive_pattern_understands_names(self):
        handler = SequenceHandler(config_data=[{
            "name": "ok", "receive": {"data": "OK<CR>??", "format": "ascii"},
            "send": {"data": "", "format": "hex"}}])
        assert handler.skipped == 0
        assert handler.check_data(b"xOK\rZ") is not None
        assert handler.check_data(b"OK<CR>Z") is None


class TestRules:
    RESERVED = {"ctrl+w", "ctrl+c", "enter", "f2"}

    @pytest.mark.parametrize("key", ["ctrl+enter", "ctrl+shift+enter", "alt+x", "f5",
                                     "ctrl+shift+2", "super+enter"])  # super = Cmd on a Mac
    def test_allowed(self, key):
        assert shortcut_problem(key, 2, {}, self.RESERVED) is None

    @pytest.mark.parametrize("key,why", [("x", "types text"), ("shift+x", "types text"),
                                         ("ctrl+w", "already used"), ("f2", "already used")])
    def test_refused(self, key, why):
        assert why in shortcut_problem(key, 2, {}, self.RESERVED)

    def test_one_key_one_character(self):
        assert "already types <CR>" in shortcut_problem("f5", 10, {13: "f5"}, set())
        assert shortcut_problem("f5", 13, {13: "f5"}, set()) is None  # re-assigning its own

    def test_app_and_text_editing_keys_are_reserved(self):
        from serialterminal.ui.app import TUIApp
        reserved = reserved_keys(TUIApp())
        for key in ("ctrl+q", "ctrl+w", "ctrl+f", "f2", "ctrl+c", "ctrl+v", "ctrl+z", "ctrl+a",
                    "ctrl+p", "ctrl+m", "enter", "tab"):
            assert key in reserved, key
        for key in DEFAULT_SHORTCUTS.values():
            assert key not in reserved, key

    def test_settings_values(self):
        assert clean_shortcuts(None) == DEFAULT_SHORTCUTS
        assert clean_shortcuts({}) == {}, "an empty map means no shortcuts"
        assert clean_shortcuts({"13": "f6", 99: "f7", "x": "f8", 2: "", 3: "f6"}) == {13: "f6"}

    def test_pretty(self):
        assert pretty_key("ctrl+shift+enter") == "Ctrl+Shift+Enter"


async def focus_send_box(app, pilot, fmt="ascii"):
    await pilot.pause()
    app.query_one("#send-format-select", Select).value = fmt
    await pilot.click("#quick-send-input")
    return app.query_one("#quick-send-input", Input)


class TestSendCommand:
    async def test_defaults_insert_cr_and_lf(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            box = await focus_send_box(app, pilot)
            await pilot.press(*"AT", "ctrl+enter", "ctrl+shift+enter")
            assert box.value == "AT<CR><LF>"
            assert app.query_one("QuickSend").border_subtitle == "", "valid"

    @pytest.mark.parametrize("fmt,before,after", [("hex", "41", "41 0D "),
                                                  ("decimal", "65 ", "65 13 "),
                                                  ("binary", "", "00001101 ")])
    async def test_numeric_notations(self, write_config, make_app, fmt, before, after):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            box = await focus_send_box(app, pilot, fmt)
            box.value, box.cursor_position = before, len(before)
            await pilot.press("ctrl+enter")
            assert box.value == after

    async def test_names_are_sent_as_control_characters(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            box = await focus_send_box(app, pilot)
            box.value = "AT<CR><LF>"
            await pilot.press("enter")
            await pilot.pause()
            assert port.written[-1] == b"AT\r\n"

    async def test_no_shortcuts_configured(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        (isolated_cwd / "settings.yml").write_text(yaml.dump({"control_shortcuts": {}}))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            box = await focus_send_box(app, pilot)
            await pilot.press("ctrl+enter")
            assert box.value == ""


class TestButtonEditor:
    async def test_sequence_and_auto_send_fields(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            sequence = app.screen.query_one("#ed-sequence", TextArea)
            sequence.focus()
            await pilot.press(*"OK", "ctrl+enter")
            assert sequence.text == "OK<CR>"
            from textual.widgets import Checkbox
            app.screen.query_one("#ed-auto", Checkbox).value = True  # enables the field
            await pilot.pause()
            auto = app.screen.query_one("#ed-auto-data", Input)
            auto.focus()
            await pilot.pause()
            await pilot.press(*"06", "ctrl+shift+enter")
            assert auto.value == "06 0A ", "the auto-send pattern is HEX by default"


class TestSettingsScreen:
    async def open(self, app, pilot, row):
        await pilot.press("f2")
        await pilot.pause(0.2)
        await pilot.click("#settings-control-keys")
        await pilot.pause(0.3)
        assert isinstance(app.screen, ControlKeysScreen)
        app.screen.query_one(DataTable).move_cursor(row=row)
        return app.screen

    async def capture(self, pilot, *keys):
        await pilot.press("enter")
        await pilot.pause(0.2)
        await pilot.press(*keys)
        await pilot.pause(0.2)

    async def test_assign_refuse_clear_and_reset(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = await self.open(app, pilot, row=2)
            assert screen.query_one(DataTable).row_count == 32

            await self.capture(pilot, "ctrl+w")
            assert "already used" in str(screen.query_one("#control-keys-status").render())
            assert 2 not in app.control_shortcuts()

            await self.capture(pilot, "f5")
            assert app.control_shortcuts()[2] == "f5"
            saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
            assert saved["control_shortcuts"][2] == "f5"

            await self.capture(pilot, "escape")
            assert app.control_shortcuts()[2] == "f5", "Escape cancels"
            await self.capture(pilot, "delete")
            assert 2 not in app.control_shortcuts(), "Delete clears"

            await pilot.click("#control-keys-defaults")
            await pilot.pause()
            assert app.control_shortcuts() == DEFAULT_SHORTCUTS

    async def test_capture_takes_keys_the_app_also_binds(self, write_config, make_app):
        """The capture dialog sees F2 itself (to refuse it) rather than the app
        opening Settings again."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = await self.open(app, pilot, row=4)
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert isinstance(app.screen, KeyCaptureScreen)
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert app.screen is screen
            assert "already used" in str(screen.query_one("#control-keys-status").render())


class TestTerminalsWithoutKittyProtocol:
    async def test_regression_ctrl_enter_sent_as_ctrl_j(self, write_config, make_app):
        """REGRESSION: Windows Terminal delivers Ctrl+Enter as a line feed,
        which Textual names ctrl+j (measured), so the Ctrl+Enter default
        never fired there."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            box = await focus_send_box(app, pilot)
            await pilot.press(*"AT", "ctrl+j")
            assert box.value == "AT<CR>"

    def test_an_explicit_ctrl_j_shortcut_wins(self):
        from serialterminal.ui.app import TUIApp
        app = TUIApp.__new__(TUIApp)
        app.settings = {"control_shortcuts": {13: "ctrl+enter", 2: "ctrl+j"}}
        assert app.control_code_for_key("ctrl+j") == 2
        assert app.control_code_for_key("ctrl+enter") == 13
