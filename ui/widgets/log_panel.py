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
    
    def log_message(self, message: str, type: str = ''):
        """
        Log a message to all format tabs.
        
        Args:
            message: The message to log
            type: Message type ('tx', 'rx', 'error', or '')
        """
        type_map = {
            'tx': '[TX] ',
            'rx': '[RX] ',
            'error': '[Error] '
        }
        type_str = type_map.get(type, '')
        full_message = f"{type_str}{message}"
        
        try:
            # For TX/RX messages, format in all encoding types
            if type in ('tx', 'rx'):
                ascii_msg = format_log_message_ascii(full_message)
                hex_msg = format_log_message_hex(full_message)
                dec_msg = format_log_message_decimal(full_message)
                bin_msg = format_log_message_binary(full_message)
                
                self.query_one("#tab-ascii LogPanel").log(ascii_msg)
                self.query_one("#tab-hex LogPanel").log(hex_msg)
                self.query_one("#tab-decimal LogPanel").log(dec_msg)
                self.query_one("#tab-binary LogPanel").log(bin_msg)
            else:
                # Non TX/RX messages (errors, info, etc.) only go to ASCII tab
                formatted = format_log_message(full_message)
                self.query_one("#tab-ascii LogPanel").log(formatted)
                # Optionally, you can also log to other tabs as plain text
                # or skip them entirely. Here we'll add them to all tabs:
                self.query_one("#tab-hex LogPanel").log(formatted)
                self.query_one("#tab-decimal LogPanel").log(formatted)
                self.query_one("#tab-binary LogPanel").log(formatted)
                
        except Exception as e:
            # Fallback logging
            print(f"Error logging message: {e}")
    
    def clear(self):
        """Clear all log panels."""
        try:
            self.query_one("#tab-ascii LogPanel").clear()
            self.query_one("#tab-hex LogPanel").clear()
            self.query_one("#tab-decimal LogPanel").clear()
            self.query_one("#tab-binary LogPanel").clear()
        except Exception as e:
            print(f"Error clearing logs: {e}")