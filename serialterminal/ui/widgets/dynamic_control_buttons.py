from textual.app import ComposeResult
from textual.widgets import Button, Static
from textual.containers import Container, ItemGrid
from pathlib import Path
import logging
import yaml

log = logging.getLogger("serialterminal.buttons")

# Beyond this a label is ellipsised (full text on hover) rather than one
# long label widening every column: 28 fits three columns at 100 wide.
MAX_COLUMN_WIDTH = 28


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
                log.debug("Loaded %d buttons from %s", len(self.buttons_config), self.config_file)
            else:
                log.debug("Button config file not found: %s", self.config_file)
                self.buttons_config = []
        except Exception as e:
            log.error("Error loading button config: %s", e)
            self.buttons_config = []
    
    def compose(self) -> ComposeResult:
        """Compose the buttons based on YAML configuration."""
        if not self.buttons_config:
            yield Static("No buttons configured. Edit project.yml (Ctrl+O)", id="no-buttons-msg")
            return
        
        # A Horizontal never wraps, so buttons past the right edge were cut
        # off unseen, and fixed 12-column buttons truncated labels until
        # e.g. "LIGHT RELAY ON" and "LIGHT RELAY OFF" looked identical. ItemGrid
        # wraps; columns are sized to the longest label (capped) so every
        # label shows in full.
        longest = max(len(str(b.get('label', 'Button'))) for b in self.buttons_config)
        with ItemGrid(id="buttons-container",
                      min_column_width=min(longest + 4, MAX_COLUMN_WIDTH)):
            for btn_config in self.buttons_config:
                button_id = btn_config.get('id', 'btn-unknown')
                label = str(btn_config.get('label', 'Button'))
                tooltip = btn_config.get('tooltip', '')
                if not tooltip and len(label) + 4 > MAX_COLUMN_WIDTH:
                    tooltip = label  # it may be ellipsised; hover shows it whole

                button = Button(
                    label,
                    id=button_id,
                    classes="control-button",
                    tooltip=tooltip if tooltip else None,
                    compact=True,
                )
                # Store message and format as attributes
                button.message = btn_config.get('message', '')
                button.format = btn_config.get('format', 'ascii')
                button.repeat = btn_config.get('repeat', None)  # Repeat interval in ms
                button.checksum = btn_config.get('checksum', 'none')
                button.line_ending = btn_config.get('line_ending', 'none')
                
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
            log.debug("Reloaded %d buttons from config data", len(self.buttons_config))
        elif self.config_file:
            # Load from file (legacy)
            self._load_config()
        else:
            log.debug("Cannot reload: no config source available")
        
        # Trigger a refresh
        self.refresh(recompose=True)
    
    def get_button_config(self, button_id: str) -> dict:
        """Get configuration for a specific button."""
        for btn in self.buttons_config:
            if btn.get('id') == button_id:
                return btn
        return {}