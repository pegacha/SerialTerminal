from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, Button, Select, Input
from pathlib import Path
import serial
import yaml

from ui.widgets.log_panel import MultiFormatLog
from ui.widgets.serial_bar import SerialBar
from ui.widgets.dynamic_control_buttons import DynamicControlButtons
from ui.widgets.quick_send import QuickSend
from ui.widgets.import_settings import DirectoryTree

from sequence_handler import SequenceHandler,ReceiveSequence

from serial_comm.connection import SerialConnection
from serial_comm.receiver import SerialReceiver

from utils.formatting import format_frame


class TUIApp(App):

    BINDINGS = [
        Binding("ctrl+q", "quit", "quit", show=True),
        Binding("ctrl+w", "clearlog_message", "clear", show=True),
        Binding("ctrl+r", "reload_css", "reload css", show=False),
        Binding("ctrl+b", "reload_buttons", "reload buttons", show=True),
        Binding("ctrl+s", "reload_sequences", "reload sequences", show=True)  
    ]

    CSS_PATH = "styles.tcss"

    def __init__(self):
        super().__init__()
        self.serial_conn = SerialConnection()
        self.receiver = SerialReceiver(
            self.serial_conn,
            self._on_frame_received_threadsafe
        )
        
        self.repeating_buttons = {}
        self.sequence_handler = SequenceHandler("sequences.yml")

    def import_settings(self):
        DirectoryTree.run()

    def loadSettings(self):
        settings_file = Path("settings.yml")
        try:
            if not settings_file.exists():
                default_settings = {
                    'serial': {
                        'port': 'none',
                        'baud_rate': 57600
                    },
                    'ui': {
                        'theme': 'nord'
                    }
                }

                with open(settings_file, 'w') as f:
                    yaml.dump(default_settings, f, default_flow_style=False)
                self.config = default_settings
                self.log_message("Created default settings file")
            else:
                # Load existing settings
                with open(settings_file, 'r') as f:
                    self.config = yaml.safe_load(f)

        except Exception as e:
            self.log_message(f"Error loading settings: {e}")
            self.config = {
                'serial': {'port': 'none', 'baud_rate': 57600},
                'ui': {'theme': 'nord'} 
            }

    def saveSettings(self):
        settings_file = Path("settings.yml")
        try:
            # Save current theme
            self.config['ui']['theme'] = self.theme

            # Save current UI values if available
            try:
                select = self.query_one("#serial-port-select", Select)
                baud_input = self.query_one("#serial-baud", Select)
                data_bits = self.query_one("#serial-bits", Select)
                serial_parity = self.query_one("serial-parity", Select)
                serial_stop_bits = self.query_one("serial-stop-bits", Select)

                self.config['serial']['port'] = select.value
                self.config['serial']['baud_rate'] = int(baud_input.value)
                self.config['serial']['data_bits'] = int(data_bits.value)
                self.config['serial']['parity'] = int(serial_parity.value)
                self.config['serial']['stop_bits'] = int(
                    serial_stop_bits.value)
            except:
                pass

            with open(settings_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False)

        except Exception as e:
            self.log_message(f"Error saving settings: {e}")

    def compose(self) -> ComposeResult:
        yield Static("SerialTerm", id="title")
        yield SerialBar()
        yield MultiFormatLog()
        yield QuickSend()
        yield DynamicControlButtons()
        yield Footer()

    def on_mount(self):
        """Initialize UI components on mount."""
        self.loadSettings()

        # Apply loaded theme
        if 'ui' in self.config and 'theme' in self.config['ui']:
            self.theme = self.config['ui']['theme']

        self.refresh_serial_ports()

        # Apply loaded serial settings to UI
        if 'serial' in self.config:
            try:
                select = self.query_one("#serial-port-select", Select)
                baud_input = self.query_one("#serial-baud", Select)

                if self.config['serial']['port'] != 'none':
                    select.value = self.config['serial']['port']
                baud_input.value = str(self.config['serial']['baud_rate'])

            except Exception as e:
                self.log_message(f"Error applying settings to UI: {e}")

    def _on_frame_received(self, frame_bytes: bytes):
        self.log_message(frame_bytes, 'rx')
        
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
                comment = f"Sequence: {sequence.name}"
                self.log_message(response_bytes, 'tx')
                self.log_message(f"Sequence: {sequence.name}", 'info')
        except Exception as e:
            self.log_message(f"Error sending sequence response: {e}", 'error')

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button press events."""
        button_id = event.button.id

        if button_id == "serial-connect":
            self._connect_serial()
        elif button_id == "serial-disconnect":
            self._disconnect_serial()
        elif button_id == "refresh-ports":
            self.refresh_serial_ports()
        elif button_id == "send-button":  # Quick send
            if self.serial_conn.connected:
                input_widget = self.query_one("#quick-send-input", Input)
                command = input_widget.value
                self._send_command(command)  # Uses format from selector
            else:
                pass
        elif hasattr(event.button, 'message') and hasattr(event.button, 'format'):
            message = event.button.message
            format_type = event.button.format
            label = event.button.label
            repeat = getattr(event.button, 'repeat', None)
            
            if self.serial_conn.connected:
                if repeat is not None:
                    # This is a repeating button
                    self._toggle_repeat_button(event.button, message, format_type, repeat)
                else:
                    # Regular one-shot button - use format override
                    self._send_command(message, format_override=format_type, comment=label)
            else:
                self.log_message("Not connected to serial port", 'error')
    
    def _toggle_repeat_button(self, button: Button, message: str, format_type: str, interval_ms: int):
        """Toggle a repeating button on/off."""
        button_id = button.id
        
        if button_id in self.repeating_buttons:
            # Button is currently repeating - stop it
            self._stop_repeating_button(button_id)
            button.remove_class("button-repeating")
            self.log_message(f"Stopped repeating: {button.label}")
        else:
            # Start repeating
            self._start_repeating_button(button_id, button, message, format_type, interval_ms)
            button.add_class("button-repeating")
    
    def _start_repeating_button(self, button_id: str, button: Button, message: str, format_type: str, interval_ms: int):
        """Start repeating a command at the specified interval."""
        # Send immediately first
        self._send_command(message, format_override=format_type, comment="")
        
        # Convert ms to seconds
        interval_s = interval_ms / 1000.0
        
        # Set up timer to repeat
        timer = self.set_interval(
            interval_s,
            lambda: self._send_command(message, format_override=format_type, comment=f"{button.label} (repeat)"),
            name=f"repeat_{button_id}"
        )
        
        # Store the timer handle
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

    def on_input_submitted(self, event: Input.Submitted):
        """Get input value and send the command"""
        input_widget = self.query_one("#quick-send-input", Input)

        if self.serial_conn.connected:
            command = input_widget.value
            self._send_command(command)

        input_widget.value = ""

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

            # Connect using wrapper (initial connection)
            self.serial_conn.connect(port, baud_rate)

            # Configure pySerial directly
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

            self.first_ack_received = False

            self.query_one("#serial-connect", Button).disabled = True
            self.query_one("#serial-disconnect", Button).disabled = False

            self.receiver.start()

            self.log_message(f"Connected to {port} at {baud_rate} baud")

            # Save config
            self.config["serial"] = {
                "port": port,
                "baud_rate": baud_rate,
                "parity": parity_val,
                "data_bits": bits_val,
                "stop_bits": stop_val,
            }
            self.saveSettings()

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

    def _send_command(self, frame, format_override: str = None, comment: str = ''):
        """
        Send a command frame over serial, converting from selected format if needed.
        
        Args:
            frame: The message/command to send
            format_override: Override the format selector (for control buttons)
            comment: Optional comment to add to log
        """
        if not self.serial_conn.connected:
            self.log_message("Not connected to serial port", 'error')
            return
        
        try:
            # Determine which format to use
            if format_override:
                # Use the override format (from control button)
                input_format = format_override
            else:
                # Get the selected input format from UI
                try:
                    format_select = self.query_one("#send-format-select", Select)
                    input_format = format_select.value
                except:
                    input_format = "ascii"  # Default to ASCII if selector not found
            
            # Convert input based on format
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
            else:  # ascii (default)
                frameData = frame.encode('ascii')
            
            comment_str = f" ({comment})" if comment else ""
            self.log_message(frameData, 'tx')  
            self.serial_conn.write(frameData)
            
        except ValueError as e:
            self.log_message(f"Invalid format for {input_format}: {e}", 'error')
        except Exception as e:
            self.log_message(f"Error sending command: {e}", 'error')

    def log_message(self, message, type: str = ''):
        """Log a message to the multi-format log panel."""
        try:
            log = self.query_one(MultiFormatLog)
            if isinstance(message, bytes):
                log.log_message(message, type)
            else:
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

    def on_unmount(self):
        """Clean up on app close."""
        self._stop_all_repeating_buttons()
        self.saveSettings()
        self.receiver.stop()
        self.serial_conn.disconnect()

    def action_quit(self):
        """Override quit action to save settings first."""
        self.log_message("Quitting and saving settings...")
        self.saveSettings()
        self.exit()

    def action_reload_buttons(self):
        try:
            control_buttons = self.query_one(DynamicControlButtons)
            control_buttons.reload_config()
            self.log_message("Button configuration reloaded from buttons.yml")
        except Exception as e:
            self.log_message(f"Error reloading buttons: {e}", 'error')

    def action_reload_sequences(self):
        """Reload sequence configuration."""
        try:
            self.sequence_handler.reload_sequences()
            active_count = len(self.sequence_handler.get_active_sequences())
            self.log_message(f"Sequences reloaded: {active_count} active", 'info')
        except Exception as e:
            self.log_message(f"Error reloading sequences: {e}", 'error')
            
    def _on_frame_received_threadsafe(self, frame_bytes: bytes):
        self.call_from_thread(self._on_frame_received, frame_bytes)
