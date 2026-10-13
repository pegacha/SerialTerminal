"""Log colours by kind, the Settings screen (F2), and readable selections."""

import pytest
import yaml
from rich.style import Style
from textual.widgets import Select

from serialterminal.ui.widgets.log_panel import (
    DEFAULT_LOG_COLORS, KINDS, LogPanel, kind_for_type, resolve_color,
)
from serialterminal.ui.widgets.settings_screen import COLOR_CHOICES, SettingsScreen, color_options
from tests.conftest import MINIMAL_CONFIG

THEME = {"primary": "#88C0D0", "success": "#A3BE8C", "foreground-muted": "#D8DEE999",
         "background": "#2E3440"}


class TestResolveColor:
    def test_theme_variable(self):
        assert resolve_color("$primary", THEME).hex == "#88C0D0"

    def test_hex_and_names(self):
        assert resolve_color("#FF5555", THEME).hex == "#FF5555"
        assert resolve_color("red", THEME) is not None

    def test_translucent_colors_are_blended_onto_the_background(self):
        color = resolve_color("$foreground-muted", THEME, THEME["background"])
        assert color.a == 1
        assert color.hex not in ("#D8DEE9", "#2E3440"), "between text and background"

    @pytest.mark.parametrize("bad", ["", None, 5, "$no-such-variable", "not a colour"])
    def test_unusable_values(self, bad):
        assert resolve_color(bad, THEME) is None

    @pytest.mark.parametrize("type,kind", [("tx", "tx"), ("rx", "rx"), ("error", "error"),
                                           ("seq_comment", "sequence"), ("info", "system"),
                                           ("", "system")])
    def test_message_types_map_to_kinds(self, type, kind):
        assert kind_for_type(type) == kind


def line_color(panel: LogPanel, y: int):
    strip = panel._render_line_strip(y, Style())
    colors = {seg.style.color for seg in strip if seg.text.strip() and seg.style}
    assert len(colors) == 1, colors
    return colors.pop()


