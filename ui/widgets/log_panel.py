from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import TabbedContent, TabPane, Log
from utils.formatting import (
    format_log_message,
    format_log_message_ascii,
    format_log_message_hex,
    format_log_message_decimal,
    format_log_message_binary,
)


class LogPanel(Log):
    """Individual log panel for each format."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def log(self, message: str):
        """Write a timestamped message to the log."""
        self.write_line(message)
        self._scroll_to_end()
    
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
    """Tabbed log panel with multiple format views (ASCII, HEX, Decimal, Binary)."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "multi-format-log"
    
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
    
    def log_message(self, message, type: str = ''):
        """
        Log a message to all format tabs.
        
        Args:
            message: The message to log (can be bytes or str)
            type: Message type ('tx', 'rx', 'error', 'seq_comment', or '')
        """
        type_map = {
            'tx': '[TX] ',
            'rx': '[RX] ',
            'error': '[Error] ',
            'seq_comment': '[Sequence] '
        }
        type_prefix = type_map.get(type, '')
        
        try:
            # For TX/RX messages, format in all encoding types
            if type in ('tx', 'rx'):
                # Format the data first, then add prefix
                ascii_msg = format_log_message_ascii(message)
                hex_msg = format_log_message_hex(message)
                dec_msg = format_log_message_decimal(message)
                bin_msg = format_log_message_binary(message)
                
                # Add type prefix after timestamp
                ascii_msg = self._add_prefix_after_timestamp(ascii_msg, type_prefix)
                hex_msg = self._add_prefix_after_timestamp(hex_msg, type_prefix)
                dec_msg = self._add_prefix_after_timestamp(dec_msg, type_prefix)
                bin_msg = self._add_prefix_after_timestamp(bin_msg, type_prefix)
                
                self.query_one("#tab-ascii LogPanel").log(ascii_msg)
                self.query_one("#tab-hex LogPanel").log(hex_msg)
                self.query_one("#tab-decimal LogPanel").log(dec_msg)
                self.query_one("#tab-binary LogPanel").log(bin_msg)
                
            elif type == 'seq_comment':
                # Sequence comments always display as plain text in all tabs
                formatted = format_log_message(message)
                formatted = self._add_prefix_after_timestamp(formatted, type_prefix)
                
                self.query_one("#tab-ascii LogPanel").log(formatted)
                self.query_one("#tab-hex LogPanel").log(formatted)
                self.query_one("#tab-decimal LogPanel").log(formatted)
                self.query_one("#tab-binary LogPanel").log(formatted)
                
            else:
                # Non TX/RX messages (errors, info, etc.) only go to ASCII tab
                # or add to all tabs as plain text
                full_message = f"{type_prefix}{message}" if isinstance(message, str) else message
                formatted = format_log_message(full_message)
                
                self.query_one("#tab-ascii LogPanel").log(formatted)
                self.query_one("#tab-hex LogPanel").log(formatted)
                self.query_one("#tab-decimal LogPanel").log(formatted)
                self.query_one("#tab-binary LogPanel").log(formatted)
                
        except Exception as e:
            # Fallback logging
            print(f"Error logging message: {e}")

    def _add_prefix_after_timestamp(self, formatted_msg: str, prefix: str) -> str:
        """
        Add a prefix after the timestamp in a formatted message.
        Converts: "[12:34:56.789] data" -> "[12:34:56.789] [TX] data"
        """
        if prefix and "] " in formatted_msg:
            parts = formatted_msg.split("] ", 1)
            if len(parts) == 2:
                return f"{parts[0]}] {prefix}{parts[1]}"
        return formatted_msg
        
    def clear(self):
        """Clear all log panels."""
        try:
            self.query_one("#tab-ascii LogPanel").clear()
            self.query_one("#tab-hex LogPanel").clear()
            self.query_one("#tab-decimal LogPanel").clear()
            self.query_one("#tab-binary LogPanel").clear()
        except Exception as e:
            print(f"Error clearing logs: {e}")