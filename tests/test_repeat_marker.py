"""The ↻ / [R] marker on buttons that resend on a timer."""

import pytest
import yaml
from textual.widgets import Select

from serialterminal.ui.widgets.dynamic_control_buttons import (
    REPEAT_SYMBOL, REPEAT_TEXT, ControlButton, button_label, is_repeating, repeat_marker,
    terminal_draws_symbol,
)
from serialterminal.ui.widgets.settings_screen import SettingsScreen
from tests.conftest import MINIMAL_CONFIG


class TestTerminalGuess:
    @pytest.mark.parametrize("environ,platform,expected", [
        ({"WT_SESSION": "1"}, "win32", True),        # Windows Terminal
        ({"TERM_PROGRAM": "vscode"}, "win32", True),  # VS Code, WezTerm, ...
        ({}, "win32", False),                         # old console host
        ({}, "darwin", True),
        ({"TERM": "xterm-256color"}, "linux", True),
        ({"TERM": "linux"}, "linux", False),          # text console, VGA font
    ])
    def test_where_the_symbol_shows(self, environ, platform, expected):
        assert terminal_draws_symbol(environ, platform) is expected

    def test_auto_follows_the_guess(self):
        assert repeat_marker("auto", {"WT_SESSION": "1"}, "win32") == REPEAT_SYMBOL
        assert repeat_marker("auto", {}, "win32") == REPEAT_TEXT

    @pytest.mark.parametrize("platform", ["win32", "linux"])
    def test_explicit_choices_ignore_the_guess(self, platform):
        assert repeat_marker("symbol", {}, platform) == REPEAT_SYMBOL
        assert repeat_marker("text", {"WT_SESSION": "1"}, platform) == REPEAT_TEXT

    def test_unknown_choice_means_auto(self):
        assert repeat_marker("nonsense", {}, "win32") == REPEAT_TEXT


class TestIsRepeating:
    @pytest.mark.parametrize("repeat,expected", [
        (500, True), (0.5, True), (0, False), (None, False), (-1, False),
        (True, False), ("500", False),  # normalize_buttons makes numbers ints
    ])
    def test_values(self, repeat, expected):
        assert is_repeating({"repeat": repeat}) is expected

    def test_missing(self):
        assert not is_repeating({})


class TestButtonLabel:
    def test_marker_leads_in_its_own_colour(self):
        label = button_label("Poll", REPEAT_SYMBOL)
        assert label.plain == f"{REPEAT_SYMBOL} Poll"
        [span] = label.spans
        assert (span.start, span.end) == (0, 1)
        assert "$text-accent" in str(span.style)

    def test_running_marker_takes_the_label_colour(self):
        """The running button is $accent; an accent marker would vanish into it."""
        [span] = button_label("Poll", REPEAT_SYMBOL, running=True).spans
        assert "accent" not in str(span.style)

    def test_fallback_text(self):
        assert button_label("Poll", REPEAT_TEXT).plain == "[R] Poll"

    def test_no_marker(self):
        label = button_label("Ping")
        assert label.plain == "Ping" and not label.spans

    def test_label_is_literal_not_markup(self):
        assert button_label("[bold]x[/]", REPEAT_TEXT).plain == "[R] [bold]x[/]"


def marker_settings(isolated_cwd, choice):
    (isolated_cwd / "settings.yml").write_text(yaml.dump({"repeat_marker": choice}))


def poll_and_ping(app):
    return app.query_one("#btn-poll", ControlButton), app.query_one("#btn-ping", ControlButton)


class TestButtonsShowTheMarker:
    async def test_only_repeating_buttons_are_marked(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)  # btn-poll repeats every 500 ms, btn-ping doesn't
        marker_settings(isolated_cwd, "symbol")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll, ping = poll_and_ping(app)
            assert poll.label.plain == f"{REPEAT_SYMBOL} Poll"
            assert ping.label.plain == "Ping"

    async def test_text_fallback_setting(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, "text")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert poll_and_ping(app)[0].label.plain == "[R] Poll"

    async def test_running_recolours_the_marker_and_back(self, write_config, make_app,
                                                          isolated_cwd):
        """REGRESSION: Content compares by text only, so assigning the label
        reactive kept the old styling - an accent marker on the accent button."""
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, "symbol")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll, _ = poll_and_ping(app)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            await pilot.pause()
            assert poll.has_class("button-repeating")
            assert "accent" not in str(poll.label.spans[0].style)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            await pilot.pause()
            assert not poll.has_class("button-repeating")
            assert "$text-accent" in str(poll.label.spans[0].style)

    async def test_log_uses_the_plain_label(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, "symbol")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll, _ = poll_and_ping(app)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "Stopped repeating: Poll" in text
            assert REPEAT_SYMBOL not in text

    async def test_stop_all_says_so(self, write_config, make_app):
        """REGRESSION: the message was checked after the loop emptied the
        timers, so it never showed."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll, _ = poll_and_ping(app)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            app._stop_all_repeating_buttons()
            await pilot.pause()
            assert "Stopped all repeating buttons" in "\n".join(
                app.query_one("#tab-ascii LogPanel").lines)
            assert not poll.has_class("button-repeating")


class TestMarkerSetting:
    async def test_changing_it_relabels_saves_and_keeps_repeats_running(
        self, write_config, make_app, isolated_cwd
    ):
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, "symbol")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll, _ = poll_and_ping(app)
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert isinstance(app.screen, SettingsScreen)
            app.screen.query_one("#settings-repeat-marker", Select).value = "text"
            await pilot.pause(0.3)
            poll = app.query_one("#btn-poll", ControlButton)  # rebuilt
            assert poll.label.plain == "[R] Poll"
            assert poll.has_class("button-repeating"), "running highlight restored"
            assert "btn-poll" in app.repeating_buttons
            saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
            assert saved["repeat_marker"] == "text"

    async def test_unreadable_value_means_auto(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, ["not", "a", "choice"])
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.repeat_marker_choice() == "auto"
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert app.screen.query_one("#settings-repeat-marker", Select).value == "auto"

    async def test_regression_r_is_shown_not_parsed_as_markup(self, write_config, make_app,
                                                               isolated_cwd):
        """REGRESSION: "[R]" in a plain string is a markup tag to Textual, so the
        dropdown showed nothing and the note lost the word."""
        write_config(MINIMAL_CONFIG)
        marker_settings(isolated_cwd, "text")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f2")
            await pilot.pause(0.2)
            shown = app.screen.query_one("#settings-repeat-marker #label").render()
            assert str(shown) == REPEAT_TEXT
            notes = " ".join(str(note.render()) for note in app.screen.query(".settings-note"))
            assert f"Pick {REPEAT_TEXT} if" in notes
