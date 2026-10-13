from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
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
from serialterminal.ui.widgets.log_panel import MultiFormatLog, DEFAULT_LOG_COLORS, KINDS
from serialterminal.ui.widgets.settings_screen import SettingsScreen
from serialterminal.ui.widgets.serial_bar import SerialBar
from serialterminal.ui.widgets.dynamic_control_buttons import (
    REPEAT_MARKER_CHOICES, ControlButton, DynamicControlButtons, RESERVED_IDS, _widget_id,
    repeat_marker,
)
from serialterminal.ui.widgets.button_editor import ButtonEditor
from serialterminal.ui.widgets.quick_send import QuickSend
from serialterminal.ui.widgets.file_pickers import CompactFileOpen, CompactFileSave

from serialterminal.sequence_handler import (
    SequenceHandler, ReceiveSequence, sequences_from_buttons,
)

from serialterminal.serial_comm.connection import SerialConnection
from serialterminal.serial_comm.receiver import SerialReceiver

from serialterminal.utils.docklight_interpreter import DocklightConfigInterpreter
from serialterminal.utils.formatting import timestamp
from serialterminal.utils.payload import build_frame
from serialterminal.utils.session_capture import SessionCapture
from serialterminal.utils.places import Places

log = logging.getLogger("serialterminal.app")


class _UnreadableConfig(Exception):
    """project.yml exists but cannot be used as a config."""


class SerialData(Message):
    """A received frame, posted from the receive thread."""

    def __init__(self, data: bytes):
        super().__init__()
        self.data = data


class SerialPortLost(Message):
    """The port failed under us, posted from the receive thread."""

    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason


