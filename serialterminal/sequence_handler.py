from pathlib import Path
import yaml
import re
import logging
from typing import List, Dict, Any, Optional

from serialterminal.utils.payload import build_frame

log = logging.getLogger("serialterminal.sequence")

# Wildcard used by every receive format. A character class rather than "."
# so it also matches CR/LF, which appear in most real serial framing.
ANY_BYTE = r"[\x00-\xFF]"


class ReceiveSequence:
    """Represents a single receive/send sequence."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get('name', 'Unnamed')
        self.active = config.get('active', True)
        self.delay = self._coerce_delay(config.get('delay'))
        self.comment = config.get('comment', '')
        
        # Receive configuration
        receive_cfg = config.get('receive', {})
        self.receive_data = receive_cfg.get('data', '')
        self.receive_format = receive_cfg.get('format', 'hex')
        
        # Send configuration
        send_cfg = config.get('send', {})
        self.send_data = send_cfg.get('data', '')
        self.send_format = send_cfg.get('format', 'hex')
        self.send_checksum = send_cfg.get('checksum', 'none')
        self.send_line_ending = send_cfg.get('line_ending', 'none')
        
        # Compile the pattern for matching
        self.pattern = self._compile_pattern()
    
    @staticmethod
    def _coerce_delay(raw) -> float:
        """Convert a config delay in milliseconds to seconds.

        YAML hands us None for `delay:` with no value, and a string if it was
        quoted. Neither should take down the whole sequence list, so anything
        uninterpretable falls back to no delay.
        """
        if raw is None or raw == "":
            return 0.0
        try:
            return max(0.0, float(raw) / 1000.0)
        except (TypeError, ValueError):
            log.warning("Invalid delay %r - treating as 0", raw)
            return 0.0

    def _compile_pattern(self) -> Optional[bytes]:
        """
        Compile the receive pattern into a regex that handles wildcards.
        Returns a compiled regex pattern or None if invalid.
        """
        if not str(self.receive_data).strip():
            # An empty pattern compiles to an empty regex, which matches every
            # frame - the sequence would answer every byte that arrived.
            log.error("Sequence '%s': receive data is empty", self.name)
            return None

        try:
            if self.receive_format == "hex":
                # Split into per-byte hex tokens (split() collapses whitespace)
                hex_parts = self.receive_data.split()
                
                # Build regex pattern
                pattern_parts = []
                for part in hex_parts:
                    if part.strip() == "??":
                        # Wildcard - match any byte
                        pattern_parts.append(r"[\x00-\xFF]")
                    else:
                        # Specific byte value
                        byte_val = int(part, 16)
                        pattern_parts.append(re.escape(bytes([byte_val]).decode('latin-1')))
                
                pattern_str = "".join(pattern_parts)
                return re.compile(pattern_str.encode('latin-1'))
                
            elif self.receive_format == "ascii":
                # '??' is the only wildcard; everything else is a literal.
                # Escape the literal runs, or regex metacharacters that occur
                # naturally in payloads ($, ., *, +, (, [ ...) silently change
                # what matches - e.g. "PRICE $1.00" would match nothing at all.
                literals = self.receive_data.split("??")
                pattern_str = ANY_BYTE.join(re.escape(part) for part in literals)
                return re.compile(pattern_str.encode('ascii'))
                
            elif self.receive_format == "decimal":
                dec_parts = self.receive_data.split()
                pattern_parts = []
                for part in dec_parts:
                    if part.strip() == "??":
                        pattern_parts.append(r"[\x00-\xFF]")
                    else:
                        byte_val = int(part)
                        pattern_parts.append(re.escape(bytes([byte_val]).decode('latin-1')))
                
                pattern_str = "".join(pattern_parts)
                return re.compile(pattern_str.encode('latin-1'))
                
            elif self.receive_format == "binary":
                # Remove spaces and split into 8-bit chunks
                bin_str = self.receive_data.replace(" ", "")
                pattern_parts = []
                
                for i in range(0, len(bin_str), 8):
                    chunk = bin_str[i:i+8]
                    if chunk == "????????":
                        pattern_parts.append(r"[\x00-\xFF]")
                    else:
                        byte_val = int(chunk, 2)
                        pattern_parts.append(re.escape(bytes([byte_val]).decode('latin-1')))
                
                pattern_str = "".join(pattern_parts)
                return re.compile(pattern_str.encode('latin-1'))

            log.error(
                "Sequence '%s': unknown receive format %r (expected one of "
                "hex, ascii, decimal, binary)", self.name, self.receive_format
            )
            return None

        except Exception as e:
            log.error("Error compiling pattern for sequence '%s': %s", self.name, e)
            return None
    
    def matches(self, data: bytes) -> bool:
        """Check if the received data matches this sequence pattern."""
        if not self.active or self.pattern is None:
            return False
        
        return self.pattern.search(data) is not None
    
    def get_response_bytes(self) -> bytes:
        """Convert the send data to bytes, with optional checksum and line ending."""
        try:
            return build_frame(
                self.send_data, self.send_format,
                self.send_checksum, self.send_line_ending,
            )
        except Exception as e:
            log.error("Error converting response for sequence '%s': %s", self.name, e)
            return b""


class SequenceHandler:
    """Manages all receive sequences."""
    
    def __init__(self, config_path: str = None, config_data: list = None):
        """
        Initialize SequenceHandler.
        
        Args:
            config_path: Path to YAML file (legacy support)
            config_data: List of sequence dictionaries from unified config
        """
        self.config_path = Path(config_path) if config_path else None
        self.sequences: List[ReceiveSequence] = []
        self.skipped = 0
        
        if config_data is not None:
            # Load from provided data (unified config)
            self.load_sequences_from_data(config_data)
        elif self.config_path:
            # Load from file (legacy support)
            self.load_sequences()
        else:
            log.debug("SequenceHandler initialized with no config")
    
    def load_sequences_from_data(self, sequences_data: list) -> int:
        """Load sequences from provided list data.

        Each entry is parsed independently: one malformed sequence is skipped
        and reported rather than aborting the loop, which previously discarded
        every sequence defined after the bad one.

        Returns:
            The number of entries that were skipped.
        """
        self.sequences.clear()
        self.skipped = 0

        if not sequences_data:
            log.debug("No sequences in config data")
            return 0

        if not isinstance(sequences_data, list):
            log.error("Sequences section must be a list, got %s",
                      type(sequences_data).__name__)
            self.skipped = 1
            return 1

        for i, seq_config in enumerate(sequences_data):
            if not isinstance(seq_config, dict):
                log.error("Sequence %d is %s, expected a mapping - skipped",
                          i, type(seq_config).__name__)
                self.skipped += 1
                continue
            try:
                self.sequences.append(ReceiveSequence(seq_config))
            except Exception as e:
                log.exception("Sequence %d (%r) failed to load - skipped: %s",
                              i, seq_config.get('name', '?'), e)
                self.skipped += 1

        log.debug("Loaded %d sequences from config data (%d skipped)",
                  len(self.sequences), self.skipped)
        return self.skipped
    
    def load_sequences(self):
        """Load sequences from YAML configuration file (legacy support)."""
        self.sequences.clear()

        if not (self.config_path and self.config_path.exists()):
            log.debug("Sequence config file not found: %s", self.config_path)
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            log.debug("Found sequence file: %s", self.config_path)
        except Exception as e:
            log.exception("Error reading sequence file %s: %s", self.config_path, e)
            return

        if not (config and 'sequences' in config):
            log.debug("No 'sequences' key found in config file")
            return

        # Delegate so file-loaded sequences get the same per-entry isolation.
        self.load_sequences_from_data(config['sequences'])
    
    def reload_sequences(self, config_data: list = None):
        """
        Reload sequences from data or file.
        
        Args:
            config_data: Optional list of sequence dictionaries
        """
        if config_data is not None:
            self.load_sequences_from_data(config_data)
        elif self.config_path:
            self.load_sequences()
        else:
            log.debug("Cannot reload: no config source available")
    
    def check_data(self, data: bytes) -> Optional[ReceiveSequence]:
        """
        Check if received data matches any active sequence.
        Returns the first matching sequence, or None.
        """
        for sequence in self.sequences:
            if sequence.matches(data):
                return sequence
        return None
    
    def get_active_sequences(self) -> List[ReceiveSequence]:
        """Get list of all active sequences."""
        return [seq for seq in self.sequences if seq.active]
    
    def get_sequence_by_name(self, name: str) -> Optional[ReceiveSequence]:
        """Get a specific sequence by name."""
        for seq in self.sequences:
            if seq.name == name:
                return seq
        return None
    
    def toggle_sequence(self, name: str) -> bool:
        """Toggle a sequence active state. Returns new state."""
        seq = self.get_sequence_by_name(name)
        if seq:
            seq.active = not seq.active
            return seq.active
        return False

def sequences_from_buttons(buttons) -> list:
    """Receive sequences for the buttons that have `auto_send` set.

    A button can double as an automatic answer, as in Docklight: when a frame
    matching its `auto_send.receive` pattern arrives, the button's own command
    (with its checksum and line ending) is sent, after `auto_send.delay` ms.
    Expressed as ordinary sequence configs so matching, delays and logging are
    exactly those of the `sequences` section.

    Button entries that aren't mappings are ignored here; the button panel
    reports them.
    """
    derived = []
    if not isinstance(buttons, list):
        return derived
    for button in buttons:
        if not isinstance(button, dict):
            continue
        auto = button.get('auto_send')
        if not isinstance(auto, dict) or auto.get('enabled', True) is False:
            continue
        receive = auto.get('receive') if isinstance(auto.get('receive'), dict) else {}
        label = button.get('label') or button.get('id') or 'button'
        derived.append({
            'name': f"{label} (auto-send)",
            'active': True,
            'delay': auto.get('delay', 0),
            'comment': f"Auto-sent: {label}",
            'receive': {
                'data': receive.get('data', ''),
                'format': receive.get('format', 'hex'),
            },
            'send': {
                'data': button.get('message', ''),
                'format': button.get('format', 'ascii'),
                'checksum': button.get('checksum', 'none'),
                'line_ending': button.get('line_ending', 'none'),
            },
        })
    return derived