class TestLogPanelColors:
    async def test_each_kind_has_its_own_color(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for data, type in ((b"PING", "tx"), (b"PONG", "rx"), ("Note", "info"),
                               ("Bad", "error"), ("Auto", "seq_comment")):
                app.log_message(data, type)
            await pilot.pause()
            panel = app.query_one("#tab-hex LogPanel", LogPanel)
            colors = [line_color(panel, y) for y in range(5)]
            assert len({c.name for c in colors}) == 5, "five kinds, five colours"
            variables = app.get_css_variables()
            assert colors[0].triplet.hex.upper() == resolve_color("$primary", variables).hex
            assert colors[1].triplet.hex.upper() == resolve_color("$success", variables).hex

    async def test_every_line_of_a_multiline_frame_is_coloured(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.log_message(b"LINE1\r\nLINE2\r\n", "rx")
            app.log_message("after", "info")
            await pilot.pause()
            panel = app.query_one("#tab-ascii LogPanel", LogPanel)
            assert panel._line_kinds == ["rx", "rx", "system"]
            assert line_color(panel, 0) == line_color(panel, 1) != line_color(panel, 2)

    async def test_kinds_stay_aligned_when_old_lines_are_dropped(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#tab-hex LogPanel", LogPanel)
            panel.max_lines = 3
            for i in range(10):
                panel.write_message(f"entry {i}", "tx" if i % 2 else "rx")
            assert len(panel._line_kinds) == len(panel._lines) == 3
            assert panel._line_kinds == ["tx", "rx", "tx"]  # entries 7, 8, 9

    async def test_filtering_keeps_the_colours(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.log_message(b"PING", "tx")
            app.log_message(b"PONG", "rx")
            await pilot.pause()
            panel = app.query_one("#tab-ascii LogPanel", LogPanel)
            panel.set_filter("pong")
            assert panel._line_kinds == ["rx"]
            panel.set_filter("")
            assert panel._line_kinds == ["tx", "rx"]


class TestSettingsStore:
    async def test_defaults(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        assert app.log_colors() == DEFAULT_LOG_COLORS

    async def test_set_saves_and_applies(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.log_message(b"PING", "tx")
            app.set_log_color("tx", "#FF5555")
            await pilot.pause()
            assert line_color(app.query_one("#tab-hex LogPanel", LogPanel), 0).triplet.hex.upper() == "#FF5555"
        saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
        assert saved["log_colors"]["tx"] == "#FF5555"

    async def test_unparseable_value_falls_back_to_the_default(self, write_config, make_app,
                                                                isolated_cwd):
        write_config(MINIMAL_CONFIG)
        (isolated_cwd / "settings.yml").write_text(yaml.dump({"log_colors": {"tx": "nonsense"}}))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.log_message(b"PING", "tx")
            await pilot.pause()
            expected = resolve_color("$primary", app.get_css_variables())
            assert line_color(app.query_one("#tab-hex LogPanel", LogPanel), 0).triplet.hex.upper() == expected.hex

    async def test_theme_change_recolours(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.log_message(b"PING", "tx")
            await pilot.pause()
            panel = app.query_one("#tab-hex LogPanel", LogPanel)
            app.theme = "nord"
            await pilot.pause()
            nord = line_color(panel, 0)
            app.theme = "textual-light"
            await pilot.pause()
            assert line_color(panel, 0) != nord


class TestSettingsScreen:
    async def open(self, app, pilot):
        await pilot.press("f2")
        await pilot.pause(0.2)
        assert isinstance(app.screen, SettingsScreen)
        return app.screen

    async def test_shows_current_values(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = await self.open(app, pilot)
            assert screen.query_one("#settings-theme", Select).value == app.theme
            for kind in KINDS:
                assert screen.query_one(f"#settings-color-{kind}", Select).value == DEFAULT_LOG_COLORS[kind]

    async def test_picking_a_color_applies_and_saves(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = await self.open(app, pilot)
            screen.query_one("#settings-color-rx", Select).value = "#50FA7B"
            await pilot.pause()
            assert app.log_colors()["rx"] == "#50FA7B"
            saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
            assert saved["log_colors"]["rx"] == "#50FA7B"

    async def test_picking_a_theme_applies_and_saves(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = await self.open(app, pilot)
            screen.query_one("#settings-theme", Select).value = "dracula"
            await pilot.pause()
            assert app.theme == "dracula"
            assert yaml.safe_load((isolated_cwd / "settings.yml").read_text())["ui"]["theme"] == "dracula"

    async def test_reset_restores_defaults(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.set_log_color("tx", "#FF5555")
            screen = await self.open(app, pilot)
            await pilot.click("#settings-reset")
            await pilot.pause()
            assert app.log_colors() == DEFAULT_LOG_COLORS
            assert screen.query_one("#settings-color-tx", Select).value == "$primary"

    @pytest.mark.parametrize("key", ["escape", None])
    async def test_closes(self, write_config, make_app, key):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await self.open(app, pilot)
            if key:
                await pilot.press(key)
            else:
                await pilot.click("#settings-close")
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    def test_custom_values_from_settings_yml_are_offered(self):
        assert ("Custom: #123456", "#123456") in color_options("#123456")
        assert color_options("$primary") == COLOR_CHOICES


class TestSelection:
    async def test_regression_selected_log_text_stays_visible(self, write_config, make_app):
        """REGRESSION: themes leave the selection foreground transparent and Log
        drew selected text in it, so highlighting text made it vanish."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            style = app.screen.get_component_rich_style("screen--selection")
            assert style.color is not None
            foreground = resolve_color("$foreground", app.get_css_variables())
            assert style.color.triplet.hex.upper() == foreground.hex
            assert style.bgcolor is not None and style.color != style.bgcolor


# ----------------------------------------------------------------------------
# Short or verbose COM errors
# ----------------------------------------------------------------------------

class TestComErrors:
    """Short by default; the system's text and a hint with Verbose errors on."""

    REFUSED = "could not open port 'COM_X': PermissionError(13, 'Access is denied.', None, 5)"

    async def failed_connect(self, app, pilot, monkeypatch):
        import serial

        def refuse(*args, **kwargs):
            raise serial.SerialException(self.REFUSED)

        select = app.query_one("#serial-port-select", Select)
        select.set_options([("No port", "none"), ("COM_X", "COM_X")])
        select.value = "COM_X"
        monkeypatch.setattr(app.serial_conn, "connect", refuse)
        monkeypatch.setattr("sys.platform", "win32")
        app._connect_serial()
        await pilot.pause()
        return "\n".join(app.query_one("#tab-ascii LogPanel").lines)

    async def test_short_by_default(self, write_config, make_app, monkeypatch):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert not app.verbose_errors()
            text = await self.failed_connect(app, pilot, monkeypatch)
            assert "Error: couldn't open COM_X" in text
            assert "PermissionError" not in text and "another program" not in text

    async def test_verbose_adds_detail_and_hint(self, write_config, make_app, monkeypatch):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.set_verbose_errors(True)
            text = await self.failed_connect(app, pilot, monkeypatch)
            assert "Error: couldn't open COM_X: could not open port" in text
            assert "another program" in text

    async def test_detail_always_reaches_the_log_file(self, write_config, make_app, monkeypatch,
                                                      isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await self.failed_connect(app, pilot, monkeypatch)
        log_text = (isolated_cwd / "serialterminal.log").read_text(encoding="utf-8")
        assert "Access is denied" in log_text

    async def test_settings_checkbox_toggles_and_saves(self, write_config, make_app, isolated_cwd):
        from textual.widgets import Checkbox

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f2")
            await pilot.pause(0.2)
            box = app.screen.query_one("#settings-verbose-errors", Checkbox)
            assert box.value is False
            box.value = True
            await pilot.pause()
            assert app.verbose_errors()
        assert yaml.safe_load((isolated_cwd / "settings.yml").read_text())["verbose_errors"] is True

    async def test_regression_failed_auto_reply_is_not_logged_as_sent(self, write_config, make_app):
        """REGRESSION: sequence replies ignored a failed write and logged [TX]
        for bytes that never left - the bug already fixed for normal sends."""
        from tests.fakes import FakeSerialConnection

        class Refusing(FakeSerialConnection):
            def write(self, data):
                return 0

        config = dict(MINIMAL_CONFIG)  # has an ACK sequence answering 06 with 06
        write_config(config)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.serial_conn = Refusing()
            app._on_frame_received(b"\x06")
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-hex LogPanel").lines)
            assert "[TX]" not in text
            assert "auto-reply 'ACK' not sent" in text


# ----------------------------------------------------------------------------
# Settings must open, whatever the theme or saved values
# ----------------------------------------------------------------------------

class TestSettingsNeverCrashes:
    async def test_regression_opens_under_every_builtin_theme(self, write_config, make_app,
                                                               isolated_cwd):
        """REGRESSION: in the ANSI themes a colour's hex is a name like
        'ansi_blue'; the previews stylized with it and opening F2 crashed."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for theme in sorted(app.available_themes):
                app.theme = theme
                await pilot.pause()
                await pilot.press("f2")
                await pilot.pause(0.1)
                assert isinstance(app.screen, SettingsScreen), theme
                await pilot.press("escape")
                await pilot.pause()
            assert app.return_code is None

    async def test_log_colours_work_in_ansi_themes(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            if "ansi-dark" not in app.available_themes:
                pytest.skip("this Textual has no ANSI themes")  # added after 8.2.0
            app.theme = "ansi-dark"
            app.log_message(b"PING", "tx")
            app.log_message("note", "info")
            await pilot.pause()
            panel = app.query_one("#tab-hex LogPanel", LogPanel)
            panel._render_line_strip(0, Style())
            panel._render_line_strip(1, Style())

    async def test_custom_gap_from_project_yml_is_shown(self, write_config, make_app):
        config = dict(MINIMAL_CONFIG, serial=dict(MINIMAL_CONFIG["serial"], frame_gap=75))
        write_config(config)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert app.screen.query_one("#settings-gap", Select).value == "75"

    async def test_gap_from_settings_is_saved_with_the_project(self, write_config, make_app,
                                                              isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("f2")
            await pilot.pause(0.2)
            app.screen.query_one("#settings-gap", Select).value = "100"
            await pilot.pause()
        assert yaml.safe_load((isolated_cwd / "project.yml").read_text())["serial"]["frame_gap"] == 100

    async def test_gap_is_no_longer_in_the_serial_bar(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert not app.query("#serial-gap")


# ----------------------------------------------------------------------------
# The dialog fits short terminals; failed saves are reported
# ----------------------------------------------------------------------------

class TestSettingsFits:
    @pytest.mark.parametrize("size", [(80, 16), (80, 24), (120, 40)])
    async def test_regression_close_stays_on_screen(self, write_config, make_app, size):
        """REGRESSION: each new section made the dialog taller, until Close and
        Reset sat below the bottom border and couldn't be clicked."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=size) as pilot:
            await pilot.press("f2")
            await pilot.pause(0.2)
            box = app.screen.query_one("#settings").region
            for button in ("#settings-close", "#settings-reset"):
                region = app.screen.query_one(button).region
                assert box.y < region.y < box.bottom - 1, (button, region, box)
            await pilot.click("#settings-close")
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)


class TestFailedSavesAreReported:
    async def test_settings_yml(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            seen = []
            app.notify = lambda message, **kwargs: seen.append((message, kwargs))
            app.settings_file = isolated_cwd  # a directory: open() fails
            app.set_verbose_errors(True)
            assert app.verbose_errors(), "still applied"
            [(message, kwargs)] = seen
            assert "couldn't save" in message and kwargs["severity"] == "error"

    async def test_project_yml(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            seen = []
            app.notify = lambda message, **kwargs: seen.append((message, kwargs))
            app.config_unreadable = "simulated"
            app.set_frame_gap("100")
            assert app.frame_gap() == "100", "still applied"
            [(message, _)] = seen
            assert "project.yml" in message

    async def test_success_is_quiet(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            seen = []
            app.notify = lambda message, **kwargs: seen.append(message)
            app.set_verbose_errors(True)
            app.set_frame_gap("100")
            assert seen == []


# ----------------------------------------------------------------------------
# Fields stand out from their panels
# ----------------------------------------------------------------------------

def contrast(a, b) -> float:
    """WCAG contrast ratio: 1.0 for identical colours."""
    def luminance(c):
        def channel(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b)
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def weakest_field(screen):
    ratios = []
    for field in screen.query("Input, TextArea, SelectCurrent"):
        if all(node.display for node in field.ancestors_with_self if hasattr(node, "display")):
            behind, own = field.background_colors
            ratios.append((contrast(behind, own), field.parent.id or field.id))
    return min(ratios)


class TestFieldContrast:
    """REGRESSION: Textual paints fields $surface, the colour of every dialog
    panel here, so in F2, the button editor and the file dialogs inputs and
    dropdowns were indistinguishable from the panel (contrast 1.0)."""

    # Measured at 1.19 for the weakest built-in theme (solarized) and 1.48 for
    # gruvbox once tinted; 1.00 before.
    FLOOR = 1.15

    @pytest.mark.parametrize("theme", ["gruvbox", "textual-dark", "textual-light",
                                       "solarized-light", "rose-pine-dawn"])
    async def test_fields_differ_from_what_they_sit_on(self, write_config, make_app, theme):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.theme = theme
            await pilot.pause()
            assert weakest_field(app.screen)[0] >= self.FLOOR, "main screen"
            await pilot.press("f2")
            await pilot.pause(0.2)
            assert weakest_field(app.screen)[0] >= self.FLOOR, "settings"
            await pilot.press("escape")
            await pilot.press("ctrl+n")
            await pilot.pause(0.3)
            assert weakest_field(app.screen)[0] >= self.FLOOR, "button editor"
