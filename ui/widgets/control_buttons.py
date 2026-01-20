from textual.app import ComposeResult
from textual.widgets import Button
from textual.containers import Container, Horizontal

class ControlButtons(Container):
    """Control button panel with 2x2 grid."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "button-container"
        self.border_title = "Controls"  
    
    def compose(self) -> ComposeResult:
        with Container(id="button-box"):
            with Horizontal(classes="button-row"):
                yield Button("Version", id="btn1", variant="primary")
                yield Button("Report", id="btn2", variant="primary")
                yield Button("Button 3", id="btn3", variant="primary")
                yield Button("Button 4", id="btn4", variant="primary")
                yield Button("Button 5", id="btn5", variant="primary")
