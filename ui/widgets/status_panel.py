from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Container

class StatusPanel(Container):
    """Status display panel showing connection and version info."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "status-window"
        self.border_title = "Status"  
    
    def compose(self) -> ComposeResult:
        with Container(id="status-content"):
            yield Static("Disconnected", id="status-connection", classes="status-item")
            yield Static("SW Version: ---", id="status-sw-version", classes="status-item")
            yield Static("HW Version: ---", id="status-hw-version", classes="status-item")
    
    def update_connection(self, connected: bool):
        """Update connection status display."""
        try:
            status_widget = self.query_one("#status-connection", Static)
            if connected:
                status_widget.update("[#00ff00]Connected[/#00ff00]")
            else:
                status_widget.update("[#d2691e]Disconnected[/#d2691e]")
        except:
            pass
    
    def update_versions(self, sw_ver: str, hw_ver: str):
        """Update version info display."""
        try:
            sw_widget = self.query_one("#status-sw-version", Static)
            hw_widget = self.query_one("#status-hw-version", Static)
            sw_widget.update(f"SW Version: [#ff8c00]{sw_ver}[/#ff8c00]")
            hw_widget.update(f"HW Version: [#ff8c00]{hw_ver}[/#ff8c00]")
        except:
            pass
