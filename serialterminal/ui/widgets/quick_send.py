from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.validation import ValidationResult, Validator
from textual.widgets import Button, Select, Input
from textual.containers import Container, Horizontal

from serialterminal.utils.checksum import CHECKSUMS
from serialterminal.ui.control_keys import ControlKeyInput
from serialterminal.utils.payload import LINE_ENDINGS, expand_control_names, parse_payload

FORMATS = ("ascii", "hex", "decimal", "binary")
MAX_HISTORY = 100


def clean_history(raw) -> list[dict]:
    """Sent commands from settings.yml, dropping anything malformed."""
    if not isinstance(raw, list):
        return []
    return [{"text": entry["text"], "format": entry["format"]} for entry in raw
            if isinstance(entry, dict) and isinstance(entry.get("text"), str)
            and entry.get("format") in FORMATS][-MAX_HISTORY:]


class PayloadValidator(Validator):
    """Checks the input against whichever format is currently selected."""

    def __init__(self, get_format):
        super().__init__()
        self._get_format = get_format

    def validate(self, value: str) -> ValidationResult:
        fmt = self._get_format()
        try:
            parse_payload(expand_control_names(value) if fmt == "ascii" else value, fmt)
        except ValueError as e:
            return self.failure(str(e))
        return self.success()


class QuickSend(Container):
    """Quick send single command with format, line ending and checksum selection.

    Up and Down in the box step through the commands sent before, like a
    shell's history. Each entry brings back its format too: a hex command
    recalled under ASCII would not send what it did.
    """

    BINDINGS = [
        Binding("up", "history(-1)", "previous command", show=False),
        Binding("down", "history(1)", "next command", show=False),
    ]

    def __init__(self, history: list | None = None, **kwargs):
        super().__init__(**kwargs)
        self.id = "quick-send-window"
        self.border_title = "Send Command"
        # Oldest first. The caller's list is kept and appended to, so it can
        # persist it (settings.yml).
        self.history = history if history is not None else []
        self._position: int | None = None  # None: editing a new command
        self._draft = {"text": "", "format": "ascii"}

    def compose(self) -> ComposeResult:
        with Horizontal(id="quick-send-horizontal"):
            yield Button("Send", id="send-button", classes="quick-send-button", compact=True)
            yield Select(
                [
                    ("ASCII", "ascii"),
                    ("HEX", "hex"),
                    ("Decimal", "decimal"),
                    ("Binary", "binary"),
                ],
                value="ascii",
                id="send-format-select",
                allow_blank=False,
                compact=True,
            )
            yield Select(
                [(label, key) for key, (label, _) in LINE_ENDINGS.items()],
                value="none",
                id="send-line-ending",
                allow_blank=False,
                compact=True,
                tooltip="Appended after the checksum. ASCII only - hex, decimal "
                        "and binary frames are sent exactly as written.",
            )
            yield Select(
                [(label, key) for key, (label, _) in CHECKSUMS.items()],
                value="none",
                id="send-checksum",
                allow_blank=False,
                compact=True,
                tooltip="Computed over the payload and appended as raw bytes.",
            )
            yield ControlKeyInput(
                placeholder="Enter command...",
                notation=self._current_format,
                id="quick-send-input",
                validators=[PayloadValidator(self._current_format)],
                validate_on=["changed", "submitted"],
                compact=True,
            )

    def remember(self, text: str, format: str) -> None:
        """Add a sent command to the history and start a new one."""
        entry = {"text": text, "format": format}
        if text and (not self.history or self.history[-1] != entry):
            self.history.append(entry)
            del self.history[:-MAX_HISTORY]
        self._position = None

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        # Only in the command box; elsewhere (the Send button) the keys do nothing.
        if action == "history":
            return self.query_one("#quick-send-input", Input).has_focus
        return True

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        box = self.query_one("#quick-send-input", Input)
        if self._position is None:
            if step > 0:
                return  # already at the newest: the command being typed
            self._draft = {"text": box.value, "format": self._current_format()}
            position = len(self.history) - 1
        else:
            position = max(0, self._position + step)
        if position >= len(self.history):
            self._position, entry = None, self._draft
        else:
            self._position, entry = position, self.history[position]
        self.query_one("#send-format-select", Select).value = entry["format"]
        box.value = entry["text"]
        box.cursor_position = len(box.value)

    def _current_format(self) -> str:
        try:
            return self.query_one("#send-format-select", Select).value
        except Exception:
            return "ascii"

    def options(self) -> dict:
        """The selected settings, as keyword arguments for TUIApp._send_command."""
        return {
            "format_override": self._current_format(),
            "line_ending": self.query_one("#send-line-ending", Select).value,
            "checksum": self.query_one("#send-checksum", Select).value,
        }

    @on(Select.Changed, "#send-format-select")
    def _format_changed(self, event: Select.Changed):
        # The line ending only ever applies to ASCII; say so by disabling it.
        self.query_one("#send-line-ending", Select).disabled = event.value != "ascii"
        box = self.query_one("#quick-send-input", Input)
        self._show_validation(box.validate(box.value))

    @on(Input.Changed, "#quick-send-input")
    def _input_changed(self, event: Input.Changed):
        self._show_validation(event.validation_result)

    def _show_validation(self, result: ValidationResult | None):
        if result is None or result.is_valid:
            self.border_subtitle = ""
        else:
            self.border_subtitle = "✗ " + "; ".join(result.failure_descriptions)
