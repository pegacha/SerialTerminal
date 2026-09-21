from textual.app import ComposeResult
from textual.widgets import Static, Button, Select, Input
from textual.containers import Container, Horizontal


class QuickSend(Container):
    """Quick send single command with format selection"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "quick-send-window"
        self.border_title = "Send Command"  
    
    def compose(self) -> ComposeResult:
        with Horizontal(id="quick-send-horizontal"):
            yield Button("→", id="send-button", classes="quick-send-button")
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
            )
            yield Input(
                placeholder="Enter command...",
                id="quick-send-input",
            )