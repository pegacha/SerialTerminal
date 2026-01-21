from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, Button, Select, Input
from textual.screen import ModalScreen
from textual_fspicker import FileOpen, FileSave, Filters
from pathlib import Path
import serial
import yaml
import shutil

from ui.widgets.log_panel import MultiFormatLog
from ui.widgets.serial_bar import SerialBar
from ui.widgets.dynamic_control_buttons import DynamicControlButtons
from ui.widgets.quick_send import QuickSend

from sequence_handler import SequenceHandler, ReceiveSequence

from serial_comm.connection import SerialConnection
from serial_comm.receiver import SerialReceiver

from utils.formatting import format_frame


class TUIApp(App):

    BINDINGS = [
        Binding("ctrl+q", "quit", "quit", show=True),
        Binding("ctrl+w", "clearlog_message", "clear", show=True),
        Binding("ctrl+o", "edit_config", "edit config", show=True),
        Binding("ctrl+l", "reload_config", "reload config", show=True),
        Binding("ctrl+i", "import_config", "import config", show=True),
        Binding("ctrl+e", "export_config", "export config", show=True),
        Binding("ctrl+r", "reload_css", "reload css", show=False)
    ]

    CSS_PATH = "styles.tcss"

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def __init__(self):
        super().__init__()
        self.serial_conn = SerialConnection()
        self.receiver = SerialReceiver(
            self.serial_conn,
            self._on_frame_received_threadsafe
        )
        
        self.repeating_buttons = {}
        self.config_file = Path("project.yml")
        self.settings_file = Path("settings.yml")
        
        # Load user settings first (theme, preferences)
        self.settings = {}
        self.loadSettings()
        
        # Load working config (serial, buttons, sequences)
        self.config = {}
        self.sequence_handler = None
        self.loadUnifiedConfig()

    def compose(self) -> ComposeResult:
        yield Static("SerialTerm", id="title")
        yield SerialBar()
        yield MultiFormatLog()
        yield QuickSend()
        yield DynamicControlButtons(config_data=self.config.get('buttons', []))
        yield Footer()

    def on_mount(self):
        """Initialize UI components on mount."""
        # Apply loaded theme from settings
        if 'ui' in self.settings and 'theme' in self.settings['ui']:
            self.theme = self.settings['ui']['theme']
        elif 'ui' in self.config and 'theme' in self.config['ui']:
            self.theme = self.config['ui']['theme']

        self.refresh_serial_ports()

        # Apply loaded serial settings to UI
        if 'serial' in self.config:
            try:
                select = self.query_one("#serial-port-select", Select)
                baud_input = self.query_one("#serial-baud", Select)

                port = self.config['serial'].get('port', 'none')
                if port != 'none':
                    select.value = port
                    
                baud_input.value = str(self.config['serial'].get('baud_rate', 115200))

            except Exception as e:
                self.log_message(f"Error applying settings to UI: {e}")

    def on_unmount(self):
        """Clean up on app close."""
        self._stop_all_repeating_buttons()
        self.saveUnifiedConfig()
        self.saveSettings()
        self.receiver.stop()
        self.serial_conn.disconnect()

    # ========================================================================
    # SETTINGS & CONFIG MANAGEMENT
    # ========================================================================

    def loadSettings(self):
        """Load user settings (theme, preferences, etc.)"""
        try:
            if not self.settings_file.exists():
                default_settings = {
                    'ui': {
                        'theme': 'nord'
                    },
                    'config': {
                        'last_used': None
                    }
                }
                with open(self.settings_file, 'w') as f:
                    yaml.dump(default_settings, f, default_flow_style=False)
                self.settings = default_settings
            else:
                with open(self.settings_file, 'r') as f:
                    self.settings = yaml.safe_load(f) or {}
                    
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.settings = {'ui': {'theme': 'nord'}, 'config': {'last_used': None}}

    def saveSettings(self):
        """Save user settings"""
        try:
            # Update theme
            if 'ui' not in self.settings:
                self.settings['ui'] = {}
            self.settings['ui']['theme'] = self.theme
            
            with open(self.settings_file, 'w') as f:
                yaml.dump(self.settings, f, default_flow_style=False)
                
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def loadUnifiedConfig(self):
        """Load unified configuration from project.yml"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    self.config = yaml.safe_load(f) or {}
                
                print(f"Loaded configuration from {self.config_file}")
                
                # Initialize sequence handler if sequences exist
                if 'sequences' in self.config:
                    self.sequence_handler = SequenceHandler(config_data=self.config['sequences'])
                else:
                    self.sequence_handler = SequenceHandler(config_data=[])
                
            else:
                print("No project.yml found - starting with defaults")
                self.config = {
                    'serial': {
                        'port': 'none',
                        'baud_rate': 115200,
                        'parity': 'N',
                        'data_bits': '8',
                        'stop_bits': '1'
                    },
                    'ui': {
                        'theme': 'nord'
                    },
                    'buttons': [],
                    'sequences': []
                }
                self.sequence_handler = SequenceHandler(config_data=[])
                
        except Exception as e:
            print(f"Error loading config: {e}")
            self.config = {}
            self.sequence_handler = SequenceHandler(config_data=[])

    def saveUnifiedConfig(self):
        """Save unified configuration to project.yml"""
        try:
            # Update serial settings from UI if available
            try:
                select = self.query_one("#serial-port-select", Select)
                baud_input = self.query_one("#serial-baud", Select)
                data_bits = self.query_one("#serial-bits", Select)
                serial_parity = self.query_one("#serial-parity", Select)
                serial_stop_bits = self.query_one("#serial-stop-bits", Select)

                if 'serial' not in self.config:
                    self.config['serial'] = {}
                
                self.config['serial']['port'] = select.value
                self.config['serial']['baud_rate'] = int(baud_input.value)
                self.config['serial']['data_bits'] = data_bits.value
                self.config['serial']['parity'] = serial_parity.value
                self.config['serial']['stop_bits'] = serial_stop_bits.value
            except:
                pass

            # Update UI theme
            if 'ui' not in self.config:
                self.config['ui'] = {}
            self.config['ui']['theme'] = self.theme

            # Save to file
            with open(self.config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            
            print(f"Configuration saved to {self.config_file}")
            
        except Exception as e:
            print(f"Error saving config: {e}")

    def validate_config(self, config_data: dict) -> tuple[bool, str]:
        """
        Validate configuration structure.
        
        Returns:
            (is_valid, error_message)
        """
        if not isinstance(config_data, dict):
            return (False, "Config must be a dictionary")
        
        # Validate serial settings if present
        if 'serial' in config_data:
            serial_cfg = config_data['serial']
            if not isinstance(serial_cfg, dict):
                return (False, "Serial section must be a dictionary")
        
        # Validate buttons if present
        if 'buttons' in config_data:
            buttons = config_data['buttons']
            if not isinstance(buttons, list):
                return (False, "Buttons section must be a list")
            for i, btn in enumerate(buttons):
                if 'id' not in btn:
                    return (False, f"Button {i} missing 'id' field")
        
        # Validate sequences if present
        if 'sequences' in config_data:
            sequences = config_data['sequences']
            if not isinstance(sequences, list):
                return (False, "Sequences section must be a list")
            for i, seq in enumerate(sequences):
                if 'name' not in seq:
                    return (False, f"Sequence {i} missing 'name' field")
        
        return (True, "")

    # ========================================================================
    # CONFIG ACTIONS (Edit, Reload, Import, Export)
    # ========================================================================

    def action_edit_config(self):
        """Open project.yml in nano editor."""
        import subprocess
        try:
            if not self.config_file.exists():
                self.saveUnifiedConfig()
            
            with self.suspend():
                subprocess.run(['nano', str(self.config_file)])
            
            self.action_reload_config()
            
        except FileNotFoundError:
            self.log_message("nano editor not found", 'error')
        except Exception as e:
            self.log_message(f"Error opening config: {e}", 'error')
            
    def action_reload_config(self):
        """Reload the unified configuration."""
        try:
            self.loadUnifiedConfig()
            
            try:
                control_buttons = self.query_one(DynamicControlButtons)
                control_buttons.reload_config(self.config.get('buttons', []))
            except Exception as e:
                self.log_message(f"Error reloading buttons: {e}", 'error')
            
            self.on_mount()
            
            button_count = len(self.config.get('buttons', []))
            sequence_count = len(self.sequence_handler.get_active_sequences()) if self.sequence_handler else 0
            self.log_message(f"Config reloaded: {button_count} buttons, {sequence_count} sequences", 'info')
            
        except Exception as e:
            self.log_message(f"Error reloading config: {e}", 'error')

        def action_import_config(self):
            """Import configuration from a file using file picker."""
            def handle_file_open(file_path: Path | None) -> None:
                if file_path is None:
                    self.log_message("Import cancelled", 'info')
                    return
                
                try:
                    # Load and validate config
                    with open(file_path, 'r') as f:
                        new_config = yaml.safe_load(f)
                    
                    is_valid, error_msg = self.validate_config(new_config)
                    
                    if not is_valid:
                        self.log_message(f"Invalid config: {error_msg}", 'error')
                        return
                    
                    # Backup current config
                    if self.config:
                        backup_file = Path("project.backup.yml")
                        with open(backup_file, 'w') as f:
                            yaml.dump(self.config, f, default_flow_style=False)
                        self.log_message(f"Backed up to {backup_file.name}", 'info')
                    
                    # Load the new config
                    self.config = new_config
                    self.saveUnifiedConfig()
                    
                    # Update last_used in settings
                    if 'config' not in self.settings:
                        self.settings['config'] = {}
                    self.settings['config']['last_used'] = str(file_path)
                    self.saveSettings()
                    
                    # Reload everything
                    self.action_reload_config()
                    
                    self.log_message(f"Config imported from: {file_path.name}", 'info')
                    
                except yaml.YAMLError as e:
                    self.log_message(f"Invalid YAML: {e}", 'error')
                except Exception as e:
                    self.log_message(f"Error importing: {e}", 'error')
            
            # Show file picker
            file_open_screen = FileOpen(
                ".",  # Starting directory
                filters=Filters(
                    ("YAML files", lambda p: p.suffix.lower() in {".yml", ".yaml"}),
                    ("All files", lambda p: True),
                ),
            )
            self.push_screen(file_open_screen, handle_file_open)

    def action_export_config(self):
        """Export current configuration to a file using file picker."""
        def handle_file_save(file_path: Path | None) -> None:
            if file_path is None:
                self.log_message("Export cancelled", 'info')
                return
            
            try:
                # Ensure .yml extension
                if file_path.suffix.lower() not in {'.yml', '.yaml'}:
                    file_path = file_path.with_suffix('.yml')
                
                # Create parent directory if needed
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Save config
                with open(file_path, 'w') as f:
                    yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
                
                self.log_message(f"Config exported to: {file_path.name}", 'info')
                
                # Update last_used in settings
                if 'config' not in self.settings:
                    self.settings['config'] = {}
                self.settings['config']['last_used'] = str(file_path)
                self.saveSettings()
                
            except Exception as e:
                self.log_message(f"Error exporting: {e}", 'error')
        
        # Show file picker - FileSave just takes the starting directory
        file_save_screen = FileSave(".")
        self.push_screen(file_save_screen, handle_file_save)

    # ========================================================================
    # SERIAL PORT MANAGEMENT
    # ========================================================================

    def refresh_serial_ports(self):
        """Refresh available serial ports list."""
        ports = SerialConnection.list_ports()
        port_options = [("None", "none")] + [(p[0], p[1]) for p in ports]

        try:
            select = self.query_one("#serial-port-select", Select)
            select.set_options(port_options)
        except:
            pass

    def _connect_serial(self):
        """Connect to serial port using SerialConnection wrapper."""
        try:
            port = self.query_one("#serial-port-select", Select).value
            if port in ("none", Select.BLANK):
                self.log_message("No serial port selected", 'error')
                return

            baud_rate = int(self.query_one("#serial-baud", Select).value)
            parity_val = self.query_one("#serial-parity", Select).value
            bits_val = self.query_one("#serial-bits", Select).value
            stop_val = self.query_one("#serial-stop-bits", Select).value

            self.serial_conn.connect(port, baud_rate)

            ser = self.serial_conn.connection
            if ser:
                parity_map = {
                    "N": serial.PARITY_NONE,
                    "E": serial.PARITY_EVEN,
                    "O": serial.PARITY_ODD,
                    "M": serial.PARITY_MARK,
                    "S": serial.PARITY_SPACE,
                }
                bytesize_map = {
                    "5": serial.FIVEBITS,
                    "6": serial.SIXBITS,
                    "7": serial.SEVENBITS,
                    "8": serial.EIGHTBITS,
                }
                stopbits_map = {
                    "1": serial.STOPBITS_ONE,
                    "1.5": serial.STOPBITS_ONE_POINT_FIVE,
                    "2": serial.STOPBITS_TWO,
                }

                ser.parity = parity_map[parity_val]
                ser.bytesize = bytesize_map[bits_val]
                ser.stopbits = stopbits_map[stop_val]

            self.query_one("#serial-connect", Button).disabled = True
            self.query_one("#serial-disconnect", Button).disabled = False

            self.receiver.start()

            self.log_message(f"Connected to {port} at {baud_rate} baud")

            self.config["serial"] = {
                "port": port,
                "baud_rate": baud_rate,
                "parity": parity_val,
                "data_bits": bits_val,
                "stop_bits": stop_val,
            }
            self.saveUnifiedConfig()

        except ValueError as e:
            self.log_message(f"Invalid configuration value: {e}", 'error')
        except serial.SerialException as e:
            self.log_message(f"Error connecting to serial: {e}", 'error')
        except Exception as e:
            self.log_message(f"Unexpected error: {e}", 'error')

    def _disconnect_serial(self):
        """Disconnect from serial port."""
        self._stop_all_repeating_buttons()
        self.receiver.stop()
        self.serial_conn.disconnect()

        try:
            status = self.query_one("#serial-status", Static)
            status.remove_class("status-connected")
            status.add_class("status-disconnected")

            connect_btn = self.query_one("#serial-connect", Button)
            disconnect_btn = self.query_one("#serial-disconnect", Button)
            connect_btn.disabled = False
            disconnect_btn.disabled = True

            self.log_message("Serial disconnected")

        except:
            pass

    # ========================================================================
    # SERIAL DATA TRANSMISSION
    # ========================================================================

    def _send_command(self, frame, format_override: str = None, comment: str = ''):
        """Send a command frame over serial."""
        if not self.serial_conn.connected:
            self.log_message("Not connected to serial port", 'error')
            return
        
        try:
            if format_override:
                input_format = format_override
            else:
                try:
                    format_select = self.query_one("#send-format-select", Select)
                    input_format = format_select.value
                except:
                    input_format = "ascii"
            
            if input_format == "hex":
                hex_str = frame.replace(" ", "").replace("0x", "")
                frameData = bytes.fromhex(hex_str)
            elif input_format == "decimal":
                dec_values = frame.split()
                frameData = bytes([int(val) for val in dec_values])
            elif input_format == "binary":
                bin_values = frame.replace(" ", "")
                byte_values = [bin_values[i:i+8] for i in range(0, len(bin_values), 8)]
                frameData = bytes([int(b, 2) for b in byte_values])
            else:
                frameData = frame.encode('ascii')
            
            self.log_message(frameData, 'tx')
            self.serial_conn.write(frameData)
            
        except ValueError as e:
            self.log_message(f"Invalid format for {input_format}: {e}", 'error')
        except Exception as e:
            self.log_message(f"Error sending command: {e}", 'error')

    def _on_frame_received(self, frame_bytes: bytes):
        """Handle received serial data."""
        self.log_message(frame_bytes, 'rx')
        
        if self.sequence_handler:
            matched_sequence = self.sequence_handler.check_data(frame_bytes)
            
            if matched_sequence:
                if matched_sequence.comment:
                    self.log_message(matched_sequence.comment, 'seq_comment')
                
                # Schedule the response with delay
                if matched_sequence.delay > 0:
                    self.set_timer(
                        matched_sequence.delay,
                        lambda: self._send_sequence_response(matched_sequence)
                    )
                else:
                    # Send immediately
                    self._send_sequence_response(matched_sequence)
    
    def _send_sequence_response(self, sequence: ReceiveSequence):
        """Send the response for a matched sequence."""
        try:
            response_bytes = sequence.get_response_bytes()
            if response_bytes:
                self.serial_conn.write(response_bytes)
                self.log_message(response_bytes, 'tx')
                self.log_message(f"Sequence: {sequence.name}", 'info')
        except Exception as e:
            self.log_message(f"Error sending sequence response: {e}", 'error')

    def _on_frame_received_threadsafe(self, frame_bytes: bytes):
        """Thread-safe wrapper for frame reception."""
        self.call_from_thread(self._on_frame_received, frame_bytes)

    # ========================================================================
    # BUTTON EVENT HANDLERS
    # ========================================================================

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button press events."""
        button_id = event.button.id

        if button_id == "serial-connect":
            self._connect_serial()
        elif button_id == "serial-disconnect":
            self._disconnect_serial()
        elif button_id == "refresh-ports":
            self.refresh_serial_ports()
        elif button_id == "send-button":
            if self.serial_conn.connected:
                input_widget = self.query_one("#quick-send-input", Input)
                command = input_widget.value
                self._send_command(command)
        elif hasattr(event.button, 'message') and hasattr(event.button, 'format'):
            message = event.button.message
            format_type = event.button.format
            label = event.button.label
            repeat = getattr(event.button, 'repeat', None)
            
            if self.serial_conn.connected:
                if repeat is not None:
                    self._toggle_repeat_button(event.button, message, format_type, repeat)
                else:
                    self._send_command(message, format_override=format_type, comment=label)
            else:
                self.log_message("Not connected to serial port", 'error')

    def on_input_submitted(self, event: Input.Submitted):
        """Handle quick send input submission."""
        input_widget = self.query_one("#quick-send-input", Input)

        if self.serial_conn.connected:
            command = input_widget.value
            self._send_command(command)

        input_widget.value = ""

    # ========================================================================
    # REPEATING BUTTON MANAGEMENT
    # ========================================================================
    
    def _toggle_repeat_button(self, button: Button, message: str, format_type: str, interval_ms: int):
        """Toggle a repeating button on/off."""
        button_id = button.id
        
        if button_id in self.repeating_buttons:
            self._stop_repeating_button(button_id)
            button.remove_class("button-repeating")
            self.log_message(f"Stopped repeating: {button.label}")
        else:
            self._start_repeating_button(button_id, button, message, format_type, interval_ms)
            button.add_class("button-repeating")
    
    def _start_repeating_button(self, button_id: str, button: Button, message: str, format_type: str, interval_ms: int):
        """Start repeating a command at the specified interval."""
        self._send_command(message, format_override=format_type, comment="")
        
        interval_s = interval_ms / 1000.0
        
        timer = self.set_interval(
            interval_s,
            lambda: self._send_command(message, format_override=format_type, comment=f"{button.label} (repeat)"),
            name=f"repeat_{button_id}"
        )
        
        self.repeating_buttons[button_id] = timer
    
    def _stop_repeating_button(self, button_id: str):
        """Stop a repeating button."""
        if button_id in self.repeating_buttons:
            timer = self.repeating_buttons[button_id]
            timer.stop()
            del self.repeating_buttons[button_id]
    
    def _stop_all_repeating_buttons(self):
        """Stop all repeating buttons (called on disconnect)."""
        for button_id in list(self.repeating_buttons.keys()):
            try:
                button = self.query_one(f"#{button_id}", Button)
                button.remove_class("button-repeating")
            except:
                pass
            self._stop_repeating_button(button_id)
        
        if self.repeating_buttons:
            self.log_message("Stopped all repeating buttons")

    # ========================================================================
    # LOGGING & UI HELPERS
    # ========================================================================

    def log_message(self, message, type: str = ''):
        """Log a message to the multi-format log panel."""
        try:
            log = self.query_one(MultiFormatLog)
            log.log_message(message, type)
        except Exception as e:
            print(f"Log error: {e} - Message: {message}")

    def action_clearlog_message(self):
        """Clear the log window."""
        try:
            log = self.query_one(MultiFormatLog)
            log.clear()
        except:
            pass

    # ========================================================================
    # APP LIFECYCLE
    # ========================================================================

    def action_quit(self):
        """Quit application and save all data."""
        self.log_message("Quitting...")
        self.saveUnifiedConfig()
        self.saveSettings()
        self.exit()