from textual.app import ComposeResult
from textual.widgets import Static, Button, Select, Input
from textual.containers import Container, Horizontal

class SerialBar(Container):
    """Serial port configuration bar."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "serial-bar"
        self.border_title = "Serial Config"  
    
    def compose(self) -> ComposeResult:
        with Horizontal(id="serial-inputs"):
            yield Select(
                options=[("None", "none")],
                value="none",
                id="serial-port-select",
                allow_blank=False
            )
            yield Input(placeholder="57600", value="57600", id="baud-rate", classes="serial-input")
            yield Static("●", id="serial-status", classes="status-disconnected")

        with Horizontal(id="serial-controls"):
            yield Button("Connect", id="serial-connect", classes="serial-button")
            yield Button("Disc.", id="serial-disconnect", classes="serial-button", disabled=True)
            yield Button("Refresh", id="refresh-ports", classes="serial-button")
