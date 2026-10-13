"""The Settings screen (F2): theme, log colours, frame gap, repeat marker
and verbose errors.

Saved as soon as they change - to settings.yml, or project.yml for the frame
gap - and applied live, so the log behind the dialog shows the effect of each
choice.
"""

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Select, Static

from serialterminal.ui.widgets.dynamic_control_buttons import (
    REPEAT_SYMBOL, REPEAT_TEXT, repeat_marker,
)
from serialterminal.ui.widgets.log_panel import DEFAULT_LOG_COLORS, KINDS, resolve_color

# Theme roles first: they stay readable in light and dark themes and follow a
# theme change. The fixed colours are tuned for dark backgrounds.
COLOR_CHOICES = [
    ("Theme primary", "$primary"),
    ("Theme secondary", "$secondary"),
    ("Theme accent", "$accent"),
    ("Theme success", "$success"),
    ("Theme warning", "$warning"),
    ("Theme error", "$error"),
    ("Theme text", "$foreground"),
    ("Theme muted text", "$foreground-muted"),
    ("Red", "#FF5555"),
    ("Orange", "#FFB86C"),
    ("Yellow", "#F1FA8C"),
    ("Green", "#50FA7B"),
    ("Cyan", "#8BE9FD"),
    ("Blue", "#6CB6FF"),
    ("Purple", "#BD93F9"),
    ("Pink", "#FF79C6"),
    ("White", "#F8F8F2"),
    ("Grey", "#9E9E9E"),
]

GAP_CHOICES = [("Auto", "auto")] + [
    (f"{ms} ms" if ms < 1000 else f"{ms // 1000} s", str(ms))
    for ms in (10, 20, 50, 100, 200, 500, 1000)
]



def marker_options() -> list[tuple[Content, str]]:
    """Auto names what it picks on this terminal.

    Content, not str: a str prompt is parsed as markup, where "[R]" is a tag
    and the option showed as nothing.
    """
    return [(Content(f"Auto ({repeat_marker('auto')})"), "auto"),
            (Content(REPEAT_SYMBOL), "symbol"), (Content(REPEAT_TEXT), "text")]


def gap_options(current: str) -> list[tuple[str, str]]:
    """The gap choices, plus the current value if project.yml holds another one."""
    options = list(GAP_CHOICES)
    if current not in {value for _, value in options}:
        options.append((f"{current} ms (custom)", current))
    return options


KIND_LABELS = {
    "tx": ("Sent (TX)", "[TX] PING<CR><LF>"),
    "rx": ("Received (RX)", "[RX] PONG<CR><LF>"),
    "system": ("System messages", "Connected to COM4"),
    "error": ("Errors", "[Error] Send failed"),
    "sequence": ("Sequence replies", "[Sequence] Sent ACK"),
}


def color_options(current: str) -> list[tuple[str, str]]:
    """The choices, plus the current value if settings.yml holds a custom one."""
    options = list(COLOR_CHOICES)
    if current and current not in {value for _, value in options}:
        options.append((f"Custom: {current}", current))
    return options


def section(title: str) -> Vertical:
    """A group of settings under its title, set in a separating line."""
    group = Vertical(classes="settings-section")
    group.border_title = title
    return group


