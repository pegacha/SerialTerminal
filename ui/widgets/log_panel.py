from textual.widgets import Log
from utils.formatting import format_log_message

class LogPanel(Log):
    """Enhanced log widget with auto-scrolling."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "log-window"
        self.border_title = "Log"  
    
    def log(self, message: str):
        """Write a timestamped message to the log."""
        formatted_message = format_log_message(message)
        self.write_line(formatted_message)
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
