import logging
from collections import deque

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.css.query import NoMatches
from textual.widgets import TabbedContent, TabPane, Log, Input, Static
from serialterminal.utils.formatting import (
    timestamp,
    format_log_message,
    format_log_message_ascii,
    format_log_message_hex,
    format_log_message_decimal,
    format_log_message_binary,
)

log = logging.getLogger("serialterminal.logpanel")

# Entries kept per tab for re-filtering and for redrawing after a pause.
HISTORY_LIMIT = 20_000


class LogPanel(Log):
    """Individual log panel for each format.

    Keeps every entry it was given, not just the visible ones, so a filter can
    be changed or cleared, and a pause lifted, without losing anything.
    """

    def __init__(self, **kwargs):
        # Cap the widget's own line buffer too. Only the entry history was
        # capped, so Log's lines grew for as long as the app ran - hours of
        # polling meant unbounded memory and an ever slower view.
        kwargs.setdefault("max_lines", HISTORY_LIMIT)
        self._entries = deque(maxlen=HISTORY_LIMIT)
        self._filter = ""
        # Kept incrementally so the status line can show a live count on every
        # entry without rescanning up to HISTORY_LIMIT entries each time.
        self._match_count = 0
        self.paused = False
        super().__init__(**kwargs)

    def write_message(self, message: str):
        """Record an already-formatted entry and show it if it should be visible.

        Named write_message, not log: MessagePump.log is a property holding
        Textual's own logger, and overriding it with a method breaks any
        internal `self.log.debug(...)` call on this widget.
        """
        if len(self._entries) == self._entries.maxlen and self._matches(self._entries[0]):
            self._match_count -= 1  # the oldest entry is about to be evicted
        self._entries.append(message)
        matched = self._matches(message)
        if matched:
            self._match_count += 1
        if self.paused or not matched:
            return
        self.write_line(message)
        self._scroll_to_end()

    def _matches(self, entry: str) -> bool:
        if not self._filter:
            return True
        # Skip the leading "[HH:MM:SS.mmm] ": otherwise "41" on the HEX tab
        # matches every entry logged at second :41. The [TX]/[RX] tag stays
        # searchable.
        if entry.startswith("[") and "] " in entry:
            entry = entry.split("] ", 1)[1]
        return self._filter in entry.lower()

    def set_filter(self, text: str):
        """Show only entries containing `text` (case-insensitive); '' shows all."""
        self._filter = text.lower()
        self._match_count = sum(1 for entry in self._entries if self._matches(entry))
        self.redraw()

    @property
    def match_count(self) -> int:
        return self._match_count

    def redraw(self):
        """Rebuild the view from the stored entries."""
        super().clear()
        self.write_lines([entry for entry in self._entries if self._matches(entry)])
        self._scroll_to_end()

    def clear(self):
        """Forget every entry, not just the visible ones."""
        self._entries.clear()
        self._match_count = 0
        return super().clear()

    def _scroll_to_end(self):
        """Attempt to scroll log to the end."""
        try:
            if hasattr(self, "scroll_end"):
                self.scroll_end()
            elif hasattr(self, "scroll_to_end"):
                self.scroll_to_end()
            elif hasattr(self, "action_scroll_end"):
                self.action_scroll_end()
        except Exception:
            pass


