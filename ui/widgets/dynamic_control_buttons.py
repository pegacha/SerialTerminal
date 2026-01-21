from textual.app import ComposeResult
from textual.widgets import Button, Static
from textual.containers import Container, Horizontal
from pathlib import Path
import yaml


class DynamicControlButtons(Container):
    """Control buttons panel dynamically loaded from YAML configuration."""
    
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
        
        if config_data is not None:
            # Load from provided data (unified config)
            self.buttons_config = config_data
        elif self.config_file:
            # Load from file (legacy support)
            self._load_config()
    
    def _load_config(self):
        """Load button configuration from YAML file (legacy support)."""
        try:
            if self.config_file and self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f)
                    self.buttons_config = config.get('buttons', [])
                print(f"Loaded {len(self.buttons_config)} buttons from {self.config_file}")
            else:
                print(f"Button config file not found: {self.config_file}")
                self.buttons_config = []
        except Exception as e:
            print(f"Error loading button config: {e}")
            self.buttons_config = []
    
    def compose(self) -> ComposeResult:
        """Compose the buttons based on YAML configuration."""
        if not self.buttons_config:
            yield Static("No buttons configured. Edit config.yml", id="no-buttons-msg")
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
                button.repeat = btn_config.get('repeat', None)  # Repeat interval in ms
                
                yield button
    
    def reload_config(self, config_data: list = None):
        """
        Reload configuration from data or file.
        
        Args:
            config_data: Optional list of button dictionaries from unified config
        """
        if config_data is not None:
            # Load from provided data
            self.buttons_config = config_data
            print(f"Reloaded {len(self.buttons_config)} buttons from config data")
        elif self.config_file:
            # Load from file (legacy)
            self._load_config()
        else:
            print("Cannot reload: no config source available")
        
        # Trigger a refresh
        self.refresh(recompose=True)
    
    def get_button_config(self, button_id: str) -> dict:
        """Get configuration for a specific button."""
        for btn in self.buttons_config:
            if btn.get('id') == button_id:
                return btn
        return {}