def connection_hint(error: Exception, platform: str = None) -> str | None:
    """What to do about a failed port open, for the errors that differ by OS.

    pyserial passes the OS message through, which names the symptom but not
    the fix - and the fix depends on the platform.
    """
    import sys

    platform = platform or sys.platform
    text = str(error).lower()
    errno = getattr(error, "errno", None)
    if platform.startswith("linux") and (errno == 13 or "permission denied" in text):
        return ("Linux only lets members of the serial group open ports. Run "
                "`sudo usermod -aG dialout $USER` (`uucp` on Arch), then log out and back in.")
    if platform == "darwin" and ("resource busy" in text or errno == 16):
        return ("The port is busy: another program has it open. On macOS use the "
                "/dev/cu.* device rather than /dev/tty.*.")
    if platform == "win32" and ("access is denied" in text or "permissionerror" in text):
        return ("Windows reports Access denied when another program (a terminal, "
                "Docklight, a vendor tool) already has the port open. Close it and retry.")
    if "could not open port" in text and ("no such file" in text or "filenotfound" in text
                                           or "cannot find" in text):
        return "The port has gone away (unplugged?). Press Refresh to rescan."
    return None


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
        Binding("f2", "settings", "settings", show=True, tooltip="Theme and log colors"),
        Binding("ctrl+o", "edit_config", "edit", show=True, tooltip="Edit project.yml"),
        Binding("ctrl+l", "reload_config", "reload", show=True, tooltip="Reload project.yml"),
        # Not Ctrl+I alone: terminals send Ctrl+I and Tab as the same byte
        # (0x09), so on macOS and Linux it arrived as Tab and moved focus.
        Binding("ctrl+t,ctrl+i", "import_config", "import", show=True, tooltip="Import a config (.yml or Docklight .ptp)"),
        Binding("ctrl+e", "export_config", "export", show=True, tooltip="Export the config to a .yml file"),
        Binding("ctrl+n", "new_button", "new button", show=False, tooltip="Create a control button"),
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
            self._on_frame_received_threadsafe,
            on_lost=self._on_port_lost_threadsafe,
        )
        # Settings the open port was opened with; None while disconnected.
        self._active_line = None
        
        self.repeating_buttons = {}
        self.capture = SessionCapture()
        self.config_file = Path("project.yml")
        self.settings_file = Path("settings.yml")
        
        # Load user settings first (theme, preferences)
        self.settings = {}
        self.load_settings()
        # Recent files and favourites for the file dialogs, kept in settings.yml.
        self.places = Places(self.settings, self._save_settings_or_warn)
        
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
            yield DynamicControlButtons(config_data=self.config.get('buttons', []),
                                        repeat_marker=self.repeat_marker())
        footer = Footer()
        footer.compact = True  # an attribute, not a constructor argument, in Textual 4.0
        yield footer

    def on_mount(self):
        """Initialize UI components on mount."""
        self._app_thread_id = threading.get_ident()
        self.set_interval(0.5, self._check_connection)
        self._apply_log_colors()
        # Theme colours change with the theme - including a change made from
        # the command palette - so recolour the log whenever it changes.
        self.theme_changed_signal.subscribe(self, lambda theme: self._apply_log_colors())
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
                with open(self.settings_file, 'w', encoding='utf-8') as f:
                    yaml.dump(default_settings, f, default_flow_style=False)
                self.settings = default_settings
            else:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    self.settings = yaml.safe_load(f) or {}
                    
        except Exception as e:
            log.error("Error loading settings: %s", e)
            self.settings = {'ui': {'theme': 'nord'}, 'config': {'last_used': None}}

    def save_settings(self) -> bool:
        """Save user settings (settings.yml). Returns True if written."""
        self.last_settings_error = None
        try:
            # Update theme
            if 'ui' not in self.settings:
                self.settings['ui'] = {}
            self.settings['ui']['theme'] = self.theme
            
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.settings, f, default_flow_style=False)
            return True
                
        except Exception as e:
            log.error("Error saving settings: %s", e)
            self.last_settings_error = str(e)
            return False

    # Settings (F2) and favourites apply at once. A change that couldn't also
    # be written would vanish at the next start without a word, so say so.
    def _save_settings_or_warn(self) -> bool:
        if self.save_settings():
            return True
        self.notify(f"Applied, but couldn't save {self.settings_file}: "
                    f"{self.last_settings_error}", severity="error", timeout=8)
        return False

    def _save_config_or_warn(self) -> bool:
        if self.save_config():
            return True
        self.notify(f"Applied, but couldn't save {self.config_file}: "
                    f"{self.last_save_error}", severity="error", timeout=8)
        return False
    
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
                
                self.sequence_handler = self._build_sequence_handler()
                
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

    def save_config(self) -> bool:
        """Save unified configuration to project.yml. Returns True if written."""
        self.last_save_error = None
        if getattr(self, 'config_unreadable', None):
            # Writing now would replace the user's file - typo and all, but
            # otherwise intact - with the empty fallback config.
            log.warning("Not saving %s: it could not be read (%s)",
                        self.config_file, self.config_unreadable)
            self.last_save_error = f"{self.config_file} could not be read"
            return False
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
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            
            log.debug("Configuration saved to %s", self.config_file)
            return True

        except Exception as e:
            log.error("Error saving config: %s", e)
            self.last_save_error = str(e)
            return False

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
                    with open(file_path, 'r', encoding='utf-8') as f:
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
                    with open(backup_file, 'w', encoding='utf-8') as f:
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
                self.places.add_recent(file_path, "config")
                
            except yaml.YAMLError as e:
                self.log_message(f"Invalid YAML: {e}", 'error')
            except Exception as e:
                self.log_message(f"Error importing: {e}", 'error')
                import traceback
                traceback.print_exc()
        
        self.push_screen(
            CompactFileOpen(self._dialog_start("config"), filters=import_filters(),
                            places=self.places, kind="config"),
            handle_file_open,
        )

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
                with open(file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
                
                self.log_message(f"Config exported to: {file_path.name}", 'info')
                self.places.add_recent(file_path, "config")
                
                # Update last_used in settings
                if 'config' not in self.settings:
                    self.settings['config'] = {}
                self.settings['config']['last_used'] = str(file_path)
                self.save_settings()
                
            except Exception as e:
                self.log_message(f"Error exporting: {e}", 'error')
        
        # Show file picker - FileSave just takes the starting directory
        file_save_screen = CompactFileSave(self._dialog_start("config"),
                                           places=self.places, kind="config")
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
        if isinstance(previous, str) and previous != 'none':
            try:
                select.value = previous
            except InvalidSelectValueError:
                self.log_message(f"Port {previous} is no longer available", 'error')

    def _line_settings(self) -> tuple | None:
        """(port, baud, parity, data bits, stop bits) as the selectors show them."""
        try:
            return tuple(self.query_one(widget_id, Select).value for widget_id in (
                "#serial-port-select", "#serial-baud", "#serial-parity",
                "#serial-bits", "#serial-stop-bits"))
        except NoMatches:
            return None

    def frame_gap(self) -> str:
        """'auto' or a number of milliseconds, as a string - project.yml's serial.frame_gap."""
        serial_cfg = self.config.get('serial') if isinstance(self.config.get('serial'), dict) else {}
        gap = str(serial_cfg.get('frame_gap', 'auto')).strip()
        return gap if gap == 'auto' or gap.isdigit() else 'auto'

    def set_frame_gap(self, gap: str):
        """Change the frame gap (Settings, F2): saved with the project, applied at once."""
        serial_cfg = self.config.setdefault('serial', {})
        if not isinstance(serial_cfg, dict):
            serial_cfg = self.config['serial'] = {}
        serial_cfg['frame_gap'] = gap if gap == 'auto' else int(gap)
        self._save_config_or_warn()
        if self.serial_conn.connected:
            self._apply_frame_gap()

    def _apply_frame_gap(self, baud_rate: int | None = None):
        """Frame received bytes with the configured gap."""
        gap = self.frame_gap()
        if gap == "auto":
            if baud_rate is None:
                try:
                    baud_rate = int(self.query_one("#serial-baud", Select).value)
                except (NoMatches, ValueError):
                    baud_rate = 9600
            self.receiver.set_baud_rate(baud_rate)
        else:
            self.receiver.set_timeout(int(gap) / 1000)

    def _ensure_connected(self) -> bool:
        """Connect with the current settings if needed, before a send.

        Sending while disconnected used to just log an error; now it connects
        first, so pressing a button or Enter is enough.
        """
        if self.serial_conn.connected:
            return True
        if self._connect_serial():
            return True
        self.log_message("Not connected - nothing sent", 'error')
        return False

    def on_select_changed(self, event: Select.Changed):
        select_id = event.select.id
        if select_id not in ("serial-port-select", "serial-baud", "serial-parity",
                             "serial-bits", "serial-stop-bits"):
            return
        # Compare what the selectors show with what the open port uses, rather
        # than reacting to every Changed event: restoring settings and Refresh
        # set values programmatically, and only a real difference matters.
        active = self._active_line
        if not self.serial_conn.connected or active is None:
            return
        current = self._line_settings()
        if current is None or current == active:
            return
        if current[0] != active[0]:
            self._disconnect_serial(
                f"Disconnected from {active[0]}: port changed to {current[0]}. "
                f"The next send connects to it.")
        else:
            self._disconnect_serial(
                f"Disconnected from {active[0]}: line settings changed. "
                f"The next send reconnects with them.")

    def _connect_serial(self) -> bool:
        """Connect to serial port using SerialConnection wrapper. Returns True on success."""
        port = "the port"
        try:
            port = self.query_one("#serial-port-select", Select).value
            if not isinstance(port, str) or port == "none":
                self.log_message("No serial port selected", 'error')
                return False

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
            self._active_line = (port, str(baud_rate), parity_val, bits_val, stop_val)

            self._apply_frame_gap(baud_rate)
            self.receiver.start()

            self.log_message(f"Connected to {port} at {baud_rate} baud")

            self.config["serial"] = {
                **(self.config.get("serial") if isinstance(self.config.get("serial"), dict) else {}),
                "port": port,
                "baud_rate": baud_rate,
                "parity": parity_val,
                "data_bits": bits_val,
                "stop_bits": stop_val,
            }
            self.save_config()
            return True

        except ValueError as e:
            self.log_message(f"Invalid configuration value: {e}", 'error')
        except serial.SerialException as e:
            self.com_error(f"Error: couldn't open {port}", str(e), connection_hint(e))
        except Exception as e:
            self.com_error(f"Error: couldn't open {port}", f"{type(e).__name__}: {e}")
        return False

    def _disconnect_serial(self, message: str | None = "Serial disconnected", type: str = 'info'):
        """Disconnect from serial port."""
        self._stop_all_repeating_buttons()
        # stop() returns bytes that arrived but never completed a frame; log
        # them here, on the UI thread, instead of losing them.
        tail = self.receiver.stop()
        if tail:
            self._on_frame_received(tail)
        self.serial_conn.disconnect()
        self._active_line = None
        try:
            self.query_one("#serial-connect", Button).disabled = False
            self.query_one("#serial-disconnect", Button).disabled = True
        except NoMatches:
            pass

        self._set_serial_status(False)
        if message:
            self.log_message(message, type)

    def _on_port_lost_threadsafe(self, reason: str):
        """Called on the receive thread when the port fails under us.

        Posted rather than called through call_from_thread, for the same reason
        as frames: the cleanup joins the receive thread, so it must not be
        waiting on us (see _on_frame_received_threadsafe).
        """
        self.post_message(SerialPortLost(reason))

    def on_serial_port_lost(self, message: SerialPortLost):
        self._on_port_lost(message.reason)

    def _check_connection(self):
        """Safety net, twice a second: never show Connected for a port that's gone.

        The receive thread normally reports a loss at once; this catches any
        path that doesn't, so the status can't stay stuck on Connected.
        """
        if self._active_line is not None and not self.serial_conn.connected:
            self._on_port_lost(getattr(self.serial_conn, "lost_reason", None)
                               or "connection lost")

    def _on_port_lost(self, reason: str):
        """The device went away (unplugged, reset): say so once and reset the UI."""
        if self._active_line is None:
            return  # already disconnected on purpose
        port = self._active_line[0]
        self._disconnect_serial(None)
        self.com_error(f"Error: connection to {port} lost", reason,
                       "The device was unplugged or reset; the next send reconnects.")

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
        if not self._ensure_connected():
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
                self.com_error("Error: send failed",
                               getattr(self.serial_conn, "last_error", None)
                               or "the port did not accept the data",
                               "Unplugged? The next send reconnects.")
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
                # Same rule as a normal send: [TX] only for bytes that left.
                if not self.serial_conn.write(response_bytes):
                    self.com_error(f"Error: auto-reply '{sequence.name}' not sent",
                                   getattr(self.serial_conn, "last_error", None)
                                   or "the port did not accept the data")
                    return
                self.log_message(response_bytes, 'tx')
                self.log_message(f"Sequence: {sequence.name}", 'info')
        except Exception as e:
            self.com_error(f"Error: auto-reply '{sequence.name}' not sent",
                           f"{type(e).__name__}: {e}")

    def _on_frame_received_threadsafe(self, frame_bytes: bytes):
        """Hand a frame to the UI thread from the receive thread.

        Posted, not call_from_thread: that blocks the receive thread until the
        UI has handled the frame, and the UI, when disconnecting, waits for the
        receive thread to finish - each waited on the other until a 2 s join
        timeout broke the deadlock, freezing the app with Connected still shown.
        post_message is thread-safe and returns at once; frames keep their order.
        """
        if threading.get_ident() == self._app_thread_id:
            self._on_frame_received(frame_bytes)
        else:
            self.post_message(SerialData(frame_bytes))

    def on_serial_data(self, message: SerialData):
        self._on_frame_received(message.data)

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
            label = getattr(event.button, 'plain_label', str(event.button.label))
            repeat = getattr(event.button, 'repeat', None)
            extras = {
                'checksum': getattr(event.button, 'checksum', 'none'),
                'line_ending': getattr(event.button, 'line_ending', 'none'),
            }

            if not self._ensure_connected():
                return
            # Check if this is a repeating button (repeat > 0)
            if repeat is not None and repeat > 0:
                # This is a repeating button
                self._toggle_repeat_button(event.button, message, format_type, repeat, **extras)
            else:
                # Regular one-shot button - use format override
                self._send_command(message, format_override=format_type, comment=label, **extras)

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
        label = getattr(button, 'plain_label', str(button.label))
        
        if interval_ms <= 0:
            self.log_message(f"Cannot repeat {label}: invalid interval", 'error')
            return
        
        if button_id in self.repeating_buttons:
            # Button is currently repeating - stop it
            self._stop_repeating_button(button_id)
            self._show_running(button, False)
            self.log_message(f"Stopped repeating: {label}")
        else:
            # Start repeating
            self._start_repeating_button(button_id, button, message, format_type, interval_ms,
                                         checksum=checksum, line_ending=line_ending)
            self._show_running(button, True)

    @staticmethod
    def _show_running(button: Button, running: bool):
        if isinstance(button, ControlButton):
            button.set_running(running)  # also recolours the repeat marker
        else:
            button.set_class(running, "button-repeating")

    def _start_repeating_button(self, button_id: str, button: Button, message: str, format_type: str,
                                interval_ms: int, checksum: str = 'none', line_ending: str = 'none'):
        """Start repeating a command at the specified interval."""
        extras = {'checksum': checksum, 'line_ending': line_ending}
        self._send_command(message, format_override=format_type, comment="", **extras)

        interval_s = interval_ms / 1000.0
        label = getattr(button, 'plain_label', str(button.label))

        timer = self.set_interval(
            interval_s,
            lambda: self._send_command(message, format_override=format_type,
                                       comment=f"{label} (repeat)", **extras),
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
        # Checked before the loop empties it: checked after, as it was, the
        # message never showed.
        any_running = bool(self.repeating_buttons)
        for button_id in list(self.repeating_buttons.keys()):
            try:
                self._show_running(self.query_one(f"#{button_id}", Button), False)
            except NoMatches:
                # Button already recomposed away; the timer still needs stopping.
                pass
            self._stop_repeating_button(button_id)
        
        if any_running:
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
            CompactFileSave(self._dialog_start("capture"), title="Record session to",
                            default_file=default, places=self.places, kind="capture"),
            handle_file_save,
        )

    def _dialog_start(self, kind: str) -> str:
        """Open file dialogs where the last file of this kind was, not always in '.'."""
        recent = self.places.recent(kind)
        return str(Path(recent[0]).parent) if recent else "."

    def start_capture(self, path) -> bool:
        """Begin appending every log entry to `path`."""
        try:
            self.capture.start(path)
        except OSError as e:
            self.log_message(f"Cannot record to {path}: {e}", 'error')
            return False
        self.query_one(MultiFormatLog).set_recording(self.capture.path.name)
        self.log_message(f"Recording session to {self.capture.path}", 'info')
        self.places.add_recent(self.capture.path, "capture")
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

    # ========================================================================
    # BUTTON EDITOR
    # ========================================================================

    def _build_sequence_handler(self) -> SequenceHandler:
        """Sequences from the `sequences` section plus buttons set to auto-send."""
        sequences = self.config.get('sequences', [])
        derived = sequences_from_buttons(self.config.get('buttons'))
        if isinstance(sequences, list):
            return SequenceHandler(config_data=sequences + derived)
        # A malformed section is still handed over as-is so it gets reported.
        return SequenceHandler(config_data=sequences)

    def action_new_button(self):
        self.open_button_editor(None)

    def on_dynamic_control_buttons_edit_requested(self, message: DynamicControlButtons.EditRequested):
        self.open_button_editor(message.index)

    def open_button_editor(self, index: int | None):
        """Open the editor on project.yml's buttons[index], or on a new button."""
        problem = self._buttons_section_problem()
        if problem:
            self.log_message(f"Can't edit buttons: {problem}", 'error')
            return
        buttons = self.config.get('buttons') or []
        entry = None
        if index is not None:
            if not 0 <= index < len(buttons):
                self.log_message(f"Button {index + 1} no longer exists - reload (Ctrl+L)", 'error')
                return
            entry = buttons[index]
        self.push_screen(ButtonEditor(entry, index))

    def _buttons_section_problem(self) -> str | None:
        if self.config_unreadable:
            return f"{self.config_file} couldn't be read - fix it (Ctrl+O) and reload (Ctrl+L)"
        buttons = self.config.get('buttons')
        if buttons is not None and not isinstance(buttons, list):
            return f"'buttons' in {self.config_file} isn't a list - fix it (Ctrl+O) first"
        return None

    def _new_button_id(self, label: str) -> str:
        """A legal id for a new button, unique in project.yml and among the app's widgets."""
        taken = set(RESERVED_IDS)
        taken.update(str(b.get('id')) for b in self.config.get('buttons') or []
                     if isinstance(b, dict))
        base = _widget_id(label.lower(), len(taken)) if label.strip() else "button"
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def _stop_repeat_for_index(self, index: int):
        """Stop the repeat timer of the button built from buttons[index], if running."""
        for button in self.query(".control-button"):
            if getattr(button, 'source_index', None) == index and button.id in self.repeating_buttons:
                self._stop_repeating_button(button.id)
                self._show_running(button, False)

    async def save_button(self, index: int | None, entry: dict) -> int:
        """Write a button from the editor into project.yml and show it.

        Returns its index in the buttons list. Raises ValueError, with a message
        for the user, if it can't be saved.
        """
        problem = self._buttons_section_problem()
        if problem:
            raise ValueError(problem)
        buttons = self.config.setdefault('buttons', [])
        if buttons is None:
            buttons = self.config['buttons'] = []

        if index is None:
            entry = {'id': self._new_button_id(entry.get('label', '')), **entry}
            buttons.append(entry)
            index = len(buttons) - 1
        else:
            self._stop_repeat_for_index(index)  # its command may have changed
            buttons[index] = entry

        if not self.save_config():
            raise ValueError(f"Couldn't write {self.config_file}: {self.last_save_error}")
        await self._refresh_buttons_and_sequences()
        self.log_message(f"Saved button '{entry.get('label', entry.get('id'))}'", 'info')
        return index

    async def delete_button(self, index: int):
        buttons = self.config.get('buttons') or []
        if not 0 <= index < len(buttons):
            return
        self._stop_repeat_for_index(index)
        removed = buttons.pop(index)
        if not self.save_config():
            buttons.insert(index, removed)
            self.log_message(f"Couldn't write {self.config_file}: {self.last_save_error}", 'error')
            return
        await self._refresh_buttons_and_sequences()
        label = removed.get('label', removed.get('id')) if isinstance(removed, dict) else removed
        self.log_message(f"Deleted button '{label}'", 'info')

    async def _refresh_buttons_and_sequences(self):
        """Rebuild the panel and the auto-send sequences after an edit.

        Unlike a full reload (Ctrl+L), other buttons' repeat timers keep
        running: they hold their own command, so they only need their
        highlight restored on the rebuilt widgets.
        """
        panel = self.query_one(DynamicControlButtons)
        panel.repeat_marker = self.repeat_marker()
        await panel.rebuild(self.config.get('buttons', []))
        self.sequence_handler = self._build_sequence_handler()
        for button_id in list(self.repeating_buttons):
            try:
                self._show_running(self.query_one(f"#{button_id}", Button), True)
            except NoMatches:
                self._stop_repeating_button(button_id)
        for problem in panel.problems:
            self.log_message(problem, 'error')

    # ========================================================================
    # SETTINGS (F2)
    # ========================================================================

    def action_settings(self):
        self.push_screen(SettingsScreen())

    def verbose_errors(self) -> bool:
        return self.settings.get('verbose_errors') is True

    def set_verbose_errors(self, on: bool):
        self.settings['verbose_errors'] = bool(on)
        self._save_settings_or_warn()

    def com_error(self, short: str, detail: str | None = None, hint: str | None = None):
        """Report a serial-port problem.

        A short line by default ("Error: couldn't open COM4"); with Verbose
        errors on (Settings, F2) also the system's message and a hint. The
        detail always goes to serialterminal.log.
        """
        if detail:
            log.error("%s: %s", short, detail)
        else:
            log.error("%s", short)
        if self.verbose_errors() and detail:
            self.log_message(f"{short}: {detail}", 'error')
            if hint:
                self.log_message(hint, 'error')
        else:
            self.log_message(short, 'error')

    def log_colors(self) -> dict:
        """Colour per log kind: settings.yml's log_colors over the defaults."""
        configured = self.settings.get('log_colors')
        configured = configured if isinstance(configured, dict) else {}
        return {kind: str(configured.get(kind) or DEFAULT_LOG_COLORS[kind]) for kind in KINDS}

    def _apply_log_colors(self):
        try:
            self.query_one(MultiFormatLog).apply_colors(self.log_colors())
        except NoMatches:
            pass

    def set_log_color(self, kind: str, value: str):
        colors = self.settings.get('log_colors')
        if not isinstance(colors, dict):
            colors = self.settings['log_colors'] = {}
        colors[kind] = value
        self._save_settings_or_warn()
        self._apply_log_colors()

    def reset_log_colors(self):
        self.settings.pop('log_colors', None)
        self._save_settings_or_warn()
        self._apply_log_colors()

    def set_theme(self, theme: str):
        self.theme = theme  # recolours the log via theme_changed_signal
        self._save_settings_or_warn()

    def repeat_marker_choice(self) -> str:
        """settings.yml's repeat_marker: auto (default), symbol (↻) or text ([R])."""
        choice = self.settings.get('repeat_marker')
        return choice if choice in REPEAT_MARKER_CHOICES else 'auto'

    def repeat_marker(self) -> str:
        """The marker shown on buttons that resend on a timer."""
        return repeat_marker(self.repeat_marker_choice())

    async def set_repeat_marker(self, choice: str):
        self.settings['repeat_marker'] = choice
        self._save_settings_or_warn()
        await self._refresh_buttons_and_sequences()

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