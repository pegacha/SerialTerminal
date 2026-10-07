from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, Button, Select, Input
from textual.containers import Horizontal, Vertical
from textual.widgets.select import InvalidSelectValueError
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual_fspicker import Filters
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
import re
import serial
import threading
import yaml
import shutil
import logging

from serialterminal import __version__
from serialterminal.ui.widgets.log_panel import MultiFormatLog
from serialterminal.ui.widgets.serial_bar import SerialBar
from serialterminal.ui.widgets.dynamic_control_buttons import DynamicControlButtons
from serialterminal.ui.widgets.quick_send import QuickSend
from serialterminal.ui.widgets.file_pickers import CompactFileOpen, CompactFileSave

from serialterminal.sequence_handler import SequenceHandler, ReceiveSequence

from serialterminal.serial_comm.connection import SerialConnection
from serialterminal.serial_comm.receiver import SerialReceiver

from serialterminal.utils.docklight_interpreter import DocklightConfigInterpreter
from serialterminal.utils.formatting import timestamp
from serialterminal.utils.payload import build_frame
from serialterminal.utils.session_capture import SessionCapture

log = logging.getLogger("serialterminal.app")


class _UnreadableConfig(Exception):
    """project.yml exists but cannot be used as a config."""


def import_filters() -> Filters:
    """File filters for Ctrl+I. The first is the default, so it must cover
    both formats: with YAML first, .ptp files were hidden until you switched."""
    return Filters(
        ("YAML or Docklight", lambda p: p.suffix.lower() in {".yml", ".yaml", ".ptp"}),
        ("YAML files", lambda p: p.suffix.lower() in {".yml", ".yaml"}),
        ("Docklight files", lambda p: p.suffix.lower() == ".ptp"),
        ("All files", lambda p: True),
    )


