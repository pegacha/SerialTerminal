"""The button editor: create, edit and delete control buttons.

Modelled on Docklight's Sequence Definition dialog - 1 - Name, 2 - Sequence
(with an edit mode that converts the sequence between ASCII, HEX, Decimal and
Binary, and a byte position indicator), 3 - Additional settings on tabs, a
documentation box, and Delete / OK / Cancel / Apply / Help. Everything it
edits is a field of the button's entry in project.yml; the app writes it back
there.
"""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Checkbox, Input, Label, RadioButton, RadioSet, Rule, Select, Static,
    TabbedContent, TabPane, TextArea,
)
from textual.widgets.select import InvalidSelectValueError

from serialterminal.sequence_handler import ReceiveSequence
from serialterminal.utils.checksum import CHECKSUMS
from serialterminal.utils.payload import (
    FORMATS, LINE_ENDINGS, config_message, editor_byte_position,
    format_editor_text, parse_editor_text, parse_payload,
)

MODE_LABELS = {"ascii": "ASCII", "hex": "HEX", "decimal": "Decimal", "binary": "Binary"}

HELP = """\
1 - Name: the button's label.

2 - Sequence: what the button sends. Switching the edit mode converts it.
In ASCII mode, control characters are written <CR>, <LF>, <STX>, <ACK>...
(the names the log uses); use HEX for bytes above 7F.

Repeat: press the button once to start sending every N seconds, again to stop.
Checksum: computed over the sequence and appended to it.
Line ending: added after the checksum; ASCII sequences only.
Auto-send: also send this whenever a matching frame is received.
?? matches any one byte.

Right-click a button, or use Edit mode, to open it here."""