class SettingsScreen(ModalScreen):
    """Theme and log colours. Everything applies and saves immediately."""

    BINDINGS = [Binding("escape", "close", "close", show=False)]

    def compose(self) -> ComposeResult:
        app = self.app
        colors = app.log_colors()
        with Vertical(id="settings"):
            # The sections scroll; the buttons stay put, so Close is always
            # reachable however short the terminal is.
            with VerticalScroll(id="settings-body"):
                with section("Appearance"):
                    with Horizontal(classes="settings-row"):
                        yield Label("Theme", classes="settings-label")
                        yield Select([(name, name) for name in sorted(app.available_themes)],
                                     value=app.theme, allow_blank=False, compact=True,
                                     id="settings-theme")

                with section("Log colors"):
                    for kind in KINDS:
                        label, _ = KIND_LABELS[kind]
                        with Horizontal(classes="settings-row"):
                            yield Label(label, classes="settings-label")
                            yield Select(color_options(colors[kind]), value=colors[kind],
                                         allow_blank=False, compact=True,
                                         id=f"settings-color-{kind}")
                            yield Static("", id=f"settings-sample-{kind}",
                                         classes="settings-sample")

                with section("Serial"):
                    with Horizontal(classes="settings-row"):
                        yield Label("Frame gap", classes="settings-label")
                        yield Select(gap_options(app.frame_gap()), value=app.frame_gap(),
                                     allow_blank=False, compact=True, id="settings-gap")
                    yield Static("Silence that ends a message. Saved per project.",
                                 classes="settings-note")

                with section("Buttons"):
                    with Horizontal(classes="settings-row"):
                        yield Label("Repeat marker", classes="settings-label")
                        yield Select(marker_options(), value=app.repeat_marker_choice(),
                                     allow_blank=False, compact=True,
                                     id="settings-repeat-marker")
                    # Content: literal, so "[R]" isn't taken for markup.
                    yield Static(Content(f"Pick {REPEAT_TEXT} if {REPEAT_SYMBOL} shows as a box."),
                                 classes="settings-note")

                with section("Errors"):
                    with Horizontal(classes="settings-row"):
                        yield Checkbox("Verbose COM errors", value=app.verbose_errors(),
                                       id="settings-verbose-errors")
                    yield Static("Adds the system's message and a hint.",
                                 classes="settings-note")
            with Horizontal(id="settings-buttons"):
                yield Button("Reset colors", id="settings-reset", compact=True,
                             tooltip="Back to the default log colors")
                yield Static(classes="settings-spacer")
                yield Button("Close", id="settings-close", variant="primary", compact=True)

    # Rows around the scrolling body: border (2) and the button row with its
    # margins (3). CSS can't say "screen height minus the buttons", and an
    # auto-height body simply grew past the screen, pushing Close off it.
    CHROME_ROWS = 5

    def on_mount(self) -> None:
        self.query_one("#settings").border_title = "Settings"
        self._fit_body(self.size.height)
        self._refresh_samples()

    def on_resize(self, event) -> None:
        self._fit_body(event.size.height)

    def _fit_body(self, screen_height: int) -> None:
        self.query_one("#settings-body").styles.max_height = max(
            3, screen_height - self.CHROME_ROWS)

    def _refresh_samples(self) -> None:
        colors = self.app.log_colors()
        variables = self.app.get_css_variables()
        for kind in KINDS:
            sample = Text(KIND_LABELS[kind][1])
            color = resolve_color(colors[kind], variables, variables.get("background"))
            if color is not None:
                # A Rich Style built from the colour, as the log does - not a
                # colour string: in the ANSI themes (ansi-dark, ansi-light) a
                # colour's "hex" is a name like "ansi_blue" that Rich can't
                # parse, and stylizing with it crashed the app on opening F2.
                sample.stylize(Style(color=color.rich_color))
            try:
                self.query_one(f"#settings-sample-{kind}", Static).update(sample)
            except Exception:
                # A preview must never take the app down; show it uncoloured.
                self.query_one(f"#settings-sample-{kind}", Static).update(
                    KIND_LABELS[kind][1])

    async def on_select_changed(self, event: Select.Changed) -> None:
        select_id = event.select.id or ""
        if select_id == "settings-repeat-marker":
            event.stop()
            if isinstance(event.value, str) and event.value != self.app.repeat_marker_choice():
                await self.app.set_repeat_marker(event.value)
        elif select_id == "settings-gap":
            event.stop()
            if isinstance(event.value, str) and event.value != self.app.frame_gap():
                self.app.set_frame_gap(event.value)
        elif select_id == "settings-theme":
            event.stop()
            if isinstance(event.value, str) and event.value != self.app.theme:
                self.app.set_theme(event.value)
                self._refresh_samples()
        elif select_id.startswith("settings-color-"):
            event.stop()
            if isinstance(event.value, str):
                self.app.set_log_color(select_id.removeprefix("settings-color-"), event.value)
                self._refresh_samples()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "settings-verbose-errors":
            event.stop()
            self.app.set_verbose_errors(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-reset":
            event.stop()
            self.app.reset_log_colors()
            for kind in KINDS:
                self.query_one(f"#settings-color-{kind}", Select).value = DEFAULT_LOG_COLORS[kind]
            self._refresh_samples()
        elif event.button.id == "settings-close":
            event.stop()
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
