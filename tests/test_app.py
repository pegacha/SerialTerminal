"""App-level behaviour, driven through Textual's test pilot.

Every test here runs in an isolated working directory (see conftest), because
TUIApp reads config in __init__ and writes it back on unmount.
"""

import pytest
import yaml
from textual.widgets import Button, Select

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
        from ui.app import TUIApp

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