class MultiFormatLog(Container):
    """Tabbed log panel with multiple format views (ASCII, HEX, Decimal, Binary).

    Also owns the log's filter box and a status line for capture, pause and
    filter state, so all three are visible where the traffic is.
    """

    BINDINGS = [
        Binding("escape", "close_filter", "close filter", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "multi-format-log"
        self.paused = False
        self._pending = 0
        self._filter_text = ""
        self._recording = None

    def compose(self) -> ComposeResult:
        """Compose the tabbed log interface."""
        with TabbedContent(id="log-tabs"):
            with TabPane("ASCII", id="tab-ascii"):
                yield LogPanel()
            with TabPane("HEX", id="tab-hex"):
                yield LogPanel()
            with TabPane("Decimal", id="tab-decimal"):
                yield LogPanel()
            with TabPane("Binary", id="tab-binary"):
                yield LogPanel()
        yield Input(
            placeholder="Filter log (case-insensitive, each tab matches its own text) - Esc closes",
            id="log-filter",
            compact=True,
        )
        # markup=False: filter text and file names may contain [brackets].
        yield Static("", id="log-status", markup=False)

    def on_mount(self):
        self.query_one("#log-filter", Input).display = False
        self._update_status()

    def _panels(self):
        return list(self.query(LogPanel))

    def log_message(self, message, type: str = '', stamp: str = None):
        """
        Log a message to all format tabs.

        Args:
            message: The message to log (can be bytes or str)
            type: Message type ('tx', 'rx', 'error', 'seq_comment', or '')
            stamp: Timestamp to use; defaults to now. The app passes one so a
                session capture and the screen agree on when a frame arrived.
        """
        type_map = {
            'tx': '[TX] ',
            'rx': '[RX] ',
            'error': '[Error] ',
            'seq_comment': '[Sequence] '
        }
        type_prefix = type_map.get(type, '')

        # One timestamp for the whole frame. Each formatter used to call
        # datetime.now() itself, so the same frame was stamped four times and
        # the tabs disagreed about when it arrived.
        stamp = stamp if stamp is not None else timestamp()

        try:
            # For TX/RX messages, format in all encoding types
            if type in ('tx', 'rx'):
                # Format the data first, then add prefix
                ascii_msg = format_log_message_ascii(message, stamp)
                hex_msg = format_log_message_hex(message, stamp)
                dec_msg = format_log_message_decimal(message, stamp)
                bin_msg = format_log_message_binary(message, stamp)

                # Add type prefix after timestamp
                ascii_msg = self._add_prefix_after_timestamp(ascii_msg, type_prefix)
                hex_msg = self._add_prefix_after_timestamp(hex_msg, type_prefix)
                dec_msg = self._add_prefix_after_timestamp(dec_msg, type_prefix)
                bin_msg = self._add_prefix_after_timestamp(bin_msg, type_prefix)

                self.query_one("#tab-ascii LogPanel").write_message(ascii_msg)
                self.query_one("#tab-hex LogPanel").write_message(hex_msg)
                self.query_one("#tab-decimal LogPanel").write_message(dec_msg)
                self.query_one("#tab-binary LogPanel").write_message(bin_msg)

            elif type == 'seq_comment':
                # Sequence comments always display as plain text in all tabs
                formatted = format_log_message(message, stamp)
                formatted = self._add_prefix_after_timestamp(formatted, type_prefix)

                self.query_one("#tab-ascii LogPanel").write_message(formatted)
                self.query_one("#tab-hex LogPanel").write_message(formatted)
                self.query_one("#tab-decimal LogPanel").write_message(formatted)
                self.query_one("#tab-binary LogPanel").write_message(formatted)

            else:
                # Non TX/RX messages (errors, info, etc.) only go to ASCII tab
                # or add to all tabs as plain text
                full_message = f"{type_prefix}{message}" if isinstance(message, str) else message
                formatted = format_log_message(full_message, stamp)

                self.query_one("#tab-ascii LogPanel").write_message(formatted)
                self.query_one("#tab-hex LogPanel").write_message(formatted)
                self.query_one("#tab-decimal LogPanel").write_message(formatted)
                self.query_one("#tab-binary LogPanel").write_message(formatted)

        except Exception as e:
            # Fallback logging
            log.error("Error logging message: %s", e)
            return

        if self.paused:
            self._pending += 1
        if self.paused or self._filter_text:
            # Live: the match count used to update only when the filter or tab
            # changed, so it went stale while traffic kept arriving.
            self._update_status()

    def _add_prefix_after_timestamp(self, formatted_msg: str, prefix: str) -> str:
        """
        Add a prefix after the timestamp in a formatted message.
        Converts: "[12:34:56.789] data" -> "[12:34:56.789] [TX] data"
        """
        if prefix and "] " in formatted_msg:
            parts = formatted_msg.split("] ", 1)
            if len(parts) == 2:
                first, *rest = f"{parts[0]}] {prefix}{parts[1]}".split("\n")
                # Shift continuation lines by the prefix too, so a multi-line
                # ASCII frame stays aligned under its own data column.
                pad = " " * len(prefix)
                return "\n".join([first] + [pad + line for line in rest])
        return formatted_msg

    def clear(self):
        """Clear all log panels."""
        try:
            for panel in self._panels():
                panel.clear()
        except Exception as e:
            log.error("Error clearing logs: %s", e)
        self._pending = 0
        self._update_status()

    # ------------------------------------------------------------------
    # Pause
    # ------------------------------------------------------------------

    def set_paused(self, paused: bool):
        """Freeze the view; entries keep being recorded and appear on resume."""
        self.paused = paused
        for panel in self._panels():
            panel.paused = paused
            if not paused:
                panel.redraw()
        if not paused:
            self._pending = 0
        self._update_status()

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    @property
    def filter_open(self) -> bool:
        return bool(self.query_one("#log-filter", Input).display)

    def open_filter(self):
        box = self.query_one("#log-filter", Input)
        box.display = True
        box.focus()

    def close_filter(self):
        box = self.query_one("#log-filter", Input)
        box.value = ""
        box.display = False
        self.set_filter("")

    def set_filter(self, text: str):
        self._filter_text = text
        for panel in self._panels():
            panel.set_filter(text)
        self._update_status()

    @on(Input.Changed, "#log-filter")
    def _filter_changed(self, event: Input.Changed):
        event.stop()
        self.set_filter(event.value)

    @on(Input.Submitted, "#log-filter")
    def _filter_submitted(self, event: Input.Submitted):
        # Stop here so Enter in the filter box never reaches quick send.
        event.stop()

    def action_close_filter(self):
        if not self.filter_open:
            return
        self.close_filter()
        try:
            self.app.query_one("#quick-send-input").focus()
        except NoMatches:
            pass

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event):
        self._update_status()

    # ------------------------------------------------------------------
    # Status line
    # ------------------------------------------------------------------

    def set_recording(self, name):
        """Show (or with None, hide) the capture indicator."""
        self._recording = name
        self._update_status()

    def _active_panel(self):
        try:
            active = self.query_one("#log-tabs", TabbedContent).active
            return self.query_one(f"#{active} LogPanel", LogPanel) if active else None
        except NoMatches:
            return None

    def _update_status(self):
        parts = []
        if self._recording:
            parts.append(f"● REC {self._recording}")
        if self.paused:
            parts.append(f"⏸ PAUSED (+{self._pending} new)")
        if self._filter_text:
            panel = self._active_panel()
            count = panel.match_count if panel is not None else 0
            parts.append(f"filter {self._filter_text!r}: {count} matching")
        try:
            status = self.query_one("#log-status", Static)
        except NoMatches:
            return
        status.update("  │  ".join(parts))
        status.display = bool(parts)