class ButtonEditor(ModalScreen):
    """Create (index None) or edit (index into project.yml's buttons) one button."""

    BINDINGS = [Binding("escape", "cancel", "cancel", show=False)]

    def __init__(self, entry: dict | None = None, index: int | None = None):
        super().__init__()
        self.original = dict(entry) if isinstance(entry, dict) else {}
        self.index = index
        fmt = self.original.get("format", "ascii")
        self.mode = fmt if fmt in FORMATS else "ascii"
        self._saved_state = None
        self._reverting_mode = False
        self._confirm_delete = False
        self._tried_to_save = False

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="editor"):
            with VerticalScroll(id="editor-body"):
                with Horizontal(classes="ed-row"):
                    yield Label("1 - Name", classes="ed-label")
                    yield Input(placeholder="Button label", id="ed-name", compact=True)
                yield Rule(classes="ed-rule")

                with Horizontal(classes="ed-row"):
                    yield Label("2 - Sequence", classes="ed-label")
                    yield Label("Edit mode", classes="ed-sublabel")
                    with RadioSet(id="ed-mode"):
                        for fmt in FORMATS:
                            yield RadioButton(MODE_LABELS[fmt], value=(fmt == self.mode),
                                              id=f"ed-mode-{fmt}")
                    yield Static("", id="ed-pos")
                yield TextArea(id="ed-sequence", soft_wrap=True)
                yield Static("", id="ed-error", markup=False)
                yield Rule(classes="ed-rule")

                with Horizontal(classes="ed-row ed-settings"):
                    yield Label("3 - Additional\n    settings", classes="ed-label")
                    with TabbedContent(id="ed-tabs"):
                        with TabPane("Repeat", id="ed-tab-repeat"):
                            yield Checkbox("Send periodically", id="ed-repeat")
                            yield Static("(if not sent as an automatic answer to a receive "
                                         "sequence)", classes="ed-note ed-note-tight")
                            with Horizontal(classes="ed-inline"):
                                yield Label("Repeat sequence every")
                                yield Input("5", id="ed-repeat-seconds", compact=True,
                                            restrict=r"[0-9]*\.?[0-9]*")
                                yield Label("seconds")
                        with TabPane("Checksum", id="ed-tab-checksum"):
                            yield Select([(label, key) for key, (label, _) in CHECKSUMS.items()],
                                         value="none", allow_blank=False, id="ed-checksum",
                                         compact=True)
                            yield Static("Computed over the sequence and appended to it "
                                         "when it is sent.", classes="ed-note")
                        with TabPane("Line ending", id="ed-tab-eol"):
                            yield Select([(label, key) for key, (label, _) in LINE_ENDINGS.items()],
                                         value="none", allow_blank=False, id="ed-eol", compact=True)
                            yield Static("Appended after the checksum. ASCII sequences only - "
                                         "HEX, Decimal and Binary are sent exactly as written.",
                                         classes="ed-note")
                        with TabPane("Auto-send", id="ed-tab-auto"):
                            yield Checkbox("Send automatically when this is received:",
                                           id="ed-auto")
                            with Horizontal(classes="ed-inline"):
                                yield Select([(MODE_LABELS[f], f) for f in FORMATS], value="hex",
                                             allow_blank=False, id="ed-auto-format", compact=True)
                                yield Input(placeholder="e.g. 05, or ID?? (?? = any byte)",
                                            id="ed-auto-data", compact=True)
                            with Horizontal(classes="ed-inline"):
                                yield Label("Wait")
                                yield Input("0", id="ed-auto-delay", compact=True,
                                            restrict=r"[0-9]*")
                                yield Label("ms before sending")

                yield Label("Documentation  (shown when you hover over the button)",
                            classes="ed-doc-label")
                yield TextArea(id="ed-doc", soft_wrap=True)

            with Horizontal(id="ed-buttons"):
                yield Button("Delete", id="ed-delete", variant="error", compact=True,
                             disabled=self.index is None)
                yield Static(classes="ed-spacer")
                yield Button("OK", id="ed-ok", variant="primary", compact=True)
                yield Button("Cancel", id="ed-cancel", compact=True)
                yield Button("Apply", id="ed-apply", compact=True, disabled=True)
                yield Button("Help", id="ed-help", compact=True)

    def on_mount(self) -> None:
        self._update_title()
        entry = self.original
        self.query_one("#ed-name", Input).value = str(entry.get("label", ""))

        message = entry.get("message", "")
        try:
            text = format_editor_text(parse_payload(message, self.mode), self.mode)
        except ValueError:
            text = str(message)  # shown as-is; validation explains what's wrong
        self.query_one("#ed-sequence", TextArea).load_text(text)

        repeat = entry.get("repeat")
        try:
            repeat_ms = float(repeat) if repeat not in (None, "") else 0
        except (TypeError, ValueError):
            repeat_ms = 0
        self.query_one("#ed-repeat", Checkbox).value = repeat_ms > 0
        if repeat_ms > 0:
            self.query_one("#ed-repeat-seconds", Input).value = f"{repeat_ms / 1000:g}"

        self._select("#ed-checksum", entry.get("checksum", "none"))
        self._select("#ed-eol", entry.get("line_ending", "none"))

        auto = entry.get("auto_send")
        if isinstance(auto, dict):
            receive = auto.get("receive") if isinstance(auto.get("receive"), dict) else {}
            self.query_one("#ed-auto", Checkbox).value = auto.get("enabled", True) is not False
            self._select("#ed-auto-format", receive.get("format", "hex"))
            self.query_one("#ed-auto-data", Input).value = str(receive.get("data", ""))
            self.query_one("#ed-auto-delay", Input).value = str(auto.get("delay", 0) or 0)

        self.query_one("#ed-doc", TextArea).load_text(str(entry.get("tooltip", "")))
        self._sync_enabled()
        self._refresh_feedback()
        self._saved_state = self._state()
        self.query_one("#ed-name", Input).focus()

    def _select(self, widget_id: str, value) -> None:
        try:
            self.query_one(widget_id, Select).value = str(value)
        except InvalidSelectValueError:
            pass  # unknown value in the file: leave the default, validation is not needed

    def _update_title(self) -> None:
        label = self.original.get("label") or "button"
        self.query_one("#editor").border_title = (
            "New button" if self.index is None else f"Edit button: {label}")

    # ------------------------------------------------------------------
    # Reading the form
    # ------------------------------------------------------------------

    def _state(self) -> tuple:
        """Everything the form holds, to tell whether there are unsaved changes."""
        return (
            self.query_one("#ed-name", Input).value,
            self.mode,
            self.query_one("#ed-sequence", TextArea).text,
            self.query_one("#ed-repeat", Checkbox).value,
            self.query_one("#ed-repeat-seconds", Input).value,
            self.query_one("#ed-checksum", Select).value,
            self.query_one("#ed-eol", Select).value,
            self.query_one("#ed-auto", Checkbox).value,
            self.query_one("#ed-auto-format", Select).value,
            self.query_one("#ed-auto-data", Input).value,
            self.query_one("#ed-auto-delay", Input).value,
            self.query_one("#ed-doc", TextArea).text,
        )

    def collect(self, strict: bool = True) -> tuple[dict | None, list[str]]:
        """The button entry the form describes, or None and what's wrong.

        With strict=False, missing-but-required fields aren't reported: that's
        the live check while typing, which shouldn't nag about an empty form.
        """
        errors = []
        name = self.query_one("#ed-name", Input).value.strip()
        if not name and strict:
            errors.append("1 - Name is required")

        text = self.query_one("#ed-sequence", TextArea).text
        data = None
        try:
            data = parse_editor_text(text, self.mode)
            if not data and strict:
                errors.append("2 - Sequence is empty")
        except ValueError as e:
            errors.append(f"2 - Sequence: {e}")

        repeat_ms = None
        if self.query_one("#ed-repeat", Checkbox).value:
            try:
                seconds = float(self.query_one("#ed-repeat-seconds", Input).value)
                if seconds <= 0:
                    raise ValueError
                repeat_ms = max(1, round(seconds * 1000))
            except ValueError:
                errors.append("Repeat: enter a number of seconds above 0")

        auto = None
        if self.query_one("#ed-auto", Checkbox).value:
            pattern = self.query_one("#ed-auto-data", Input).value.strip()
            fmt = self.query_one("#ed-auto-format", Select).value
            delay_text = self.query_one("#ed-auto-delay", Input).value.strip()
            if not pattern:
                if strict:
                    errors.append("Auto-send: enter what to wait for")
            elif ReceiveSequence({"name": "check", "receive": {"data": pattern, "format": fmt}}
                                 ).pattern is None:
                errors.append(f"Auto-send: {pattern!r} isn't valid {MODE_LABELS[fmt]}")
            auto = {"receive": {"data": pattern, "format": fmt},
                    "delay": int(delay_text) if delay_text else 0}

        if errors or data is None:
            return None, errors

        entry = dict(self.original)  # keeps any keys the editor doesn't manage
        entry["label"] = name
        entry["message"] = config_message(data, self.mode)
        entry["format"] = self.mode
        checksum = self.query_one("#ed-checksum", Select).value
        line_ending = self.query_one("#ed-eol", Select).value if self.mode == "ascii" else "none"
        for key, value in (("checksum", checksum), ("line_ending", line_ending)):
            if value == "none":
                entry.pop(key, None)
            else:
                entry[key] = value
        if repeat_ms:
            entry["repeat"] = repeat_ms
        else:
            entry.pop("repeat", None)
        doc = self.query_one("#ed-doc", TextArea).text.strip()
        if doc:
            entry["tooltip"] = doc
        else:
            entry.pop("tooltip", None)
        if auto:
            entry["auto_send"] = auto
        else:
            entry.pop("auto_send", None)
        return entry, []

    # ------------------------------------------------------------------
    # Live feedback
    # ------------------------------------------------------------------

    def _sync_enabled(self) -> None:
        self.query_one("#ed-repeat-seconds", Input).disabled = not self.query_one(
            "#ed-repeat", Checkbox).value
        auto_on = self.query_one("#ed-auto", Checkbox).value
        for widget_id in ("#ed-auto-format", "#ed-auto-data", "#ed-auto-delay"):
            self.query_one(widget_id).disabled = not auto_on
        self.query_one("#ed-eol", Select).disabled = self.mode != "ascii"

    def _refresh_feedback(self) -> None:
        _, errors = self.collect(strict=self._tried_to_save)
        self.query_one("#ed-error", Static).update(
            ("✗ " + "  ·  ".join(errors)) if errors else "")

        area = self.query_one("#ed-sequence", TextArea)
        text = area.text
        row, col = area.cursor_location
        lines = text.split("\n")
        offset = sum(len(line) + 1 for line in lines[:row]) + col
        try:
            total = str(len(parse_editor_text(text, self.mode)))
        except ValueError:
            total = "?"
        position = editor_byte_position(text, self.mode, offset) + 1
        self.query_one("#ed-pos", Static).update(f"Pos. {position} / {total}")

        dirty = self._saved_state is not None and self._state() != self._saved_state
        self.query_one("#ed-apply", Button).disabled = not dirty

    @on(Input.Changed)
    @on(Select.Changed)
    @on(TextArea.Changed)
    @on(TextArea.SelectionChanged)
    def _form_changed(self, event) -> None:
        if self._saved_state is not None:
            self._refresh_feedback()

    @on(Checkbox.Changed)
    def _checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._sync_enabled()
        if self._saved_state is not None:
            self._refresh_feedback()

    @on(RadioSet.Changed, "#ed-mode")
    def _mode_changed(self, event: RadioSet.Changed) -> None:
        new_mode = event.pressed.id.removeprefix("ed-mode-")
        if self._reverting_mode:
            self._reverting_mode = False
            return
        if new_mode == self.mode:
            return
        area = self.query_one("#ed-sequence", TextArea)
        try:
            converted = format_editor_text(parse_editor_text(area.text, self.mode), new_mode)
        except ValueError as e:
            # Stay in the current mode rather than mangle or drop bytes.
            self.query_one("#ed-error", Static).update(
                f"✗ Can't switch to {MODE_LABELS[new_mode]}: {e}")
            self._reverting_mode = True
            self.query_one(f"#ed-mode-{self.mode}", RadioButton).value = True
            return
        self.mode = new_mode
        area.load_text(converted)
        self._sync_enabled()
        self._refresh_feedback()

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    async def _save(self) -> bool:
        self._tried_to_save = True
        entry, errors = self.collect(strict=True)
        if errors:
            self.query_one("#ed-error", Static).update("✗ " + "  ·  ".join(errors))
            return False
        try:
            self.index = await self.app.save_button(self.index, entry)
        except ValueError as e:
            self.query_one("#ed-error", Static).update(f"✗ {e}")
            return False
        self.original = dict(self.app.config["buttons"][self.index])
        self._saved_state = self._state()
        self.query_one("#ed-delete", Button).disabled = False
        self._update_title()
        self._refresh_feedback()
        return True

    @on(Button.Pressed, "#ed-ok")
    async def _ok(self, event: Button.Pressed) -> None:
        event.stop()
        if await self._save():
            self.dismiss()

    @on(Button.Pressed, "#ed-apply")
    async def _apply(self, event: Button.Pressed) -> None:
        event.stop()
        await self._save()

    @on(Button.Pressed, "#ed-cancel")
    def _cancel_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss()

    @on(Button.Pressed, "#ed-delete")
    async def _delete(self, event: Button.Pressed) -> None:
        event.stop()
        if self.index is None:
            return
        button = self.query_one("#ed-delete", Button)
        if not self._confirm_delete:
            # Two clicks, so a stray one can't destroy a button.
            self._confirm_delete = True
            button.label = "Confirm delete"
            return
        await self.app.delete_button(self.index)
        self.dismiss()

    @on(Button.Pressed, "#ed-help")
    def _help(self, event: Button.Pressed) -> None:
        event.stop()
        self.notify(HELP, title="Button editor", timeout=20)
