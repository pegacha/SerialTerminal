from datetime import datetime

def format_log_message(message) -> str:
    """Add timestamp to a log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if isinstance(message, bytes):
        return f"[{timestamp}] {message.hex()}"
    return f"[{timestamp}] {message}"

def format_log_message_ascii(message) -> str:
    """Format log message as ASCII text with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if isinstance(message, bytes):
        # Try to decode as ASCII, replace non-printable with hex notation
        ascii_str = ''.join(chr(b) if 32 <= b < 127 else f'\\x{b:02x}' for b in message)
        return f"[{timestamp}] {ascii_str}"
    
    return f"[{timestamp}] {message}"

def format_log_message_hex(message) -> str:
    """Format log message as space-separated hex bytes with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if isinstance(message, bytes):
        hex_str = " ".join(f"{byte:02X}" for byte in message)
        return f"[{timestamp}] {hex_str}"
    
    return f"[{timestamp}] {message}"

def format_log_message_decimal(message) -> str:
    """Format log message as space-separated decimal bytes with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if isinstance(message, bytes):
        dec_str = " ".join(str(byte) for byte in message)
        return f"[{timestamp}] {dec_str}"
    
    return f"[{timestamp}] {message}"

def format_log_message_binary(message) -> str:
    """Format log message as space-separated 8-bit binary bytes with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if isinstance(message, bytes):
        bin_str = " ".join(f"{byte:08b}" for byte in message)
        return f"[{timestamp}] {bin_str}"
    
    return f"[{timestamp}] {message}"

def format_frame(frame_bytes: bytes) -> str:
    """Format frame bytes for display - no longer needed, kept for compatibility."""
    return frame_bytes.hex()