class TUIApp(App):

    TITLE = "SerialTerminal"

    # Ordered by how often they're used, with short labels: the footer shows
    # what fits and drops the rest, and with long labels in definition order
    # "record" never appeared below ~135 columns. Session actions come before
    # config actions, and the descriptions (shown in full by the key panel,
    # Ctrl+P > Keys) carry the detail.
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit", show=True),
        # None of these three is claimed by Input, so they still work while the
        # quick-send or filter box has focus.
        Binding("ctrl+f", "toggle_filter", "filter", show=True, tooltip="Filter the log; Esc closes"),
        Binding("ctrl+b", "toggle_pause", "pause", show=True, tooltip="Pause / resume the log view"),
        Binding("ctrl+s", "toggle_capture", "record", show=True, tooltip="Record the session to a file"),
        Binding("ctrl+w", "clearlog_message", "clear", show=True, tooltip="Clear the log"),
        Binding("ctrl+o", "edit_config", "edit", show=True, tooltip="Edit project.yml"),
        Binding("ctrl+l", "reload_config", "reload", show=True, tooltip="Reload project.yml"),
        Binding("ctrl+i", "import_config", "import", show=True, tooltip="Import a config (.yml or Docklight .ptp)"),
        Binding("ctrl+e", "export_config", "export", show=True, tooltip="Export the config to a .yml file"),
        Binding("ctrl+r", "reload_css", "reload css", show=False)
    ]

    # Classes the screen gets by size, used by styles.tcss. Below 100 columns
    # the button sidebar moves under the log; below 30 rows spacing is traded
    # for log rows (at 80x24 the log once had a single visible line).
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (30, "-tall")]

    CSS_PATH = "styles.tcss"

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def __init__(self):
        super().__init__()
        # Provisional; re-read in on_mount, which is guaranteed to run on the
        # event loop's own thread even if the App was constructed elsewhere.
        self._app_thread_id = threading.get_ident()
        # Route debug output to a rotating log file instead of stdout/stderr,
        # which would corrupt the full-screen TUI. Tail serialterminal.log
        # (capped at ~4MB across 4 files) to debug serial issues.
        _log_handler = RotatingFileHandler(
            "serialterminal.log", maxBytes=1_000_000, backupCount=3
        )
        _log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.basicConfig(level=logging.DEBUG, handlers=[_log_handler], force=True)
        self.serial_conn = SerialConnection()
        self.receiver = SerialReceiver(
            self.serial_conn,
            self._on_frame_received_threadsafe
        )
        
        self.repeating_buttons = {}
        self.capture = SessionCapture()
        self.config_file = Path("project.yml")
        self.settings_file = Path("settings.yml")
        
        # Load user settings first (theme, preferences)
        self.settings = {}
        self.load_settings()
        
        # Load working config (serial, buttons, sequences)
        self.config = {}
        self.sequence_handler = None
        self.load_config()

    def compose(self) -> ComposeResult:
        yield Static(f"SerialTerminal {__version__}", id="title")
        yield SerialBar()
        # Log and Send Command on the left, control buttons in a sidebar on the
        # right, so the log gets every row the serial bar doesn't use. Below
        # 100 columns (the -narrow class) styles.tcss stacks the buttons under
        # the log instead: a sidebar there would leave the log too narrow for
        # a hex frame.
        with Horizontal(id="workspace"):
            with Vertical(id="log-column"):
                yield MultiFormatLog()
                yield QuickSend()
            yield DynamicControlButtons(config_data=self.config.get('buttons', []))
        footer = Footer()
        footer.compact = True  # an attribute, not a constructor argument, in Textual 4.0
        yield footer

    def on_mount(self):
        """Initialize UI components on mount."""
        self._app_thread_id = threading.get_ident()
        self.refresh_serial_ports()
        self._apply_serial_config_to_ui()
        self._report_config_problems()

    def _apply_serial_config_to_ui(self):
        """Apply the loaded theme, serial and quick-send settings onto the widgets.

        Shared by on_mount() and config reload, so reloading config never
        re-runs the whole mount lifecycle (port re-enumeration, etc.).
        """
        # Theme is per-machine and lives in settings.yml. project.yml is meant
        # to be shared, so it no longer carries a theme; older files still do,
        # and are honoured once as a migration before settings.yml takes over.
        theme = self.settings.get('ui', {}).get('theme')
        if theme is None:
            theme = self.config.get('ui', {}).get('theme')
        if theme:
            self.theme = theme

        # Apply loaded serial settings to UI. Every field saved by
        # save_config() must be restored here, or the file and the widgets
        # disagree and you connect with line settings you never chose.
        serial_cfg = self.config.get('serial')
        if isinstance(serial_cfg, dict):
            restore = [
                ("#serial-port-select", 'port', 'none'),
                ("#serial-baud", 'baud_rate', 115200),
                ("#serial-parity", 'parity', 'N'),
                ("#serial-bits", 'data_bits', '8'),
                ("#serial-stop-bits", 'stop_bits', '1'),
            ]
            for widget_id, key, default in restore:
                value = str(serial_cfg.get(key, default))
                if widget_id == "#serial-port-select" and value == 'none':
                    continue
                self._set_select_value(widget_id, value)

        # Quick-send choices are a property of the device, so they live with
        # the project. Only keys actually present are applied.
        quick_cfg = self.config.get('quick_send')
        if isinstance(quick_cfg, dict):
            for widget_id, key in (
                ("#send-format-select", 'format'),
                ("#send-line-ending", 'line_ending'),
                ("#send-checksum", 'checksum'),
            ):
                if key in quick_cfg:
                    self._set_select_value(widget_id, str(quick_cfg[key]))

    def _set_select_value(self, widget_id: str, value: str) -> bool:
        """Set a Select's value, tolerating options that no longer exist.

        A saved port can disappear between runs (adapter unplugged). Textual
        rejects a value outside the current options, so report it instead of
        letting the whole restore silently abort partway through.
        """
        try:
            select = self.query_one(widget_id, Select)
        except Exception as e:
            log.debug("select %s not available: %s", widget_id, e)
            return False

        try:
            select.value = value
        except InvalidSelectValueError:
            self.log_message(
                f"Saved value {value!r} for {widget_id.lstrip('#')} is not available",
                'error'
            )
            return False
        return True

    def on_unmount(self):
        """Clean up on app close."""
        self._stop_all_repeating_buttons()
        self.capture.stop()
        self.save_config()
        self.save_settings()
        tail = self.receiver.stop()
        if tail:
            # The log panel is on its way out; the file log is what survives.
            log.debug("unframed bytes at shutdown: %r", tail)
        self.serial_conn.disconnect()

    # ========================================================================
    # SETTINGS & CONFIG MANAGEMENT
    # ========================================================================

    def load_settings(self):
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
            log.error("Error loading settings: %s", e)
            self.settings = {'ui': {'theme': 'nord'}, 'config': {'last_used': None}}

    def save_settings(self):
        """Save user settings"""
        try:
            # Update theme
            if 'ui' not in self.settings:
                self.settings['ui'] = {}
            self.settings['ui']['theme'] = self.theme
            
            with open(self.settings_file, 'w') as f:
                yaml.dump(self.settings, f, default_flow_style=False)
                
        except Exception as e:
            log.error("Error saving settings: %s", e)
    
    def load_config(self):
        """Load unified configuration from project.yml.

        If the file exists but can't be used (bad YAML, or not a mapping), the
        app starts with an empty config and refuses to save over the file:
        otherwise one typo from a Ctrl+O edit was replaced on exit by a
        near-empty config, deleting every button and sequence in it.
        """
        self.config_unreadable = None
        try:
            if self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    first_line = str(e).strip().splitlines()[-1].strip()
                    raise _UnreadableConfig(f"invalid YAML ({first_line})") from e
                if data is None:
                    data = {}
                if not isinstance(data, dict):
                    raise _UnreadableConfig(
                        f"top level must be a mapping, got {type(data).__name__}")
                self.config = data

                log.debug("Loaded configuration from %s", self.config_file)
                
                # Initialize sequence handler if sequences exist
                if 'sequences' in self.config:
                    self.sequence_handler = SequenceHandler(config_data=self.config['sequences'])
                else:
                    self.sequence_handler = SequenceHandler(config_data=[])
                
            else:
                log.debug("No project.yml found - starting with defaults")
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

        except _UnreadableConfig as e:
            log.error("Cannot use %s: %s", self.config_file, e)
            self.config_unreadable = str(e)
            self.config = {}
            self.sequence_handler = SequenceHandler(config_data=[])
        except Exception as e:
            log.error("Error loading config: %s", e)
            self.config_unreadable = str(e)
            self.config = {}
            self.sequence_handler = SequenceHandler(config_data=[])

    def _report_config_problems(self):
        """Put every config problem on screen, not only in serialterminal.log.

        Called after mount and after each reload, when the log panel exists.
        """
        if self.config_unreadable:
            self.log_message(
                f"{self.config_file} not loaded: {self.config_unreadable}. It will "
                f"not be overwritten - fix it (Ctrl+O) and reload (Ctrl+L).",
                'error'
            )
        try:
            for problem in self.query_one(DynamicControlButtons).problems:
                self.log_message(problem, 'error')
        except NoMatches:
            pass
        skipped = getattr(self.sequence_handler, 'skipped', 0)
        if skipped:
            self.log_message(
                f"{skipped} sequence(s) skipped as malformed - details in serialterminal.log",
                'error'
            )

    def save_config(self):
        """Save unified configuration to project.yml"""
        if getattr(self, 'config_unreadable', None):
            # Writing now would replace the user's file - typo and all, but
            # otherwise intact - with the empty fallback config.
            log.warning("Not saving %s: it could not be read (%s)",
                        self.config_file, self.config_unreadable)
            return
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
            except (NoMatches, ValueError) as e:
                # Widgets absent (saving before mount / during teardown) or a
                # non-numeric baud. Keep whatever is already in self.config.
                log.debug("serial settings not read from UI: %s", e)

            try:
                self.config['quick_send'] = {
                    'format': self.query_one("#send-format-select", Select).value,
                    'line_ending': self.query_one("#send-line-ending", Select).value,
                    'checksum': self.query_one("#send-checksum", Select).value,
                }
            except NoMatches as e:
                log.debug("quick-send settings not read from UI: %s", e)

            # Deliberately not writing the theme here - see _apply_serial_config_to_ui.
            # Drop a migrated-away 'ui' section so exported configs stop carrying
            # one operator's colour scheme to everybody else.
            if self.config.get('ui') == {} or list(self.config.get('ui', {})) == ['theme']:
                self.config.pop('ui', None)

            # Save to file
            with open(self.config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            
            log.debug("Configuration saved to %s", self.config_file)
            
        except Exception as e:
            log.error("Error saving config: %s", e)

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
        
        # Validate buttons and sequences if present. The isinstance check per
        # entry matters: `'id' not in btn` raises TypeError on a non-container
        # and does a substring test on a string, so a list like [1, 2] or
        # ['abc'] either crashed the validator or passed the wrong verdict.
        for section, required in (('buttons', 'id'), ('sequences', 'name')):
            if section not in config_data:
                continue
            entries = config_data[section]
            if not isinstance(entries, list):
                return (False, f"{section.capitalize()} section must be a list")
            label = section[:-1].capitalize()
            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    return (
                        False,
                        f"{label} {i} must be a mapping, got "
                        f"{type(entry).__name__}"
                    )
                if required not in entry:
                    return (False, f"{label} {i} missing '{required}' field")

        return (True, "")

    # ========================================================================
    # CONFIG ACTIONS (Edit, Reload, Import, Export)
    # ========================================================================

    def action_edit_config(self):
        """Open project.yml in the platform's text editor."""
        import subprocess
        import os
        import sys

        # Resolve an editor: $VISUAL/$EDITOR override, else platform default.
        editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
        if not editor:
            if sys.platform == 'win32':
                editor = 'notepad'
            else:
                editor = shutil.which('nano') or shutil.which('vi') or 'vi'

        try:
            if not self.config_file.exists():
                self.save_config()

            with self.suspend():
                subprocess.run([editor, str(self.config_file)])

            self.action_reload_config()

        except FileNotFoundError:
            self.log_message(
                f"Editor '{editor}' not found. Set the $EDITOR environment variable.",
                'error'
            )
        except Exception as e:
            self.log_message(f"Error opening config: {e}", 'error')
            
    def action_reload_config(self):
        """Reload the unified configuration."""
        try:
            # Reloading recomposes the button panel, which destroys the widgets
            # the timers were started from. Stop them first or they keep firing
            # against the port with nothing on screen to show it.
            self._stop_all_repeating_buttons()

            self.load_config()

            try:
                control_buttons = self.query_one(DynamicControlButtons)
                control_buttons.reload_config(self.config.get('buttons', []))
            except Exception as e:
                self.log_message(f"Error reloading buttons: {e}", 'error')
            
            self._apply_serial_config_to_ui()

            button_count = len(self.query_one(DynamicControlButtons).buttons_config)
            sequence_count = len(self.sequence_handler.get_active_sequences()) if self.sequence_handler else 0
            self.log_message(f"Config reloaded: {button_count} buttons, {sequence_count} sequences", 'info')
            self._report_config_problems()
            
        except Exception as e:
            self.log_message(f"Error reloading config: {e}", 'error')

    def action_import_config(self):
        """Import configuration from a file using file picker."""
        def handle_file_open(file_path: Path | None) -> None:
            if file_path is None:
                self.log_message("Import cancelled", 'info')
                return
            
            try:
                # Check file extension to determine format
                if file_path.suffix.lower() == '.ptp':
                    # Docklight format
                    interpreter = DocklightConfigInterpreter()
                    new_config = interpreter.parse_file(file_path)
                    self.log_message(f"Imported Docklight config", 'info')
                elif file_path.suffix.lower() in {'.yml', '.yaml'}:
                    # YAML format
                    with open(file_path, 'r') as f:
                        new_config = yaml.safe_load(f)
                else:
                    self.log_message(f"Unsupported file type: {file_path.suffix}", 'error')
                    return
                
                # Validate config
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
                
                # Load the new config. An import deliberately replaces
                # project.yml, so an unreadable one no longer blocks saving.
                self.config = new_config
                self.config_unreadable = None
                self.save_config()
                
                # Update last_used in settings
                if 'config' not in self.settings:
                    self.settings['config'] = {}
                self.settings['config']['last_used'] = str(file_path)
                self.save_settings()
                
                # Reload everything
                self.action_reload_config()
                
                self.log_message(f"Config imported from: {file_path.name}", 'info')
                
            except yaml.YAMLError as e:
                self.log_message(f"Invalid YAML: {e}", 'error')
            except Exception as e:
                self.log_message(f"Error importing: {e}", 'error')
                import traceback
                traceback.print_exc()
        
        self.push_screen(CompactFileOpen(".", filters=import_filters()), handle_file_open)

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
                self.save_settings()
                
            except Exception as e:
                self.log_message(f"Error exporting: {e}", 'error')
        
        # Show file picker - FileSave just takes the starting directory
        file_save_screen = CompactFileSave(".")
        self.push_screen(file_save_screen, handle_file_save)

    # ========================================================================
    # SERIAL PORT MANAGEMENT
    # ========================================================================

    @staticmethod
    def port_label(device: str, description: str) -> str:
        """'COM4 — USB Serial Port', not 'COM4 — USB Serial Port (COM4)'.

        Windows descriptions repeat the port name; Linux ones are often 'n/a'
        or the device itself, which adds nothing.
        """
        description = (description or "").strip()
        suffix = f"({device})"
        if description.endswith(suffix):
            description = description[:-len(suffix)].strip()
        if not description or description in (device, "n/a"):
            return device
        return f"{device} — {description}"

    def refresh_serial_ports(self):
        """Refresh available serial ports list."""
        ports = SerialConnection.list_ports()

        # Start with a None option
        port_options = [("No port", "none")]

        # Natural order (COM3, COM4, COM10), not enumeration order.
        def natural(port):
            return [int(part) if part.isdigit() else part.lower()
                    for part in re.split(r"(\d+)", port[0])]

        for device, name, description in sorted(ports, key=natural):
            port_options.append((self.port_label(device, description), device))

        try:
            select = self.query_one("#serial-port-select", Select)
        except Exception:
            return

        # set_options() resets the selection, so put the current port back if
        # it survived the rescan - otherwise pressing Refresh silently loses it.
        previous = select.value
        select.set_options(port_options)
        if previous not in (Select.BLANK, 'none'):
            try:
                select.value = previous
            except InvalidSelectValueError:
                self.log_message(f"Port {previous} is no longer available", 'error')

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

            # Apply line settings atomically at open time (see connect()).
            self.serial_conn.connect(
                port,
                baud_rate,
                bytesize=bytesize_map[bits_val],
                parity=parity_map[parity_val],
                stopbits=stopbits_map[stop_val],
            )

            self._set_serial_status(True)
            self.query_one("#serial-connect", Button).disabled = True
            self.query_one("#serial-disconnect", Button).disabled = False

            # Frame RX by the actual baud rate (Modbus/ASCII gap detection)
            self.receiver.set_baud_rate(baud_rate)
            self.receiver.start()

            self.log_message(f"Connected to {port} at {baud_rate} baud")

            self.config["serial"] = {
                "port": port,
                "baud_rate": baud_rate,
                "parity": parity_val,
                "data_bits": bits_val,
                "stop_bits": stop_val,
            }
            self.save_config()

        except ValueError as e:
            self.log_message(f"Invalid configuration value: {e}", 'error')
        except serial.SerialException as e:
            self.log_message(f"Error connecting to serial: {e}", 'error')
        except Exception as e:
            self.log_message(f"Unexpected error: {e}", 'error')

    def _disconnect_serial(self):
        """Disconnect from serial port."""
        self._stop_all_repeating_buttons()
        # stop() returns bytes that arrived but never completed a frame; log
        # them here, on the UI thread, instead of losing them.
        tail = self.receiver.stop()
        if tail:
            self._on_frame_received(tail)
        self.serial_conn.disconnect()
        connect_btn = self.query_one("#serial-connect", Button)
        disconnect_btn = self.query_one("#serial-disconnect", Button)
        connect_btn.disabled = False
        disconnect_btn.disabled = True

        self._set_serial_status(False)
        self.log_message("Serial disconnected")

    def _set_serial_status(self, connected: bool):
        """Reflect the connection state on the status indicator."""
        try:
            status = self.query_one("#serial-status", Static)
            if connected:
                status.remove_class("status-disconnected")
                status.add_class("status-connected")
                status.update("● Connected")
            else:
                status.remove_class("status-connected")
                status.add_class("status-disconnected")
                status.update("● Disconnected")
        except Exception as e:
            log.debug("status update failed: %s", e)

    # ========================================================================
    # SERIAL DATA TRANSMISSION
    # ========================================================================

    def _send_command(self, frame, format_override: str = None, comment: str = '',
                      checksum: str = 'none', line_ending: str = 'none') -> bool:
        """Send a command frame over serial. Returns True if it was sent."""
        if not self.serial_conn.connected:
            self.log_message("Not connected to serial port", 'error')
            return False

        if format_override:
            input_format = format_override
        else:
            try:
                input_format = self.query_one("#send-format-select", Select).value
            except NoMatches:
                input_format = "ascii"

        try:
            frameData = build_frame(frame, input_format, checksum, line_ending)
            if not frameData:
                self.log_message("Nothing to send", 'error')
                return False
            # write() reports failure by returning 0 rather than raising (the
            # reason goes to serialterminal.log). Check it, and log [TX] only
            # for bytes that actually left: an unplugged adapter used to show
            # a successful [TX] and clear the quick-send box.
            written = self.serial_conn.write(frameData)
            if not written:
                self.log_message(
                    "Send failed - the port did not accept the data "
                    "(unplugged? see serialterminal.log)", 'error')
                return False
            self.log_message(frameData, 'tx')
            return True

        except ValueError as e:
            self.log_message(f"Cannot send ({input_format}): {e}", 'error')
        except Exception as e:
            self.log_message(f"Error sending command: {e}", 'error')
        return False

    def _quick_send(self):
        """Send the quick-send box with its selected options.

        The text is kept unless the send succeeded, so a typo or a dropped
        connection never costs you what you typed.
        """
        box = self.query_one("#quick-send-input", Input)
        if self._send_command(box.value, **self.query_one(QuickSend).options()):
            box.value = ""

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
        """Hand a frame to the UI thread from the receive thread.

        call_from_thread refuses to run on the app's own thread, so fall back to
        a direct call when we are already there. Without this any future caller
        on the UI thread loses the frame to a swallowed RuntimeError.
        """
        if threading.get_ident() == self._app_thread_id:
            self._on_frame_received(frame_bytes)
        else:
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
            self._quick_send()
        elif hasattr(event.button, 'message') and hasattr(event.button, 'format'):
            message = event.button.message
            format_type = event.button.format
            label = event.button.label
            repeat = getattr(event.button, 'repeat', None)
            extras = {
                'checksum': getattr(event.button, 'checksum', 'none'),
                'line_ending': getattr(event.button, 'line_ending', 'none'),
            }

            if self.serial_conn.connected:
                # Check if this is a repeating button (repeat > 0)
                if repeat is not None and repeat > 0:
                    # This is a repeating button
                    self._toggle_repeat_button(event.button, message, format_type, repeat, **extras)
                else:
                    # Regular one-shot button - use format override
                    self._send_command(message, format_override=format_type, comment=label, **extras)
            else:
                self.log_message("Not connected to serial port", 'error')

    def on_input_submitted(self, event: Input.Submitted):
        """Handle quick send input submission."""
        # Any Input's Enter bubbles here; only the quick-send box sends.
        if event.input.id == "quick-send-input":
            self._quick_send()

    # ========================================================================
    # REPEATING BUTTON MANAGEMENT
    # ========================================================================
    
    def _toggle_repeat_button(self, button: Button, message: str, format_type: str, interval_ms: int,
                              checksum: str = 'none', line_ending: str = 'none'):
        """Toggle a repeating button on/off."""
        button_id = button.id
        
        if interval_ms <= 0:
            self.log_message(f"Cannot repeat {button.label}: invalid interval", 'error')
            return
        
        if button_id in self.repeating_buttons:
            # Button is currently repeating - stop it
            self._stop_repeating_button(button_id)
            button.remove_class("button-repeating")
            self.log_message(f"Stopped repeating: {button.label}")
        else:
            # Start repeating
            self._start_repeating_button(button_id, button, message, format_type, interval_ms,
                                         checksum=checksum, line_ending=line_ending)
            button.add_class("button-repeating")

    def _start_repeating_button(self, button_id: str, button: Button, message: str, format_type: str,
                                interval_ms: int, checksum: str = 'none', line_ending: str = 'none'):
        """Start repeating a command at the specified interval."""
        extras = {'checksum': checksum, 'line_ending': line_ending}
        self._send_command(message, format_override=format_type, comment="", **extras)

        interval_s = interval_ms / 1000.0

        timer = self.set_interval(
            interval_s,
            lambda: self._send_command(message, format_override=format_type,
                                       comment=f"{button.label} (repeat)", **extras),
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
                self.query_one(f"#{button_id}", Button).remove_class("button-repeating")
            except NoMatches:
                # Button already recomposed away; the timer still needs stopping.
                pass
            self._stop_repeating_button(button_id)
        
        if self.repeating_buttons:
            self.log_message("Stopped all repeating buttons")

    # ========================================================================
    # LOGGING & UI HELPERS
    # ========================================================================

    def log_message(self, message, type: str = ''):
        """Log a message to the multi-format log panel, and to the capture if recording."""
        # One instant for both, so the capture file and the screen agree.
        now = datetime.now()
        try:
            panel = self.query_one(MultiFormatLog)
            panel.log_message(message, type, stamp=timestamp(now))
        except Exception as e:
            # Named `panel`, not `log`: binding `log` here made it local to the
            # function, so this very line raised UnboundLocalError and the real
            # error was never reported.
            log.error("Log error: %s - Message: %r", e, message)

        # getattr: log_message must stay safe on a half-built app (see tests).
        capture = getattr(self, 'capture', None)
        if capture is not None and capture.active:
            try:
                capture.write(now, type, message)
            except OSError as e:
                self._stop_capture(f"Recording stopped - write failed: {e}")

    # ========================================================================
    # FILTER, PAUSE & SESSION CAPTURE
    # ========================================================================

    def action_toggle_filter(self):
        """Show the log filter box (Ctrl+F again, or Esc, closes and clears it)."""
        panel = self.query_one(MultiFormatLog)
        if panel.filter_open:
            panel.action_close_filter()
        else:
            panel.open_filter()

    def action_toggle_pause(self):
        """Freeze the log view; traffic is still recorded and shown on resume."""
        panel = self.query_one(MultiFormatLog)
        panel.set_paused(not panel.paused)

    def action_toggle_capture(self):
        """Start recording the session to a file, or stop the current recording."""
        if self.capture.active:
            self._stop_capture()
            return

        def handle_file_save(file_path: Path | None) -> None:
            if file_path is None:
                self.log_message("Recording cancelled", 'info')
                return
            self.start_capture(file_path)

        default = datetime.now().strftime("session-%Y%m%d-%H%M%S.log")
        self.push_screen(
            CompactFileSave(".", title="Record session to", default_file=default),
            handle_file_save,
        )

    def start_capture(self, path) -> bool:
        """Begin appending every log entry to `path`."""
        try:
            self.capture.start(path)
        except OSError as e:
            self.log_message(f"Cannot record to {path}: {e}", 'error')
            return False
        self.query_one(MultiFormatLog).set_recording(self.capture.path.name)
        self.log_message(f"Recording session to {self.capture.path}", 'info')
        return True

    def _stop_capture(self, reason: str = None):
        path = self.capture.path
        self.capture.stop()
        try:
            self.query_one(MultiFormatLog).set_recording(None)
        except NoMatches:
            pass
        if reason:
            self.log_message(reason, 'error')
        else:
            self.log_message(f"Recording stopped: {path}", 'info')

    async def action_reload_css(self) -> None:
        """Re-read styles.tcss without restarting (Ctrl+R).

        The binding existed but the action did not, so the key silently did
        nothing. _on_css_change is what Textual's own --dev file watcher calls;
        guarded, because it is not public API.
        """
        handler = getattr(self, "_on_css_change", None)
        if handler is None:
            self.log_message(
                "CSS reload unavailable on this Textual version; "
                "run with `textual run --dev ui.app:TUIApp` instead",
                'error'
            )
            return
        await handler()
        self.log_message(f"Reloaded {self.CSS_PATH}", 'info')

    def action_clearlog_message(self):
        """Clear the log window."""
        try:
            self.query_one(MultiFormatLog).clear()
        except Exception as e:
            log.debug("clear failed: %s", e)

    # ========================================================================
    # APP LIFECYCLE
    # ========================================================================

    def action_quit(self):
        """Quit application and save all data."""
        self.log_message("Quitting...")
        self.save_config()
        self.save_settings()
        self.exit()