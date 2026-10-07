from pathlib import Path
import yaml
from typing import Dict, List, Any
import re


class DocklightConfigInterpreter:
    """Interpreter for Docklight .ptp format to unified config."""
    
    def __init__(self):
        self.buttons = []
        self.sequences = []
        self.serial_config = {}
        
    def parse_file(self, filepath: Path) -> Dict[str, Any]:
        """Parse Docklight config file and return unified config dict."""
        raw = Path(filepath).read_bytes()
        # Docklight is a Windows program and writes .ptp files in the ANSI
        # code page, not UTF-8. Reading with the platform default happened to
        # work on Windows but raised UnicodeDecodeError on macOS and Linux as
        # soon as a label had an accented character. UTF-8 first (a file
        # re-saved by a modern editor), then cp1252, which can't fail.
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        lines = [line.strip() for line in text.splitlines()]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            if line == "COMMSETTINGS":
                i = self._parse_comm_settings(lines, i + 1)
            elif line == "SEND":
                i = self._parse_send(lines, i + 1)
            elif line == "RECEIVE":
                i = self._parse_receive(lines, i + 1)
            else:
                i += 1
        
        return {
            'serial': self.serial_config,
            'ui': {'theme': 'nord'},
            'buttons': self.buttons,
            'sequences': self.sequences
        }
    
    def _parse_comm_settings(self, lines: List[str], start_idx: int) -> int:
        """Parse COMMSETTINGS section."""
        idx = start_idx
        
        # Skip index
        idx += 1
        
        # Parse ports (we'll use the first one)
        port1 = lines[idx]
        idx += 1
        port2 = lines[idx]
        idx += 1
        
        # Parse baud rate
        baud_rate = int(lines[idx])
        idx += 1
        
        # Skip remaining settings (parity, data bits, stop bits, etc.)
        # They appear to be encoded differently in Docklight format
        idx += 5
        
        self.serial_config = {
            'port': port1 if port1.startswith('COM') else 'none',
            'baud_rate': baud_rate,
            'parity': 'N',
            'data_bits': '8',
            'stop_bits': '1'
        }
        
        return idx
    
    def _parse_send(self, lines: List[str], start_idx: int) -> int:
        """Parse SEND (button) section."""
        idx = start_idx
        
        # Index
        button_idx = int(lines[idx])
        idx += 1
        
        # Title/Label
        label = lines[idx]
        idx += 1
        
        # Command (hex string with spaces)
        command = lines[idx]
        idx += 1
        
        # Repeat enabled (1 = yes, 0 = no)
        repeat_enabled = int(lines[idx])
        idx += 1
        
        # Repeat frequency in seconds (can be decimal like .06)
        try:
            repeat_freq_sec = float(lines[idx])  # Changed from int to float
        except ValueError:
            repeat_freq_sec = 0
        idx += 1
        
        # Create button config
        button = {
            'id': f"docklight-send-{button_idx}",
            'label': label,
            'message': command,
            'format': 'hex',
            'tooltip': f"Send {label}"
        }
        
        # Add repeat if enabled (convert seconds to milliseconds)
        if repeat_enabled == 1 and repeat_freq_sec > 0:
            button['repeat'] = int(repeat_freq_sec * 1000)  # Convert to int milliseconds
        else:
            button['repeat'] = 0
        
        self.buttons.append(button)
        
        return idx
    
    def _parse_receive(self, lines: List[str], start_idx: int) -> int:
        """Parse RECEIVE (sequence) section."""
        idx = start_idx
        
        # Index
        seq_idx = int(lines[idx])
        idx += 1
        
        # Name/Comment for display
        name = lines[idx]
        idx += 1
        
        # Receive pattern (with ?? wildcards and ## for data bytes)
        receive_pattern = lines[idx]
        # Convert ## to ?? (both are wildcards in Docklight)
        receive_pattern = receive_pattern.replace('##', '??')
        idx += 1
        
        # Button index to trigger (-1 means no response)
        button_to_trigger = int(lines[idx])
        idx += 1
        
        # Skip next line (appears to be a flag)
        idx += 1
        
        # Check if there's a COMMENT line
        comment = ""
        if idx < len(lines) and lines[idx].startswith("COMMENT"):
            comment_line = lines[idx]
            # Extract comment text (remove "COMMENT " prefix)
            comment = comment_line[8:] if len(comment_line) > 8 else ""
            # Remove Docklight variable placeholders like %_D(4,2)
            comment = re.sub(r'%_[A-Z]\(\d+,\d+\)', '[VALUE]', comment)
            comment = re.sub(r'%_[A-Z]\(\d+\)', '[VALUE]', comment)
            idx += 1
        
        # Skip remaining flags (3 lines)
        idx += 3
        
        # Create sequence config
        sequence = {
            'name': name,
            'active': True,
            'delay': 0,
            'receive': {
                'data': receive_pattern,
                'format': 'hex'
            },
            'comment': comment if comment else name
        }
        
        # Add send response if button index is valid
        if button_to_trigger >= 0 and button_to_trigger < len(self.buttons):
            target_button = self.buttons[button_to_trigger]
            sequence['send'] = {
                'data': target_button['message'],
                'format': 'hex'
            }
        else:
            # No response, just log
            sequence['send'] = {
                'data': '',
                'format': 'hex'
            }
        
        self.sequences.append(sequence)
        
        return idx
    
    def convert_file(self, input_path: Path, output_path: Path = None) -> Dict[str, Any]:
        """
        Convert Docklight config to unified config and optionally save.
        
        Args:
            input_path: Path to Docklight .ptp file
            output_path: Optional path to save unified config (default: project.yml)
        
        Returns:
            Unified config dictionary
        """
        config = self.parse_file(input_path)
        
        if output_path is None:
            output_path = Path("project.yml")
        
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        print(f"Converted Docklight config {input_path} -> {output_path}")
        print(f"  Buttons: {len(config['buttons'])}")
        print(f"  Sequences: {len(config['sequences'])}")
        print(f"  Serial: {config['serial']['port']} @ {config['serial']['baud_rate']} baud")
        
        return config


def convert_docklight_config(input_file: str, output_file: str = "project.yml"):
    """
    Convert a Docklight .ptp config file to unified config format.
    
    Args:
        input_file: Path to Docklight .ptp file
        output_file: Path to save unified config (default: project.yml)
    """
    interpreter = DocklightConfigInterpreter()
    return interpreter.convert_file(Path(input_file), Path(output_file))


if __name__ == "__main__":
    # Convert the file
    config = convert_docklight_config("docklight_config.ptp", "project.yml")
    
    # Print summary
    print("\nGenerated config:")
    print(yaml.dump(config, default_flow_style=False, sort_keys=False))