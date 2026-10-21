"""Keyboard shortcuts that type control characters (ASCII 0-31).

In any field where you enter data to send - Send Command, and the button
editor's sequence and auto-send pattern - a shortcut inserts its character in
the field's current notation: <CR> in ASCII, 0D in HEX, 13 in Decimal,
00001101 in Binary. They are set in Settings (F2) > Control characters, kept in
settings.yml as `control_shortcuts: {13: ctrl+enter, ...}`, like Docklight's
Control Character Shortcuts.

A shortcut is whatever key name the terminal delivers, so it is assigned by
pressing it: a key the terminal can't tell apart (Ctrl+Enter from Enter in
some terminals) shows up as the key it really sends, and is refused if taken.
"""

from typing import Callable

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static, TextArea

from serialterminal.utils.formatting import CONTROL_NAMES
from serialterminal.utils.payload import control_text

# Docklight's defaults.
DEFAULT_SHORTCUTS = {13: "ctrl+enter", 10: "ctrl+shift+enter"}

# What terminals without the kitty keyboard protocol deliver instead of a key:
# Windows Terminal sends Ctrl+Enter as a line feed, which Textual names ctrl+j
# (measured). A shortcut set to the key on the right also answers to the left.
ENTER_ALIASES = {"ctrl+j": "ctrl+enter"}

# Keys that can never be shortcuts: they edit text, move the cursor or focus,
# or are the terminal's own codes for other keys (Ctrl+M is Enter, Ctrl+I Tab,
# Ctrl+H Backspace, Ctrl+[ Escape in classic terminals).
_ALWAYS_RESERVED = {
    "enter", "tab", "shift+tab", "escape", "backspace", "delete", "insert", "space",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "ctrl+m", "ctrl+i", "ctrl+h", "ctrl+left_square_bracket", "ctrl+p",
}


def binding_keys(*classes) -> set[str]:
    """Every key bound by `classes` (their BINDINGS, comma lists split)."""
    keys = set()
    for cls in classes:
        for binding in getattr(cls, "BINDINGS", []):
            key = binding.key if isinstance(binding, Binding) else binding[0]
            keys.update(k.strip() for k in key.split(","))
    return keys


def reserved_keys(app) -> set[str]:
    """Keys a shortcut may not use: the app's own and those of text fields."""
    from textual.app import App
    from textual.screen import Screen
    return (_ALWAYS_RESERVED | binding_keys(type(app), App, Screen, Input, TextArea)
            | {getattr(App, "COMMAND_PALETTE_BINDING", "ctrl+p")})


def pretty_key(key: str) -> str:
    """ctrl+shift+enter -> Ctrl+Shift+Enter, for display."""
    return "+".join(part.capitalize() for part in key.split("+")) if key else ""


def shortcut_problem(key: str, code: int, shortcuts: dict[int, str], reserved: set[str]) -> str | None:
    """Why `key` can't be the shortcut for `code`, or None if it can."""
    parts = key.split("+")
    modifiers = set(parts[:-1])
    if not modifiers & {"ctrl", "alt", "super", "meta"} and not parts[-1].startswith("f"):
        return f"{pretty_key(key)} types text; use Ctrl, Alt or a function key with it"
    if key in reserved:
        return f"{pretty_key(key)} is already used by SerialTerminal or for editing text"
    for other, other_key in shortcuts.items():
        if other_key == key and other != code:
            return f"{pretty_key(key)} already types {CONTROL_NAMES[other]}"
    return None


def clean_shortcuts(raw) -> dict[int, str]:
    """settings.yml's control_shortcuts, or the defaults if it has none."""
    if not isinstance(raw, dict):
        return dict(DEFAULT_SHORTCUTS)
    shortcuts = {}
    for code, key in raw.items():
        try:
            code = int(code)
        except (TypeError, ValueError):
            continue
        if 0 <= code < 32 and isinstance(key, str) and key and key not in shortcuts.values():
            shortcuts[code] = key
    return shortcuts


# ----------------------------------------------------------------------------
# Text fields that act on the shortcuts
# ----------------------------------------------------------------------------

class _ControlKeys:
    """Mixin: insert a control character when its shortcut is pressed.

    `notation` returns the field's current notation (ascii/hex/decimal/binary).
    """

    def _control_code(self, key: str) -> int | None:
        lookup = getattr(self.app, "control_code_for_key", None)
        return lookup(key) if lookup else None

    def _control_insertion(self, code: int, before: str) -> str:
        fmt = self.notation() if self.notation else "ascii"
        text = control_text(code, fmt)
        if fmt != "ascii":
            # Numeric notations are space-separated tokens.
            if before and not before[-1].isspace():
                text = " " + text
            text += " "
        return text


