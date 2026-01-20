from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Static, Button, Select, Input
from pathlib import Path
import time
import serial
import yaml

from ui.widgets.serial_bar import SerialBar
from ui.widgets.data_table import ShelfDataTable
from ui.widgets.status_panel import StatusPanel
from ui.widgets.log_panel import LogPanel
from ui.widgets.control_buttons import ControlButtons
from serial_comm.connection import SerialConnection
from serial_comm.receiver import SerialReceiver
from serial_comm.protocol import Protocol
from models.shelf_data import Shelf, ShelfRow
from config.settings import SHELF_COUNT, POSITIONS_PER_SHELF
from utils.formatting import format_frame


class TUIApp(App):

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+w", "clear_log", "Clear Log", show=True),
        Binding("ctrl+r", "reload_css", "Reload CSS", show=False)
    ]

    CSS_PATH = "styles.tcss"

    def __init__(self):
        super().__init__()
        self.serial_conn = SerialConnection()
        self.receiver = SerialReceiver(self.serial_conn)

        self.first_ack_received = False
        self.receiving_shelf_data = False
        self.received_shelf_bitmask = False
        self.current_shelf_list_idx = 0
        self.current_row_idx = 0
        self.available_shelf_list = []
        

        self._setup_receiver_callbacks()

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
                self._log("Created default settings file")
            else:
                # Load existing settings
                with open(settings_file, 'r') as f:
                    self.config = yaml.safe_load(f)

        except Exception as e:
            self._log(f"Error loading settings: {e}")
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
                baud_input = self.query_one("#baud-rate", Input)
                self.config['serial']['port'] = select.value
                self.config['serial']['baud_rate'] = int(baud_input.value)
            except:
                pass
            
            with open(settings_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False)
            
        except Exception as e:
            self._log(f"Error saving settings: {e}")

    def compose(self) -> ComposeResult:
        yield Static("STOCKS TABACO - POS SIM", id="title")
        yield SerialBar()
        yield ShelfDataTable(id="data-grid")
        yield StatusPanel()
        yield LogPanel()
        yield ControlButtons()
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
                baud_input = self.query_one("#baud-rate", Input)
                
                if self.config['serial']['port'] != 'none':
                    select.value = self.config['serial']['port']
                baud_input.value = str(self.config['serial']['baud_rate'])
                
            except Exception as e:
                self._log(f"Error applying settings to UI: {e}")

        table = self.query_one(ShelfDataTable)
        table.setup_columns()
        table.populate_rows()

    def _setup_receiver_callbacks(self):
        """Setup callbacks for serial receiver."""
        self.receiver.on_ack = self._on_ack
        self.receiver.on_ping_response = self._on_ping
        self.receiver.on_version = self._on_version
        self.receiver.on_distance_data = self._on_distance_data
        self.receiver.on_frame_received = self._on_frame_received
        self.receiver.on_error = self._on_error

    def _on_ack(self):
        """Handle ACK response."""
        if self.receiving_shelf_data:
            self.receiving_shelf_data = False
            self.received_shelf_bitmask = False
            self._log(f"Shelf report complete")
            try:
                table = self.query_one(ShelfDataTable)
                table.refresh()
            except:
                pass
        elif not self.first_ack_received:
            self.first_ack_received = True
            self._log("ACK received - requesting VERSION")
            time.sleep(0.1)
            self._send_command(Protocol.create_get_version(), "GET_VERSION")
        else:
            self._log("ACK received")

    def _on_ping(self):
        """Handle PING response."""
        self._log("PING response received")

    def _on_version(self, sw_ver: str, hw_ver: str):
        """Handle VERSION response."""
        self._log(f"VERSION: SW {sw_ver} / HW {hw_ver}")
        try:
            status_panel = self.query_one(StatusPanel)
            status_panel.update_versions(sw_ver, hw_ver)
        except:
            pass

    def _on_distance_data(self, distance: int):
        """Handle distance data from GET_REPORT."""
        if not self.received_shelf_bitmask:
            available_shelves = distance
            self._log(
                f"Received shelf availability: 0x{available_shelves:04X}")
            self.received_shelf_bitmask = True
            self._start_shelf_report(available_shelves)
        else:
            if len(self.available_shelf_list) == 0:
                self._log(
                    "Warning: Received distance data but no shelves available")
                return

            if self.current_shelf_list_idx >= len(self.available_shelf_list):
                self._log(
                    "Warning: Received extra data beyond available shelves")
                return

            shelf_idx = self.available_shelf_list[self.current_shelf_list_idx]

            if self.current_row_idx % 8 == 0:
                self._log(
                    f"Shelf {shelf_idx + 1} Row {self.current_row_idx}: {distance}mm")

            try:
                table = self.query_one(ShelfDataTable)
                self.call_from_thread(
                    self._update_table_cell,
                    shelf_idx,
                    self.current_row_idx,
                    distance
                )
            except Exception as e:
                self._log(f"Error updating table: {e}")

            self.current_row_idx += 1

            if self.current_row_idx >= POSITIONS_PER_SHELF:
                self._log(
                    f"Shelf {shelf_idx + 1} complete ({POSITIONS_PER_SHELF} rows)")
                self.current_shelf_list_idx += 1
                self.current_row_idx = 0

                if self.current_shelf_list_idx >= len(self.available_shelf_list):
                    self._log(
                        f"All {len(self.available_shelf_list)} shelf data received, waiting for ACK...")
                else:
                    next_shelf = self.available_shelf_list[self.current_shelf_list_idx]
                    self._log(f"Ready for shelf {next_shelf + 1} data...")

    def _on_frame_received(self, frame_bytes: bytes):
        """Handle received frame for logging."""
        self._log(f"[RX]: {format_frame(frame_bytes)}")

    def _on_error(self, error_msg: str):
        """Handle error from receiver."""
        self._log(error_msg)

    def _start_shelf_report(self, available_shelves: int):
        """Initialize shelf report parsing."""
        self.available_shelf_list = []
        for i in range(SHELF_COUNT):
            if (available_shelves >> i) & 0x01:
                self.available_shelf_list.append(i)

        self._log(
            f"Available shelves: {[s+1 for s in self.available_shelf_list]} (bitmask: 0x{available_shelves:04X})")

        try:
            table = self.query_one(ShelfDataTable)
            for i in range(SHELF_COUNT):
                shelf = table.shelves[i]
                shelf.available = i in self.available_shelf_list

            for i, shelf in enumerate(table.shelves):
                table.update_shelf(i, shelf)
        except Exception as e:
            self._log(f"Error updating table: {e}")

        self.receiving_shelf_data = True
        self.current_shelf_list_idx = 0
        self.current_row_idx = 0

        if len(self.available_shelf_list) > 0:
            first_shelf = self.available_shelf_list[0]
            self._log(
                f"Ready to receive data from {len(self.available_shelf_list)} shelves, starting with shelf {first_shelf + 1}")
        else:
            self._log("No available shelves - no data to receive")
            self.receiving_shelf_data = False

    def _update_table_cell(self, shelf_idx: int, row_idx: int, distance: int):
        """Update a single table cell with distance data."""
        try:
            table = self.query_one(ShelfDataTable)
            shelf = table.shelves[shelf_idx]
            shelf.rows[row_idx] = ShelfRow(distance)

            if shelf_idx >= len(table.row_keys):
                return

            row_key = table.row_keys[shelf_idx]
            col_key = str(row_idx)
            table.update_cell(row_key, col_key,
                              shelf.rows[row_idx].display_value)
        except Exception as e:
            self._log(f"UI update error: {e}")

    def on_button_pressed(self, event: Button.Pressed):
        """Handle button press events."""
        button_id = event.button.id

        if button_id == "serial-connect":
            self._connect_serial()
        elif button_id == "serial-disconnect":
            self._disconnect_serial()
        elif button_id == "refresh-ports":
            self.refresh_serial_ports()
            self._log("Serial ports refreshed")
        elif button_id == "btn1":
            self._send_command(Protocol.create_get_version(), "GET_VERSION")
        elif button_id == "btn2":
            self.received_shelf_bitmask = False
            self._send_command(Protocol.create_get_report(), "GET_REPORT")
        elif button_id == "btn3":
            self._log("CMD3 not implemented")
        elif button_id == "btn4":
            self._log("CMD4 not implemented")

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
        """Connect to serial port."""
        try:
            select = self.query_one("#serial-port-select", Select)
            baud_input = self.query_one("#baud-rate", Input)

            port = select.value
            if port == "none" or port is Select.BLANK:
                self._log("Error: No serial port selected")
                return

            try:
                baud_rate = int(baud_input.value)
            except ValueError:
                self._log("Error: Invalid baud rate")
                return

            self.serial_conn.connect(port, baud_rate)
            self.first_ack_received = False

            status = self.query_one("#serial-status", Static)
            status.remove_class("status-disconnected")
            status.add_class("status-connected")

            connect_btn = self.query_one("#serial-connect", Button)
            disconnect_btn = self.query_one("#serial-disconnect", Button)
            connect_btn.disabled = True
            disconnect_btn.disabled = False

            self._log(f"Connected to {port} at {baud_rate} baud")

            status_panel = self.query_one(StatusPanel)
            status_panel.update_connection(True)

            self.receiver.start()

            # Save settings
            self.config['serial']['port'] = port
            self.config['serial']['baud_rate'] = baud_rate
            self.saveSettings()

        except serial.SerialException as e:
            self._log(f"Error connecting to serial: {e}")
        except Exception as e:
            self._log(f"Error: {e}")

    def _disconnect_serial(self):
        """Disconnect from serial port."""
        self.receiver.stop()
        self.serial_conn.disconnect()
        self.first_ack_received = False

        try:
            status = self.query_one("#serial-status", Static)
            status.remove_class("status-connected")
            status.add_class("status-disconnected")

            connect_btn = self.query_one("#serial-connect", Button)
            disconnect_btn = self.query_one("#serial-disconnect", Button)
            connect_btn.disabled = False
            disconnect_btn.disabled = True

            self._log("Serial disconnected")

            status_panel = self.query_one(StatusPanel)
            status_panel.update_connection(False)
            status_panel.update_versions("---", "---")
        except:
            pass

    def _send_command(self, frame, comment: str):
        """Send a command frame over serial."""
        if not self.serial_conn.connected:
            self._log("Error: Not connected to serial port")
            return

        try:
            frame_bytes = frame.to_bytes()
            self._log(f"[TX]: {format_frame(frame_bytes)} ({comment})")
            self.serial_conn.write(frame_bytes)
        except Exception as e:
            self._log(f"Error sending command: {e}")

    def _log(self, message: str):
        """Write message to log."""
        try:
            log = self.query_one(LogPanel)
            log.log(message)
        except:
            pass

    def action_refresh_data(self):
        """Refresh data table display."""
        try:
            table = self.query_one(ShelfDataTable)
            table.refresh()
        except:
            pass

    def action_clear_log(self):
        """Clear the log window."""
        try:
            log = self.query_one(LogPanel)
            log.clear()
        except:
            pass

    def on_unmount(self):
        """Clean up on app close."""
        self.saveSettings()
        self.receiver.stop()
        self.serial_conn.disconnect()

    def action_quit(self):
        """Override quit action to save settings first."""
        self._log("Quitting and saving settings...")
        self.saveSettings()
        self.exit()
