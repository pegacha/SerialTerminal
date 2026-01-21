from pathlib import Path
import yaml
import re
from typing import List, Dict, Any, Optional
import time


class ReceiveSequence:
    """Represents a single receive/send sequence."""
    
    def __init__(self, config: Dict[str, Any]):
        self.name = config.get('name', 'Unnamed')
        self.active = config.get('active', True)
        self.delay = config.get('delay', 0) / 1000.0  # Convert ms to seconds
        self.comment = config.get('comment', '')
        
        # Receive configuration
        receive_cfg = config.get('receive', {})
        self.receive_data = receive_cfg.get('data', '')
        self.receive_format = receive_cfg.get('format', 'hex')
        
        # Send configuration
        send_cfg = config.get('send', {})
        self.send_data = send_cfg.get('data', '')
        self.send_format = send_cfg.get('format', 'hex')
        
        # Compile the pattern for matching
        self.pattern = self._compile_pattern()
    
    def _compile_pattern(self) -> Optional[bytes]:
        """
        Compile the receive pattern into a regex that handles wildcards.
        Returns a compiled regex pattern or None if invalid.
        """
        try:
            if self.receive_format == "hex":
                # Remove extra spaces and split into bytes
                hex_parts = self.receive_data.replace(" ", " ").split()
                
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
                # For ASCII, ?? represents any character
                pattern_str = self.receive_data.replace("??", ".")
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
                
        except Exception as e:
            print(f"Error compiling pattern for sequence '{self.name}': {e}")
            return None
    
    def matches(self, data: bytes) -> bool:
        """Check if the received data matches this sequence pattern."""
        if not self.active or self.pattern is None:
            return False
        
        return self.pattern.search(data) is not None
    
    def get_response_bytes(self) -> bytes:
        """Convert the send data to bytes based on format."""
        try:
            if self.send_format == "hex":
                hex_str = self.send_data.replace(" ", "").replace("0x", "")
                return bytes.fromhex(hex_str)
            elif self.send_format == "decimal":
                dec_values = self.send_data.split()
                return bytes([int(val) for val in dec_values])
            elif self.send_format == "binary":
                bin_values = self.send_data.replace(" ", "")
                byte_values = [bin_values[i:i+8] for i in range(0, len(bin_values), 8)]
                return bytes([int(b, 2) for b in byte_values])
            else:  # ascii
                return self.send_data.encode('ascii')
        except Exception as e:
            print(f"Error converting response for sequence '{self.name}': {e}")
            return b""


class SequenceHandler:
    """Manages all receive sequences."""
    
    def __init__(self, config_path: str = "sequences.yml"):
        self.config_path = Path(config_path)
        self.sequences: List[ReceiveSequence] = []
        self.load_sequences()
    
    def load_sequences(self):
        """Load sequences from YAML configuration file."""
        self.sequences.clear()
        
        try:
            if  self.config_path.exists():
                # Load sequences
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    print(f"Found sequence file")
                
                if config and 'sequences' in config:
                    for seq_config in config['sequences']:
                        sequence = ReceiveSequence(seq_config)
                        self.sequences.append(sequence)
                    
                    print(f"Loaded {len(self.sequences)} sequences")
            
        except Exception as e:
            print(f"Error loading sequences: {e}")
    
    def reload_sequences(self):
        """Reload sequences from file."""
        self.load_sequences()
    
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