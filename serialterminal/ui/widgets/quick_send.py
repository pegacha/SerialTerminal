from textual import on
from textual.app import ComposeResult
from textual.validation import ValidationResult, Validator
from textual.widgets import Button, Select, Input
from textual.containers import Container, Horizontal

from serialterminal.utils.checksum import CHECKSUMS
from serialterminal.utils.payload import LINE_ENDINGS, parse_payload


class PayloadValidator(Validator):
    """Checks the input against whichever format is currently selected."""

    def __init__(self, get_format):
        super().__init__()
        self._get_format = get_format

    def validate(self, value: str) -> ValidationResult:
        try:
            parse_payload(value, self._get_format())
        except ValueError as e:
            return self.failure(str(e))
        return self.success()


class QuickSend(Container):
    """Quick send single command with format, line ending and checksum selection"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "quick-send-window"
        self.border_title = "Send Command"

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
            yield Input(
                placeholder="Enter command...",
                id="quick-send-input",
                validators=[PayloadValidator(self._current_format)],
                validate_on=["changed", "submitted"],
                compact=True,
            )

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
