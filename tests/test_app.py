"""App-level behaviour, driven through Textual's test pilot.

Every test here runs in an isolated working directory (see conftest), because
TUIApp reads config in __init__ and writes it back on unmount.
"""

import pytest
import yaml
from textual.widgets import Button, Input, Select

from serialterminal.ui.widgets.log_panel import MultiFormatLog
from serialterminal.ui.widgets.quick_send import QuickSend
from tests.conftest import MINIMAL_CONFIG

pytestmark = pytest.mark.asyncio


async def running(app):
    """Shorthand for the pilot context manager."""
    return app.run_test()


class TestConfigLoading:
    async def test_loads_buttons_and_sequences(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.config["buttons"]) == 2
            assert len(app.sequence_handler.sequences) == 1

    async def test_missing_config_falls_back_to_defaults(self, isolated_cwd, make_app):
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.config["serial"]["baud_rate"] == 115200
            assert app.config["buttons"] == []

    async def test_settings_file_created_on_first_launch(self, isolated_cwd, make_app):
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
        assert (isolated_cwd / "settings.yml").exists()

    async def test_corrupt_config_does_not_prevent_startup(self, isolated_cwd, make_app):
        (isolated_cwd / "project.yml").write_text("{[not valid yaml", encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.config == {}
            assert app.sequence_handler is not None


class TestSerialSettingsRoundTrip:
    @pytest.mark.parametrize(
        "field,widget,value",
        [
            ("baud_rate", "#serial-baud", "19200"),
            ("parity", "#serial-parity", "E"),
            ("data_bits", "#serial-bits", "7"),
            ("stop_bits", "#serial-stop-bits", "2"),
        ],
    )
    async def test_regression_every_saved_field_is_restored(
        self, write_config, make_app, field, widget, value
    ):
        """REGRESSION: save wrote all five serial fields but restore handled
        only port and baud, so a 7E1 device silently came back as 8N1."""
        config = dict(MINIMAL_CONFIG)
        config["serial"] = dict(MINIMAL_CONFIG["serial"], **{field: value})
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(widget, Select).value == value

    async def test_settings_survive_a_save_load_cycle(self, write_config, make_app):
        config = dict(MINIMAL_CONFIG)
        config["serial"] = dict(
            MINIMAL_CONFIG["serial"],
            baud_rate=38400, parity="O", data_bits="7", stop_bits="2",
        )
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
        reloaded = make_app()
        async with reloaded.run_test() as pilot:
            await pilot.pause()
            assert reloaded.query_one("#serial-baud", Select).value == "38400"
            assert reloaded.query_one("#serial-parity", Select).value == "O"
            assert reloaded.query_one("#serial-bits", Select).value == "7"
            assert reloaded.query_one("#serial-stop-bits", Select).value == "2"

    async def test_unavailable_saved_port_is_reported_not_silently_dropped(
        self, write_config, make_app
    ):
        config = dict(MINIMAL_CONFIG)
        config["serial"] = dict(MINIMAL_CONFIG["serial"], port="COM_NOPE_99")
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "COM_NOPE_99" in text

    async def test_regression_refresh_keeps_the_selected_port(
        self, write_config, make_app
    ):
        """REGRESSION: set_options() resets the value, so pressing Refresh
        silently dropped the selection back to none."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one("#serial-port-select", Select)
            select.set_options([("None", "none"), ("COM77 - fake", "COM77")])
            select.value = "COM77"
            # Re-enumerating finds only real ports, so stub the scan to keep
            # the fake one present.
            app.__class__.refresh_serial_ports(app)
            await pilot.pause()
            # Real hardware differs per machine; either the port survived or it
            # genuinely vanished and was reported. Both beat silent reset.
            if select.value == "none":
                text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
                assert "COM77" in text


class TestPortList:
    @pytest.mark.parametrize(
        "device,description,label",
        [
            ("COM4", "USB Serial Port (COM4)", "COM4 — USB Serial Port"),
            ("COM4", "USB Serial Port", "COM4 — USB Serial Port"),
            ("/dev/ttyS0", "n/a", "/dev/ttyS0"),
            ("/dev/ttyUSB0", "/dev/ttyUSB0", "/dev/ttyUSB0"),
            ("COM7", "", "COM7"),
            ("COM7", None, "COM7"),
        ],
    )
    async def test_port_label_drops_repetition(self, isolated_cwd, description, device, label):
        from serialterminal.ui.app import TUIApp

        assert TUIApp.port_label(device, description) == label

    async def test_ports_listed_in_natural_order(self, write_config, make_app, monkeypatch):
        from serialterminal.serial_comm.connection import SerialConnection

        fake = [("COM10", "COM10", "x"), ("COM3", "COM3", "x"),
                ("COM19", "COM19", "x"), ("COM4", "COM4", "x")]
        monkeypatch.setattr(SerialConnection, "list_ports", staticmethod(lambda: fake))
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            values = [value for _, value in app.query_one("#serial-port-select", Select)._options]
            assert values == ["none", "COM3", "COM4", "COM10", "COM19"]


class TestImportPicker:
    async def test_regression_default_filter_shows_docklight_files(self, isolated_cwd):
        """REGRESSION: 'YAML files' was the first (default) filter, so .ptp
        files didn't appear in the picker until you changed filter."""
        from pathlib import Path
        from serialterminal.ui.app import import_filters

        default = import_filters()[0]
        for name in ("device.ptp", "project.yml", "x.YAML"):
            assert default(Path(name)), name
        assert not default(Path("notes.txt"))

    async def test_ctrl_i_opens_the_picker_with_that_default(self, write_config, make_app):
        from textual_fspicker import FileOpen

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+i")
            await pilot.pause()
            assert isinstance(app.screen, FileOpen)


class TestThemePersistence:
    async def test_settings_theme_wins_over_project(self, isolated_cwd, make_app):
        (isolated_cwd / "settings.yml").write_text(
            yaml.dump({"ui": {"theme": "nord"}}), encoding="utf-8"
        )
        (isolated_cwd / "project.yml").write_text(
            yaml.dump(dict(MINIMAL_CONFIG, ui={"theme": "gruvbox"})), encoding="utf-8"
        )
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "nord"

    async def test_legacy_project_theme_honoured_when_settings_has_none(
        self, isolated_cwd, make_app
    ):
        (isolated_cwd / "settings.yml").write_text(
            yaml.dump({"config": {"last_used": None}}), encoding="utf-8"
        )
        (isolated_cwd / "project.yml").write_text(
            yaml.dump(dict(MINIMAL_CONFIG, ui={"theme": "gruvbox"})), encoding="utf-8"
        )
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "gruvbox"

    async def test_saved_project_no_longer_carries_a_theme(
        self, isolated_cwd, write_config, make_app
    ):
        write_config(dict(MINIMAL_CONFIG, ui={"theme": "gruvbox"}))
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.save_config()
        saved = yaml.safe_load((isolated_cwd / "project.yml").read_text())
        assert "ui" not in saved
        assert saved["serial"]["baud_rate"] == 9600, "other sections preserved"


class TestValidateConfig:
    @pytest.mark.parametrize("entries", [[1, 2], [None], ["abc"], [[]]])
    async def test_regression_non_dict_entries_rejected_not_crashed(
        self, isolated_cwd, make_app, entries
    ):
        """REGRESSION: `'id' not in btn` raised TypeError for non-containers and
        did a substring test on strings, so the validator crashed or lied."""
        app = make_app()
        is_valid, error = app.validate_config({"buttons": entries})
        assert is_valid is False
        assert "mapping" in error

    async def test_missing_required_field_reported(self, isolated_cwd, make_app):
        app = make_app()
        is_valid, error = app.validate_config({"buttons": [{"label": "no id"}]})
        assert is_valid is False
        assert "'id'" in error

    async def test_sequences_need_a_name(self, isolated_cwd, make_app):
        app = make_app()
        is_valid, error = app.validate_config({"sequences": [{"receive": {}}]})
        assert is_valid is False
        assert "'name'" in error

    @pytest.mark.parametrize("bad", ["a string", 42, {"k": "v"}])
    async def test_non_list_sections_rejected(self, isolated_cwd, make_app, bad):
        app = make_app()
        assert app.validate_config({"buttons": bad})[0] is False

    async def test_valid_config_accepted(self, isolated_cwd, make_app):
        app = make_app()
        assert app.validate_config(MINIMAL_CONFIG) == (True, "")

    async def test_non_dict_config_rejected(self, isolated_cwd, make_app):
        app = make_app()
        assert app.validate_config(["not", "a", "dict"])[0] is False


class TestRepeatingButtons:
    async def test_regression_timers_cleared_before_reload_recomposes(
        self, write_config, make_app
    ):
        """REGRESSION: reload recomposed the panel but left timers running, so
        the port kept being polled with nothing on screen to show it."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            button = app.query_one("#btn-poll", Button)
            app._start_repeating_button(button.id, button, "AA", "hex", 500)
            assert app.repeating_buttons
            app.action_reload_config()
            await pilot.pause()
            assert app.repeating_buttons == {}

    async def test_toggle_starts_then_stops(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            button = app.query_one("#btn-poll", Button)
            app._toggle_repeat_button(button, "AA", "hex", 500)
            assert "btn-poll" in app.repeating_buttons
            assert button.has_class("button-repeating")
            app._toggle_repeat_button(button, "AA", "hex", 500)
            assert "btn-poll" not in app.repeating_buttons
            assert not button.has_class("button-repeating")

    async def test_zero_interval_refused(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            button = app.query_one("#btn-poll", Button)
            app._toggle_repeat_button(button, "AA", "hex", 0)
            assert app.repeating_buttons == {}

    async def test_disconnect_stops_repeats(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            button = app.query_one("#btn-poll", Button)
            app._start_repeating_button(button.id, button, "AA", "hex", 500)
            app._disconnect_serial()
            await pilot.pause()
            assert app.repeating_buttons == {}


class TestLogging:
    async def test_regression_log_error_path_does_not_raise(self, isolated_cwd, make_app):
        """REGRESSION: a local `log =` made the module logger function-local, so
        the error handler raised UnboundLocalError on its own reporting line."""
        from serialterminal.ui.app import TUIApp

        unmounted = TUIApp.__new__(TUIApp)
        unmounted.log_message("no widgets here", "info")  # must not raise

    async def test_frame_reaches_all_four_tabs(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"\x41\x42", "rx")
            await pilot.pause()
            for tab in ("ascii", "hex", "decimal", "binary"):
                assert app.query_one("#tab-" + tab + " LogPanel").lines

    async def test_regression_one_timestamp_across_tabs(self, write_config, make_app):
        """REGRESSION: each formatter called datetime.now(), so the four tabs
        disagreed about when a frame arrived."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"\x41\x42", "rx")
            await pilot.pause()
            stamps = {
                app.query_one("#tab-" + tab + " LogPanel").lines[-1].split("]")[0]
                for tab in ("ascii", "hex", "decimal", "binary")
            }
            assert len(stamps) == 1

    async def test_tx_and_rx_are_labelled(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"\x41", "tx")
            app.log_message(b"\x42", "rx")
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-hex LogPanel").lines)
            assert "[TX]" in text and "[RX]" in text

    async def test_clear_empties_every_tab(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"\x41", "rx")
            await pilot.pause()
            app.action_clearlog_message()
            await pilot.pause()
            for tab in ("ascii", "hex", "decimal", "binary"):
                assert app.query_one("#tab-" + tab + " LogPanel").lines == []


class TestSendingWhileDisconnected:
    async def test_send_is_refused_and_reported(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._send_command("PING")
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "Not connected" in text


def tab_text(app, tab="ascii"):
    return "\n".join(app.query_one(f"#tab-{tab} LogPanel").lines)


def connect_fake(app):
    """Swap in a fake port so sends go somewhere observable."""
    from tests.fakes import FakeSerialConnection

    app.serial_conn = FakeSerialConnection()
    return app.serial_conn


class TestQuickSend:
    async def set_options(self, app, pilot, fmt="ascii", eol="none", checksum="none"):
        app.query_one("#send-format-select", Select).value = fmt
        app.query_one("#send-line-ending", Select).value = eol
        app.query_one("#send-checksum", Select).value = checksum
        await pilot.pause()

    async def test_ascii_with_crlf(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            await self.set_options(app, pilot, "ascii", "crlf")
            app.query_one("#quick-send-input", Input).value = "PING"
            app._quick_send()
            assert port.written == [b"PING\r\n"]

    async def test_hex_with_crc_and_no_eol(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            # CRLF selected, but it must not land on a hex frame.
            await self.set_options(app, pilot, "hex", "crlf", "crc16_modbus")
            app.query_one("#quick-send-input", Input).value = "01 03 00 00 00 0A"
            app._quick_send()
            assert port.written == [bytes.fromhex("01030000000AC5CD")]

    async def test_line_ending_disabled_outside_ascii(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            eol = app.query_one("#send-line-ending", Select)
            await self.set_options(app, pilot, "hex")
            assert eol.disabled
            await self.set_options(app, pilot, "ascii")
            assert not eol.disabled

    async def test_invalid_input_flagged_while_typing(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self.set_options(app, pilot, "hex")
            box = app.query_one("#quick-send-input", Input)
            box.focus()
            await pilot.press("4", "G")
            await pilot.pause()
            assert box.has_class("-invalid")
            assert "'G' is not a hex digit" in app.query_one(QuickSend).border_subtitle

    async def test_switching_format_revalidates(self, write_config, make_app):
        """'41' is fine as hex; as binary it is not."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self.set_options(app, pilot, "hex")
            box = app.query_one("#quick-send-input", Input)
            box.value = "41"
            await pilot.pause()
            assert app.query_one(QuickSend).border_subtitle == ""
            await self.set_options(app, pilot, "binary")
            assert "binary digit" in app.query_one(QuickSend).border_subtitle

    async def test_failed_send_keeps_the_text(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            await self.set_options(app, pilot, "hex")
            box = app.query_one("#quick-send-input", Input)
            box.value = "4G"
            app._quick_send()
            assert box.value == "4G"
            assert port.written == []
            assert "Cannot send" in tab_text(app)

    async def test_send_while_disconnected_keeps_the_text(self, write_config, make_app):
        """REGRESSION: Enter while disconnected silently wiped the box."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            box = app.query_one("#quick-send-input", Input)
            box.focus()
            box.value = "PING"
            await pilot.press("enter")
            await pilot.pause()
            assert box.value == "PING"
            assert "Not connected" in tab_text(app)

    async def test_successful_send_clears_the_box(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            connect_fake(app)
            box = app.query_one("#quick-send-input", Input)
            box.focus()
            box.value = "PING"
            await pilot.press("enter")
            await pilot.pause()
            assert box.value == ""

    async def test_choices_persist_in_project(self, isolated_cwd, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await self.set_options(app, pilot, "hex", "lf", "xor8")
            app.save_config()
        saved = yaml.safe_load((isolated_cwd / "project.yml").read_text())
        assert saved["quick_send"] == {"format": "hex", "line_ending": "lf", "checksum": "xor8"}

        reloaded = make_app()
        async with reloaded.run_test() as pilot:
            await pilot.pause()
            assert reloaded.query_one("#send-format-select", Select).value == "hex"
            assert reloaded.query_one("#send-line-ending", Select).value == "lf"
            assert reloaded.query_one("#send-checksum", Select).value == "xor8"


class TestButtonLayout:
    async def test_regression_every_button_visible_with_full_label(
        self, write_config, make_app
    ):
        """REGRESSION: buttons sat in a Horizontal, which never wraps, at a fixed
        12 columns. With 11 buttons two were off-screen, and truncation made
        'LIGHT RELAY ON' and 'LIGHT RELAY OFF' read identically."""
        labels = ["Ping", "Hardware Version", "Software Version", "LED OFF",
                  "LED ON", "LIGHT RELAY OFF", "LIGHT RELAY ON", "Reader disable",
                  "Reader enable", "Enable raw mode", "Disable raw mode"]
        config = dict(MINIMAL_CONFIG)
        config["buttons"] = [
            {"id": f"b{i}", "label": label, "message": "X", "format": "ascii"}
            for i, label in enumerate(labels)
        ]
        write_config(config)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for i, label in enumerate(labels):
                button = app.query_one(f"#b{i}", Button)
                assert app.screen.region.contains_region(button.region), label
                assert button.region.width >= len(label) + 2, label

    async def test_regression_many_buttons_scroll_instead_of_eating_the_log(
        self, write_config, make_app
    ):
        """REGRESSION: the panel was sized to its content, so a big Docklight
        import grew it until the log had no rows and later buttons were cut off."""
        config = dict(MINIMAL_CONFIG)
        config["buttons"] = [
            {"id": f"b{i}", "label": f"Button number {i}", "message": "X", "format": "ascii"}
            for i in range(40)
        ]
        write_config(config)
        app = make_app()
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.pause()
            panel = app.query_one("#control-buttons")
            assert app.query_one("#log-tabs").region.height >= 10
            assert panel.region.height <= 38 * 0.35 + 1
            assert panel.max_scroll_y > 0 and panel.show_vertical_scrollbar

            panel.scroll_end(animate=False)
            await pilot.pause()
            assert panel.region.contains_region(app.query_one("#b39", Button).region)

    async def test_mouse_wheel_over_a_button_scrolls_the_panel(self, write_config, make_app):
        from textual import events

        config = dict(MINIMAL_CONFIG)
        config["buttons"] = [
            {"id": f"b{i}", "label": f"Button {i}", "message": "X", "format": "ascii"}
            for i in range(40)
        ]
        write_config(config)
        app = make_app()
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.pause()
            panel = app.query_one("#control-buttons")
            button = app.query_one("#b0", Button)
            region = button.region
            button.post_message(events.MouseScrollDown(
                button, 1, 0, 0, 1, 0, False, False, False,
                screen_x=region.x + 1, screen_y=region.y,
            ))
            await pilot.pause(0.5)
            assert panel.scroll_y > 0

    async def test_long_label_without_tooltip_gets_one(self, write_config, make_app):
        label = "SETUP(Device B) 100ms, high, multichannel"
        config = dict(MINIMAL_CONFIG)
        config["buttons"] = [{"id": "long", "label": label, "message": "X", "format": "ascii"}]
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#long", Button).tooltip == label

    async def test_file_dialog_controls_are_one_row(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(100, 38)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+i")
            await pilot.pause(0.3)
            bar = list(app.screen.query("InputBar > *"))
            assert len(bar) == 4  # file name, filter, Open, Cancel
            for widget in bar:
                assert widget.region.height == 1, type(widget).__name__

    async def test_controls_are_one_row(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for selector in ("#serial-connect", "#serial-baud", "#send-checksum",
                             "#quick-send-input", "#btn-ping"):
                assert app.query_one(selector).region.height == 1, selector


class TestButtonChecksums:
    async def test_button_appends_its_own_checksum_and_eol(self, write_config, make_app):
        config = dict(MINIMAL_CONFIG)
        config["buttons"] = [
            {"id": "btn-crc", "label": "CRC", "message": "01 03 00 00 00 0A",
             "format": "hex", "checksum": "crc16_modbus"},
            {"id": "btn-txt", "label": "Txt", "message": "HI",
             "format": "ascii", "line_ending": "cr"},
        ]
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            await pilot.click("#btn-crc")
            await pilot.click("#btn-txt")
            await pilot.pause()
            assert port.written == [bytes.fromhex("01030000000AC5CD"), b"HI\r"]

    async def test_quick_send_options_do_not_leak_into_buttons(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            app.query_one("#send-checksum", Select).value = "crc16_modbus"
            await pilot.pause()
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.written == [b"PING"]

    async def test_repeating_button_keeps_its_checksum(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            button = app.query_one("#btn-poll", Button)
            app._start_repeating_button(button.id, button, "01 02", "hex", 50, checksum="sum8")
            # Poll rather than sleep a fixed time: a loaded CI runner can miss ticks.
            for _ in range(40):
                if len(port.written) >= 2:
                    break
                await pilot.pause(0.05)
            app._stop_all_repeating_buttons()
            assert len(port.written) >= 2
            assert set(port.written) == {b"\x01\x02\x03"}


class TestLogFilter:
    async def test_filter_shows_only_matching_entries(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"ALPHA", "rx")
            app.log_message(b"BETA", "rx")
            await pilot.press("ctrl+f")
            await pilot.press(*"beta")
            await pilot.pause()
            text = tab_text(app)
            assert "BETA" in text and "ALPHA" not in text

    async def test_each_tab_matches_its_own_notation(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one(MultiFormatLog)
            # Fixed stamps: a real one can itself contain "42" (17:42:...),
            # which made this test fail at certain times of day.
            panel.log_message(b"A", "rx", stamp="00:00:00.000")
            panel.log_message(b"B", "rx", stamp="00:00:00.000")
            panel.set_filter("41")
            await pilot.pause()
            assert "41" in tab_text(app, "hex") and "42" not in tab_text(app, "hex")
            assert tab_text(app, "ascii") == ""

    async def test_regression_timestamp_is_not_searched(self, write_config, make_app):
        """REGRESSION: the filter matched the timestamp, so '41' on the HEX tab
        hit every entry logged at second :41 (and the test above flaked)."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one(MultiFormatLog)
            panel.log_message(b"B", "rx", stamp="12:41:41.414")
            panel.set_filter("41")
            await pilot.pause()
            assert tab_text(app, "hex") == ""

    async def test_direction_tag_is_searchable(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"out", "tx")
            app.log_message(b"in", "rx")
            app.query_one(MultiFormatLog).set_filter("[rx]")
            await pilot.pause()
            assert "[RX] in" in tab_text(app) and "[TX]" not in tab_text(app)

    async def test_closing_restores_everything(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"ALPHA", "rx")
            app.log_message(b"BETA", "rx")
            await pilot.press("ctrl+f", *"beta")
            await pilot.press("escape")
            await pilot.pause()
            text = tab_text(app)
            assert "ALPHA" in text and "BETA" in text
            assert not app.query_one("#log-filter", Input).display

    async def test_new_entries_respect_the_filter(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one(MultiFormatLog).set_filter("keep")
            app.log_message("keep me", "info")
            app.log_message("drop me", "info")
            await pilot.pause()
            assert "keep me" in tab_text(app) and "drop me" not in tab_text(app)

    async def test_enter_in_filter_box_never_sends(self, write_config, make_app):
        """Input.Submitted bubbles to the app, which used to treat any Enter as a send."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = connect_fake(app)
            app.query_one("#quick-send-input", Input).value = "PING"
            await pilot.press("ctrl+f", "x", "enter")
            await pilot.pause()
            assert port.written == []

    async def test_status_reports_match_count(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(3):
                app.log_message(b"hit", "rx")
            app.log_message(b"miss", "rx")
            app.query_one(MultiFormatLog).set_filter("hit")
            await pilot.pause()
            assert "3 matching" in str(app.query_one("#log-status").render())


class TestPause:
    async def test_paused_view_does_not_move_and_catches_up_on_resume(
        self, write_config, make_app
    ):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"before", "rx")
            await pilot.press("ctrl+b")
            frozen = tab_text(app)
            app.log_message(b"during", "rx")
            await pilot.pause()
            assert tab_text(app) == frozen
            assert "+1 new" in str(app.query_one("#log-status").render())
            await pilot.press("ctrl+b")
            await pilot.pause()
            assert "during" in tab_text(app)
            assert not app.query_one("#log-status").display

    async def test_pause_works_while_typing_in_quick_send(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#quick-send-input", Input).focus()
            await pilot.press("ctrl+b")
            assert app.query_one(MultiFormatLog).paused

    async def test_clear_while_paused_resets_the_counter(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+b")
            app.log_message(b"x", "rx")
            app.action_clearlog_message()
            await pilot.press("ctrl+b")
            await pilot.pause()
            assert tab_text(app) == ""


class TestSessionCapture:
    async def test_traffic_is_recorded_with_screen_timestamps(
        self, isolated_cwd, write_config, make_app
    ):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.start_capture(isolated_cwd / "cap.log")
            app.log_message(b"\x41\x42", "rx")
            await pilot.pause()
            screen_stamp = tab_text(app, "hex").splitlines()[-1].split("]")[0].lstrip("[")
            assert "REC cap.log" in str(app.query_one("#log-status").render())
        text = (isolated_cwd / "cap.log").read_text(encoding="utf-8")
        assert f"{screen_stamp} RX   41 42  |AB|" in text
        assert "# capture stopped" in text, "unmount closes the capture"

    async def test_toggle_stops_recording(self, isolated_cwd, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.start_capture(isolated_cwd / "cap.log")
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert not app.capture.active
            app.log_message(b"late", "rx")
        assert "late" not in (isolated_cwd / "cap.log").read_text(encoding="utf-8")

    async def test_ctrl_s_asks_where_to_record(self, write_config, make_app):
        from textual_fspicker import FileSave

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, FileSave)

    async def test_unwritable_path_reported(self, isolated_cwd, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            (isolated_cwd / "a_dir").mkdir()
            assert not app.start_capture(isolated_cwd / "a_dir")
            assert "Cannot record" in tab_text(app)

    async def test_write_failure_stops_capture_and_says_so(
        self, isolated_cwd, write_config, make_app
    ):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.start_capture(isolated_cwd / "cap.log")

            def fail(*args):
                raise OSError("disk full")

            app.capture.write = fail
            app.log_message(b"x", "rx")
            await pilot.pause()
            assert not app.capture.active
            assert "disk full" in tab_text(app)


class TestBindings:
    async def test_ctrl_r_reloads_css(self, write_config, make_app):
        """The binding existed but action_reload_css did not, so the key was a
        silent no-op."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "Reloaded" in text

    async def test_every_binding_has_an_action(self, isolated_cwd, make_app):
        app = make_app()
        for binding in app.BINDINGS:
            action = binding.action
            assert hasattr(app, "action_" + action), "no action_" + action
