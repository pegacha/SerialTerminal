from textual.app import ComposeResult
from textual.widgets import Button, Static
from textual.containers import Container, Horizontal, Vertical, Grid, HorizontalScroll
from pathlib import Path
import yaml


class DynamicControlButtons(Container):
    """Control buttons panel dynamically loaded from YAML configuration."""
    
    def __init__(self, config_file: str = "buttons.yml", **kwargs):
        super().__init__(**kwargs)
        self.id = "control-buttons"
        self.border_title = "Controls"
        self.config_file = Path(config_file)
        self.buttons_config = []
        self._load_config()
    
    def _load_config(self):
        """Load button configuration from YAML file."""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f)
                    self.buttons_config = config.get('buttons', [])
        
        except Exception as e:
            print(f"Error loading button config: {e}")
            self.buttons_config = []
    
    
    def compose(self) -> ComposeResult:
        """Compose the buttons based on YAML configuration."""
        if not self.buttons_config:
            yield Static("No buttons configured. Check buttons.yml", id="no-buttons-msg")
            return
        
        # Use a simple container with horizontal layout that will wrap
        with Horizontal(id="buttons-container"):
            for btn_config in self.buttons_config:
                button_id = btn_config.get('id', 'btn-unknown')
                label = btn_config.get('label', 'Button')
                tooltip = btn_config.get('tooltip', '')
                
                button = Button(
                    label,
                    id=button_id,
                    classes="control-button",
                    tooltip=tooltip if tooltip else None
                )
                # Store message and format as attributes
                button.message = btn_config.get('message', '')
                button.format = btn_config.get('format', 'ascii')
                
                yield button
    
    def reload_config(self):
        """Reload configuration from YAML file."""
        self._load_config()
        # Trigger a refresh
        self.refresh(recompose=True)
    
    def get_button_config(self, button_id: str) -> dict:
        """Get configuration for a specific button."""
        for btn in self.buttons_config:
            if btn.get('id') == button_id:
                return btn
        return {}