class ControlKeyInput(_ControlKeys, Input):
    def __init__(self, *args, notation: Callable[[], str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.notation = notation

    async def _on_key(self, event: events.Key) -> None:
        code = self._control_code(event.key)
        if code is None:
            await super()._on_key(event)
            return
        event.stop()
        event.prevent_default()
        self.insert_text_at_cursor(
            self._control_insertion(code, self.value[:self.cursor_position]))


class ControlKeyTextArea(_ControlKeys, TextArea):
    def __init__(self, *args, notation: Callable[[], str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.notation = notation

    async def _on_key(self, event: events.Key) -> None:
        code = self._control_code(event.key)
        if code is None or self.read_only:
            await super()._on_key(event)
            return
        event.stop()
        event.prevent_default()
        row, column = self.cursor_location
        before = self.document.get_line(row)[:column]
        self.insert(self._control_insertion(code, before))


# ----------------------------------------------------------------------------
# Settings: the table of shortcuts
# ----------------------------------------------------------------------------

class KeyCaptureScreen(ModalScreen):
    """Waits for one key and returns its name; Escape cancels, Delete clears."""

    def __init__(self, title: str):
        super().__init__()
        self.title_text = title

    def compose(self) -> ComposeResult:
        with Vertical(id="key-capture"):
            yield Static(Content(self.title_text), id="key-capture-title")
            yield Static("Press the shortcut now.  Esc cancels, Delete clears it.",
                         id="key-capture-hint")

    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in ("delete", "backspace"):
            self.dismiss("")
        else:
            self.dismiss(event.key)


class ControlKeysScreen(ModalScreen):
    """Settings > Control characters: codes 0-31 and their shortcuts."""

    BINDINGS = [Binding("escape", "close", "close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="control-keys"):
            yield Static("A shortcut types its character wherever you enter data to send: "
                         "Send Command and the button editor.", classes="settings-note")
            yield DataTable(id="control-keys-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="control-keys-status")
            with Horizontal(id="control-keys-buttons"):
                yield Button("Set...", id="control-keys-set", variant="primary", compact=True)
                yield Button("Clear", id="control-keys-clear", compact=True)
                yield Button("Defaults", id="control-keys-defaults", compact=True,
                             tooltip="Ctrl+Enter for CR, Ctrl+Shift+Enter for LF")
                yield Static(classes="settings-spacer")
                yield Button("Close", id="control-keys-close", compact=True)

    def on_mount(self) -> None:
        self.query_one("#control-keys").border_title = "Control character shortcuts"
        table = self.query_one(DataTable)
        table.add_columns("Dec", "Hex", "Char", "Shortcut")
        self._fill()
        table.focus()

    def _fill(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        shortcuts = self.app.control_shortcuts()
        for code in range(32):
            table.add_row(str(code), f"{code:02X}", CONTROL_NAMES[code].strip("<>"),
                          pretty_key(shortcuts.get(code, "")), key=str(code))
        table.move_cursor(row=row)

    def _selected_code(self) -> int:
        return self.query_one(DataTable).cursor_row

    def _status(self, text: str, error: bool = False) -> None:
        status = self.query_one("#control-keys-status", Static)
        status.update(Content(text))
        status.set_class(error, "-error")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._capture()

    def _capture(self) -> None:
        code = self._selected_code()
        name = CONTROL_NAMES[code]

        def captured(key):
            if key is None:
                return
            if key == "":
                self.app.set_control_shortcut(code, None)
                self._status(f"{name}: shortcut cleared.")
            else:
                problem = shortcut_problem(key, code, self.app.control_shortcuts(),
                                           reserved_keys(self.app))
                if problem:
                    self._status(problem + ".", error=True)
                    return
                self.app.set_control_shortcut(code, key)
                self._status(f"{pretty_key(key)} now types {name}.")
            self._fill()

        self.app.push_screen(KeyCaptureScreen(f"Shortcut for {name} (decimal {code})"), captured)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button = event.button.id
        if button == "control-keys-set":
            self._capture()
        elif button == "control-keys-clear":
            code = self._selected_code()
            self.app.set_control_shortcut(code, None)
            self._status(f"{CONTROL_NAMES[code]}: shortcut cleared.")
            self._fill()
        elif button == "control-keys-defaults":
            self.app.reset_control_shortcuts()
            self._status("Back to the defaults.")
            self._fill()
        elif button == "control-keys-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
