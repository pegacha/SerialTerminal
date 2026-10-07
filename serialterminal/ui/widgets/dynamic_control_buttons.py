from textual import events
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Static
from textual.containers import Container, Horizontal, ItemGrid
from pathlib import Path
import logging
import re
import yaml

log = logging.getLogger("serialterminal.buttons")

# Beyond this a label is ellipsised (full text on hover) rather than one
# long label widening every column: 28 fits three columns at 100 wide.
MAX_COLUMN_WIDTH = 28

# Ids the app's own widgets use. A control button sharing one would be routed
# as that widget - a button with id "serial-connect" would connect the port.
RESERVED_IDS = frozenset({
    "buttons-container", "buttons-toolbar", "new-button", "edit-buttons",
    "control-buttons", "log-filter", "log-status",
    "log-tabs", "multi-format-log", "no-buttons-msg", "quick-send-horizontal",
    "quick-send-input", "quick-send-window", "refresh-ports", "send-button",
    "send-checksum", "send-format-select", "send-line-ending", "serial-bar",
    "serial-baud", "serial-bits", "serial-connect", "serial-disconnect",
    "serial-parity", "serial-port-select", "serial-row-bottom",
    "serial-row-top", "serial-status", "serial-stop-bits", "tab-ascii",
    "tab-binary", "tab-decimal", "tab-hex", "title",
})

_NOT_ID_CHAR = re.compile(r"[^A-Za-z0-9_-]")


def _widget_id(raw, index: int) -> str:
    """A legal Textual id derived from the configured one.

    Textual ids are letters, digits, '_' and '-', not starting with a digit.
    """
    text = _NOT_ID_CHAR.sub("-", str(raw).strip()) if raw is not None else ""
    if not text:
        return f"button-{index + 1}"
    if text[0].isdigit():
        text = "btn-" + text
    return text


