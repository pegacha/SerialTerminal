"""Regression tests for the issues found in the pre-release review.

Each was reproduced against the app before it was fixed; the docstrings say
what used to happen.
"""

import pytest
import yaml
from textual.widgets import Button, Input, Select

from serialterminal.ui.widgets.dynamic_control_buttons import RESERVED_IDS, normalize_buttons
from serialterminal.ui.widgets.log_panel import HISTORY_LIMIT, LogPanel
from serialterminal.utils.session_capture import SessionCapture, format_capture_line
from tests.conftest import MINIMAL_CONFIG
from tests.fakes import FakeSerialConnection

# Async tests run under asyncio_mode = "auto" (pyproject.toml).


def tab_text(app, tab="ascii"):
    return "\n".join(app.query_one(f"#tab-{tab} LogPanel").lines)


# ----------------------------------------------------------------------------
# A typo in project.yml must never cost the user the file
# ----------------------------------------------------------------------------

BROKEN_YAML = "buttons:\n  - id: a\n    label: 'unclosed\n"


class TestUnreadableConfigIsNeverOverwritten:
    async def test_regression_yaml_typo_does_not_wipe_the_file(self, isolated_cwd, make_app):
        """REGRESSION: one YAML typo made load_config fall back to {}, and on
        exit save_config wrote that over project.yml - every button and
        sequence in it gone (a 5 KB file became 3 bytes)."""
        path = isolated_cwd / "project.yml"
        path.write_text(BROKEN_YAML, encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
        assert path.read_text(encoding="utf-8") == BROKEN_YAML

    async def test_problem_is_shown_on_screen(self, isolated_cwd, make_app):
        (isolated_cwd / "project.yml").write_text(BROKEN_YAML, encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            text = tab_text(app)
            assert "not loaded" in text and "invalid YAML" in text
            assert "will not be overwritten" in text

    async def test_non_mapping_top_level_is_unreadable_too(self, isolated_cwd, make_app):
        path = isolated_cwd / "project.yml"
        path.write_text("- just\n- a list\n", encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "must be a mapping" in tab_text(app)
        assert path.read_text(encoding="utf-8") == "- just\n- a list\n"

    async def test_fixing_the_file_and_reloading_resumes_saving(self, isolated_cwd, make_app):
        path = isolated_cwd / "project.yml"
        path.write_text(BROKEN_YAML, encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            path.write_text(yaml.dump(MINIMAL_CONFIG), encoding="utf-8")
            app.action_reload_config()
            await pilot.pause()
            assert app.config_unreadable is None
            app.query_one("#serial-baud", Select).value = "19200"
            app.save_config()
        assert yaml.safe_load(path.read_text())["serial"]["baud_rate"] == 19200

    async def test_empty_file_is_fine_and_saved_normally(self, isolated_cwd, make_app):
        path = isolated_cwd / "project.yml"
        path.write_text("", encoding="utf-8")
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.config_unreadable is None
            app.save_config()
        assert "serial" in yaml.safe_load(path.read_text())


# ----------------------------------------------------------------------------
# Malformed buttons: repaired or skipped, reported, never a crash
# ----------------------------------------------------------------------------

class TestNormalizeButtons:
    def test_valid_entries_pass_through_unchanged(self):
        raw = [{"id": "ping", "label": "Ping", "message": "P"}]
        buttons, problems = normalize_buttons(raw)
        assert buttons == raw and problems == []

    def test_input_is_not_mutated(self):
        raw = [{"id": "has space", "repeat": "100"}]
        normalize_buttons(raw)
        assert raw == [{"id": "has space", "repeat": "100"}]

    @pytest.mark.parametrize("raw", [{"id": "x"}, "text", 42])
    def test_non_list_section_loads_nothing_and_says_why(self, raw):
        buttons, problems = normalize_buttons(raw)
        assert buttons == [] and "must be a list" in problems[0]

    def test_none_section_is_simply_empty(self):
        assert normalize_buttons(None) == ([], [])

    @pytest.mark.parametrize("entry", ["oops", 7, None, ["a"]])
    def test_non_mapping_entries_skipped(self, entry):
        buttons, problems = normalize_buttons([entry, {"id": "ok"}])
        assert [b["id"] for b in buttons] == ["ok"]
        assert "skipped" in problems[0]

    def test_duplicate_ids_made_unique(self):
        buttons, problems = normalize_buttons([{"id": "dup"}, {"id": "dup"}, {"id": "dup"}])
        assert [b["id"] for b in buttons] == ["dup", "dup-2", "dup-3"]
        assert len(problems) == 2

    @pytest.mark.parametrize(
        "raw_id,expected",
        [("my button", "my-button"), ("1st", "btn-1st"), ("a.b/c", "a-b-c"), (5, "btn-5")],
    )
    def test_illegal_ids_made_legal(self, raw_id, expected):
        buttons, _ = normalize_buttons([{"id": raw_id}])
        assert buttons[0]["id"] == expected

    def test_missing_id_gets_one(self):
        buttons, problems = normalize_buttons([{"label": "No id"}])
        assert buttons[0]["id"] == "button-1"
        assert problems == []

    @pytest.mark.parametrize("reserved", ["serial-connect", "send-button", "title"])
    def test_app_widget_ids_are_reserved(self, reserved):
        """A button with id serial-connect would have been routed as the
        Connect button."""
        buttons, problems = normalize_buttons([{"id": reserved}])
        assert buttons[0]["id"] != reserved and buttons[0]["id"] not in RESERVED_IDS
        assert problems

    @pytest.mark.parametrize("raw,expected", [("1000", 1000), (250.0, 250), (None, None), ("", "")])
    def test_repeat_coerced(self, raw, expected):
        buttons, problems = normalize_buttons([{"id": "r", "repeat": raw}])
        assert buttons[0].get("repeat") == expected
        assert problems == []

    def test_regression_non_numeric_repeat_becomes_one_shot(self):
        """REGRESSION: a quoted or misspelt repeat reached `repeat > 0` in the
        button handler, raised TypeError there, and took the app down."""
        buttons, problems = normalize_buttons([{"id": "r", "repeat": "fast"}])
        assert buttons[0]["repeat"] == 0
        assert "not a number" in problems[0]


class TestMalformedButtonsInTheApp:
    @pytest.mark.parametrize(
        "buttons",
        [
            ["oops", {"id": "ok", "label": "OK", "message": "x"}],
            [{"id": "dup", "label": "A"}, {"id": "dup", "label": "B"}],
            [{"id": "my button", "label": "A"}],
            {"id": "x"},
        ],
        ids=["non-mapping entry", "duplicate ids", "illegal id", "section not a list"],
    )
    async def test_regression_app_starts_and_reports(self, write_config, make_app, buttons):
        """REGRESSION: each of these crashed the app at startup with a traceback
        (AttributeError, MountError, BadIdentifier)."""
        config = dict(MINIMAL_CONFIG, buttons=buttons)
        write_config(config)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "[Error]" in tab_text(app)

    async def test_bad_edit_then_reload_does_not_crash(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            write_config(dict(MINIMAL_CONFIG, buttons=[{"id": "x y"}, {"id": "x y"}]))
            app.action_reload_config()
            await pilot.pause()
            ids = [b.id for b in app.query(".control-button")]
            assert ids == ["x-y", "x-y-2"]

    async def test_saved_config_keeps_the_users_text(self, write_config, make_app, isolated_cwd):
        """Repairs apply to the widgets only; project.yml keeps what was typed."""
        write_config(dict(MINIMAL_CONFIG, buttons=[{"id": "my button", "label": "A"}]))
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.save_config()
        saved = yaml.safe_load((isolated_cwd / "project.yml").read_text())
        assert saved["buttons"][0]["id"] == "my button"

    async def test_string_repeat_in_config_works(self, write_config, make_app):
        write_config(dict(MINIMAL_CONFIG, buttons=[
            {"id": "poll", "label": "Poll", "message": "AA", "format": "hex", "repeat": "500"}]))
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.serial_conn = FakeSerialConnection()
            await pilot.click("#poll")
            await pilot.pause()
            assert "poll" in app.repeating_buttons


# ----------------------------------------------------------------------------
# Sending
# ----------------------------------------------------------------------------

class DeadPort(FakeSerialConnection):
    """Claims to be connected, but every write fails - an unplugged adapter."""

    def write(self, data):
        return 0


class TestSendFailures:
    async def test_regression_failed_write_keeps_text_and_logs_no_tx(self, write_config, make_app):
        """REGRESSION: write() reports failure by returning 0, which was ignored:
        the log showed a successful [TX] and the quick-send box was cleared."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.serial_conn = DeadPort()
            box = app.query_one("#quick-send-input", Input)
            box.value = "PING"
            app._quick_send()
            await pilot.pause()
            assert box.value == "PING"
            assert "[TX]" not in tab_text(app)
            assert "Send failed" in tab_text(app)

    async def test_empty_send_is_refused(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            assert app._send_command("", format_override="ascii") is False
            await pilot.pause()
            assert port.written == []
            assert "Nothing to send" in tab_text(app)

    async def test_tx_logged_after_a_successful_write(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            assert app._send_command("PING", format_override="ascii") is True
            await pilot.pause()
            assert port.written == [b"PING"]
            assert "[TX] PING" in tab_text(app)


# ----------------------------------------------------------------------------
# Session capture
# ----------------------------------------------------------------------------

class FailingHandle:
    def __init__(self):
        self.closed = False

    def write(self, text):
        raise OSError("drive removed")

    def close(self):
        self.closed = True


class TestCaptureLifecycle:
    def test_regression_stop_closes_even_if_the_final_write_fails(self):
        """REGRESSION: write and close shared one try, so a failed footer write
        skipped close() and leaked the handle (e.g. a USB stick pulled)."""
        capture = SessionCapture()
        handle = FailingHandle()
        capture._file = handle
        capture.stop()
        assert handle.closed
        assert not capture.active

    def test_failed_header_write_leaves_capture_inactive(self, tmp_path, monkeypatch):
        import builtins

        handle = FailingHandle()
        monkeypatch.setattr(builtins, "open", lambda *a, **k: handle)
        capture = SessionCapture()
        with pytest.raises(OSError):
            capture.start(tmp_path / "x.log")
        assert not capture.active
        assert handle.closed

    def test_multiline_text_entry_stays_on_one_line(self):
        from datetime import datetime

        line = format_capture_line(datetime(2026, 1, 1), "error", "first\nsecond\r\n")
        assert "\n" not in line
        assert line.endswith("first\\nsecond\\r\\n")


# ----------------------------------------------------------------------------
# Log panel memory and live counts
# ----------------------------------------------------------------------------

class TestLogPanelBounds:
    def test_regression_widget_line_buffer_is_capped(self):
        """REGRESSION: only the entry history was capped; Log's own lines grew
        for as long as the app ran."""
        assert LogPanel().max_lines == HISTORY_LIMIT

    async def test_match_count_tracks_new_entries_and_eviction(self, write_config, make_app,
                                                                monkeypatch):
        import serialterminal.ui.widgets.log_panel as log_panel_module
        from collections import deque

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            panel = app.query_one("#tab-ascii LogPanel", LogPanel)
            panel._entries = deque(maxlen=3)
            panel.set_filter("pong")
            for text in ("PONG 1", "ping", "PONG 2"):
                panel.write_message(text)
            assert panel.match_count == 2
            panel.write_message("ping")  # evicts "PONG 1"
            assert panel.match_count == 1
            assert panel.match_count == sum(1 for e in panel._entries if panel._matches(e))

    async def test_status_count_is_live_while_filtering(self, write_config, make_app):
        """REGRESSION: the 'N matching' count only refreshed when the filter or
        tab changed, so it went stale while traffic arrived."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("ctrl+f")
            await pilot.press(*"pong")
            await pilot.pause()
            app.log_message(b"PONG\r\n", "rx")
            app.log_message(b"PONG\r\n", "rx")
            await pilot.pause()
            status = str(app.query_one("#log-status").render())
            assert "2 matching" in status


# ----------------------------------------------------------------------------
# Display details from the UX review
# ----------------------------------------------------------------------------

class TestDisplay:
    async def test_multiline_ascii_frame_aligned_under_its_data(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.log_message(b"LINE1\r\nLINE2\r\n", "rx")
            await pilot.pause()
            lines = app.query_one("#tab-ascii LogPanel").lines[-2:]
            assert lines[1].index("LINE2") == lines[0].index("LINE1")

    @pytest.mark.parametrize(
        "widget_id,expected",
        [("#serial-parity", "No parity"), ("#serial-bits", "8 bits"),
         ("#serial-stop-bits", "1 stop"), ("#send-checksum", "No checksum")],
    )
    async def test_selects_say_what_they_are(self, write_config, make_app, widget_id, expected):
        """A bare 'None  8  1' row gave no hint which selector was which."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one(widget_id, Select)
            labels = {str(prompt) for prompt, _ in select._options}
            assert expected in labels

    async def test_saved_values_unchanged_by_the_new_labels(self, write_config, make_app,
                                                            isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.save_config()
        serial = yaml.safe_load((isolated_cwd / "project.yml").read_text())["serial"]
        assert (serial["parity"], serial["data_bits"], serial["stop_bits"]) == ("N", "8", "1")

    async def test_long_button_labels_ellipsise_on_one_row(self, write_config, make_app):
        label = "SETUP(Device B) 100ms, high, multichannel"
        write_config(dict(MINIMAL_CONFIG, buttons=[{"id": "long", "label": label}]))
        app = make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            button = app.query_one("#long", Button)
            assert button.region.height == 1
            assert button.styles.text_wrap == "nowrap"
            assert button.styles.text_overflow == "ellipsis"

    async def test_regression_no_dead_scrollbar_row_under_the_log(self, write_config, make_app):
        """REGRESSION: Log defaults to overflow-x: scroll, so every tab kept an
        empty horizontal scrollbar - a whole row - under the traffic."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            panel = app.query_one("#tab-ascii LogPanel", LogPanel)  # the visible tab
            app.log_message(b"short", "rx")
            await pilot.pause()
            assert not panel.show_horizontal_scrollbar
            app.log_message(b"X" * 200, "rx")  # wider than the log: must still scroll
            await pilot.pause()
            assert panel.show_horizontal_scrollbar and panel.max_scroll_x > 0

    async def test_title_and_version(self, write_config, make_app):
        from serialterminal import __version__

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            assert app.title == "SerialTerminal"
            assert __version__ in str(app.query_one("#title").render())

    async def test_session_bindings_fit_the_footer_at_120_columns(self, write_config, make_app):
        """With long labels in definition order, 'record' fell off the footer
        below ~135 columns."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            app.set_focus(None)
            await pilot.pause()
            visible = {
                key.description
                for key in app.query("FooterKey")
                if app.screen.region.contains_region(key.region)
            }
            assert {"quit", "filter", "pause", "record", "clear"} <= visible
