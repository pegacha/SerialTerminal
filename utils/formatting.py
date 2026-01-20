from datetime import datetime


def format_log_message(message: str) -> str:
    """Add timestamp to a log message."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    return f"[{timestamp}] {message}"


def _extract_bytes_from_string(data: str) -> bytes:
    """
    Extract actual bytes from string representation.
    Handles: b'data', b"data", or plain data
    """
    # Check if it's a bytes representation like b'...' or b"..."
    if (data.startswith("b'") and data.endswith("'")) or \
       (data.startswith('b"') and data.endswith('"')):
        # Remove b' or b" prefix and trailing quote
        inner = data[2:-1]
        
        # Handle escape sequences
        # Replace common escape sequences
        inner = inner.replace('\\r', '\r')
        inner = inner.replace('\\n', '\n')
        inner = inner.replace('\\t', '\t')
        inner = inner.replace("\\'", "'")
        inner = inner.replace('\\"', '"')
        inner = inner.replace('\\\\', '\\')
        
        # Convert to bytes using latin-1 to preserve byte values
        try:
            return inner.encode('latin-1')
        except:
            return inner.encode('utf-8', errors='replace')
    else:
        # Plain string, encode normally
        return data.encode('utf-8', errors='replace')


def format_log_message_ascii(message: str) -> str:
    """Format log message as ASCII text with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # For ASCII, just display the message as-is
    # The b'...' representation is fine for ASCII view
    return f"[{timestamp}] {message}"


def format_log_message_hex(message: str) -> str:
    """Format log message as space-separated hex bytes with timestamp.
    Keeps [TX]/[RX] labels as ASCII, converts only the data portion."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # Extract the label prefix (like [TX] or [RX]) if present
    prefix = ''
    data = message
    
    if message.startswith('[TX] '):
        prefix = '[TX] '
        data = message[5:]  # Remove '[TX] '
    elif message.startswith('[RX] '):
        prefix = '[RX] '
        data = message[5:]  # Remove '[RX] '
    elif message.startswith('[Error] '):
        prefix = '[Error] '
        data = message[8:]  # Remove '[Error] '
    
    # Convert data to hex
    try:
        byte_data = _extract_bytes_from_string(data)
        hex_str = " ".join(f"{byte:02X}" for byte in byte_data)
    except Exception as e:
        # Fallback: just return the data as-is
        hex_str = data
    
    return f"[{timestamp}] {prefix}{hex_str}"


def format_log_message_decimal(message: str) -> str:
    """Format log message as space-separated decimal bytes with timestamp.
    Keeps [TX]/[RX] labels as ASCII, converts only the data portion."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # Extract the label prefix (like [TX] or [RX]) if present
    prefix = ''
    data = message
    
    if message.startswith('[TX] '):
        prefix = '[TX] '
        data = message[5:]
    elif message.startswith('[RX] '):
        prefix = '[RX] '
        data = message[5:]
    elif message.startswith('[Error] '):
        prefix = '[Error] '
        data = message[8:]
    
    # Convert data to decimal
    try:
        byte_data = _extract_bytes_from_string(data)
        dec_str = " ".join(str(byte) for byte in byte_data)
    except Exception as e:
        # Fallback: just return the data as-is
        dec_str = data
    
    return f"[{timestamp}] {prefix}{dec_str}"


def format_log_message_binary(message: str) -> str:
    """Format log message as space-separated 8-bit binary bytes with timestamp.
    Keeps [TX]/[RX] labels as ASCII, converts only the data portion."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    # Extract the label prefix (like [TX] or [RX]) if present
    prefix = ''
    data = message
    
    if message.startswith('[TX] '):
        prefix = '[TX] '
        data = message[5:]
    elif message.startswith('[RX] '):
        prefix = '[RX] '
        data = message[5:]
    elif message.startswith('[Error] '):
        prefix = '[Error] '
        data = message[8:]
    
    # Convert data to binary
    try:
        byte_data = _extract_bytes_from_string(data)
        bin_str = " ".join(f"{byte:08b}" for byte in byte_data)
    except Exception as e:
        # Fallback: just return the data as-is
        bin_str = data
    
    return f"[{timestamp}] {prefix}{bin_str}"


def format_frame(frame_bytes: bytes) -> str:
    """Format frame bytes for display as string representation."""
    # Return as string representation (e.g., b'HELLO')
    # This will be properly parsed by the formatting functions
    return str(frame_bytes)