def normalize_buttons(raw) -> tuple[list[dict], list[str]]:
    """Turn the configured `buttons` section into entries safe to mount.

    project.yml is hand-edited (Ctrl+O), and a single bad entry used to crash
    the app outright - at startup, or on reload mid-session. Instead every
    problem is repaired or skipped and described, so the panel still comes up
    and the user is told what to fix:

    - a section that is not a list, or entries that are not mappings: skipped
    - ids that are missing, illegal for Textual, duplicated or reserved by the
      app: replaced with a legal unique id
    - a `repeat` that isn't a number: treated as a one-shot button

    The returned dicts are copies; the caller's config, which is what gets
    saved back to project.yml, is never altered.

    Returns:
        (buttons, problems) - problems are messages fit to show the user.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"'buttons' must be a list, got {type(raw).__name__} - no buttons loaded"]

    buttons, problems, seen = [], [], set(RESERVED_IDS)
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            problems.append(f"Button {i + 1} is {type(entry).__name__}, not a mapping - skipped")
            continue
        entry = dict(entry)
        configured = entry.get('id')
        widget_id = _widget_id(configured, i)
        if widget_id in seen:
            base, n = widget_id, 2
            while f"{base}-{n}" in seen:
                n += 1
            widget_id = f"{base}-{n}"
        if configured is not None and widget_id != str(configured):
            problems.append(f"Button {i + 1} id {configured!r} is unusable "
                            f"(duplicate, reserved or illegal) - using {widget_id!r}")
        seen.add(widget_id)
        entry['id'] = widget_id

        repeat = entry.get('repeat')
        if repeat not in (None, ""):
            try:
                entry['repeat'] = int(float(repeat))
            except (TypeError, ValueError):
                problems.append(f"Button {i + 1} repeat {repeat!r} is not a number "
                                "of milliseconds - sending once instead")
                entry['repeat'] = 0
        buttons.append(entry)

    for message in problems:
        log.warning(message)
    return buttons, problems


class ControlButton(Button):
    """A configured button. Left-click sends it; right-click opens it in the editor.

    `source_index` is the entry's position in project.yml's `buttons` list, so
    the editor writes back to the right entry even when ids were repaired.
    """

    def __init__(self, *args, source_index: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_index = source_index

    async def _on_click(self, event: events.Click) -> None:
        if event.button == 3:
            # Right-click edits and never sends. Some terminals keep the right
            # button for themselves, which is why Edit mode exists as well.
            event.stop()
            self.post_message(DynamicControlButtons.EditRequested(self.source_index))
            return
        # Button._on_click is a coroutine: calling it without awaiting does
        # nothing, so a left-click would silently not send.
        await super()._on_click(event)


class DynamicControlButtons(Container):
    """Control buttons panel dynamically loaded from YAML configuration."""

    class EditRequested(Message):
        """Open the button editor: `index` into project.yml's buttons, or None for a new one."""

        def __init__(self, index: int | None):
            super().__init__()
            self.index = index

    def __init__(self, config_file: str = None, config_data: list = None, **kwargs):
        """
        Initialize DynamicControlButtons.
        
        Args:
            config_file: Path to YAML file (legacy support)
            config_data: List of button dictionaries from unified config
        """
        super().__init__(**kwargs)
        self.id = "control-buttons"
        self.border_title = "Control Buttons"
        self.config_file = Path(config_file) if config_file else None
        self.buttons_config = []
        self.source_indices: list[int] = []
        self.problems: list[str] = []
        # Edit mode: clicking a button opens it in the editor instead of
        # sending it. Survives rebuilds, so you can edit one button after
        # another.
        self.editing = False

        if config_data is not None:
            # Load from provided data (unified config)
            self._set_buttons(config_data)
        elif self.config_file:
            # Load from file (legacy support)
            self._load_config()

    def _set_buttons(self, raw):
        """Normalise `raw` (see normalize_buttons) and remember what was wrong."""
        self.buttons_config, self.problems = normalize_buttons(raw)
        # normalize_buttons keeps every mapping entry, in order, and skips the
        # rest - so this lines each normalised button up with its source entry.
        self.source_indices = (
            [i for i, entry in enumerate(raw) if isinstance(entry, dict)]
            if isinstance(raw, list) else []
        )

    async def rebuild(self, raw):
        """Show `raw` (the buttons section) and wait until it's on screen."""
        self._set_buttons(raw)
        await self.recompose()

    def set_editing(self, editing: bool):
        self.editing = editing
        self.set_class(editing, "-editing")
        self.border_title = ("Control Buttons · click one to edit" if editing
                             else "Control Buttons")
        try:
            self.query_one("#edit-buttons", Button).label = "Done" if editing else "Edit"
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "new-button":
            event.stop()
            self.post_message(self.EditRequested(None))
        elif event.button.id == "edit-buttons":
            event.stop()
            self.set_editing(not self.editing)
        elif self.editing and isinstance(event.button, ControlButton):
            event.stop()  # edit, don't send
            self.post_message(self.EditRequested(event.button.source_index))

    def _load_config(self):
        """Load button configuration from YAML file (legacy support)."""
        try:
            if self.config_file and self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                self._set_buttons(config.get('buttons', []) if isinstance(config, dict) else [])
                log.debug("Loaded %d buttons from %s", len(self.buttons_config), self.config_file)
            else:
                log.debug("Button config file not found: %s", self.config_file)
                self._set_buttons([])
        except Exception as e:
            log.error("Error loading button config: %s", e)
            self._set_buttons([])
    
    def compose(self) -> ComposeResult:
        """Compose the buttons based on YAML configuration."""
        with Horizontal(id="buttons-toolbar"):
            yield Button("+ New", id="new-button", classes="toolbar-button", compact=True,
                         tooltip="Create a button (Ctrl+N)")
            yield Button("Done" if self.editing else "Edit", id="edit-buttons",
                         classes="toolbar-button", compact=True,
                         tooltip="Edit mode: click a button to edit it instead of "
                                 "sending it. Right-clicking a button also edits it.")

        if not self.buttons_config:
            yield Static("No buttons yet - press + New (Ctrl+N) or import a config (Ctrl+T)",
                         id="no-buttons-msg")
            return
        
        # A Horizontal never wraps, so buttons past the right edge were cut
        # off unseen, and fixed 12-column buttons truncated labels until
        # e.g. "LIGHT RELAY ON" and "LIGHT RELAY OFF" looked identical. ItemGrid
        # wraps; columns are sized to the longest label (capped) so every
        # label shows in full.
        longest = max(len(str(b.get('label', 'Button'))) for b in self.buttons_config)
        with ItemGrid(id="buttons-container",
                      min_column_width=min(longest + 4, MAX_COLUMN_WIDTH)):
            for btn_config, source_index in zip(self.buttons_config, self.source_indices):
                button_id = btn_config['id']  # always legal and unique after normalising
                label = str(btn_config.get('label', 'Button'))
                tooltip = btn_config.get('tooltip', '')
                if not tooltip and len(label) + 4 > MAX_COLUMN_WIDTH:
                    tooltip = label  # it may be ellipsised; hover shows it whole

                button = ControlButton(
                    label,
                    id=button_id,
                    classes="control-button",
                    tooltip=tooltip if tooltip else None,
                    compact=True,
                    source_index=source_index,
                )
                # Store message and format as attributes
                button.message = btn_config.get('message', '')
                button.format = btn_config.get('format', 'ascii')
                button.repeat = btn_config.get('repeat', None)  # Repeat interval in ms
                button.checksum = btn_config.get('checksum', 'none')
                button.line_ending = btn_config.get('line_ending', 'none')
                
                yield button
    
    def reload_config(self, config_data: list = None):
        """
        Reload configuration from data or file.
        
        Args:
            config_data: Optional list of button dictionaries from unified config
        """
        if config_data is not None:
            # Load from provided data
            self._set_buttons(config_data)
            log.debug("Reloaded %d buttons from config data", len(self.buttons_config))
        elif self.config_file:
            # Load from file (legacy)
            self._load_config()
        else:
            log.debug("Cannot reload: no config source available")
        
        # Trigger a refresh
        self.refresh(recompose=True)
    
    def get_button_config(self, button_id: str) -> dict:
        """Get configuration for a specific button."""
        for btn in self.buttons_config:
            if btn.get('id') == button_id:
                return btn
        return {}