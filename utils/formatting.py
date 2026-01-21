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
        # Control character map
        ctrl_chars = {
            0x00: '<NUL>', 0x01: '<SOH>', 0x02: '<STX>', 0x03: '<ETX>',
            0x04: '<EOT>', 0x05: '<ENQ>', 0x06: '<ACK>', 0x07: '<BEL>',
            0x08: '<BS>',  0x09: '<TAB>', 0x0A: '<LF>',  0x0B: '<VT>',
            0x0C: '<FF>',  0x0D: '<CR>',  0x0E: '<SO>',  0x0F: '<SI>',
            0x10: '<DLE>', 0x11: '<DC1>', 0x12: '<DC2>', 0x13: '<DC3>',
            0x14: '<DC4>', 0x15: '<NAK>', 0x16: '<SYN>', 0x17: '<ETB>',
            0x18: '<CAN>', 0x19: '<EM>',  0x1A: '<SUB>', 0x1B: '<ESC>',
            0x1C: '<FS>',  0x1D: '<GS>',  0x1E: '<RS>',  0x1F: '<US>',
            0x7F: '<DEL>'
        }
        
        result = []
        for byte in message:
            if byte in ctrl_chars:
                result.append(ctrl_chars[byte])
            elif 32 <= byte < 127:
                result.append(chr(byte))
            else:
                result.append(f'\\x{byte:02x}')
        
        ascii_str = ''.join(result)
        
        # Handle newlines - split into multiple lines
        if '<LF>' in ascii_str or '<CR>' in ascii_str:
            lines = ascii_str.replace('<CR><LF>', '\n').replace('<LF>', '\n').replace('<CR>', '\n')
            formatted_lines = [f"[{timestamp}] {line}" if i == 0 else f"{'':>13} {line}" 
                             for i, line in enumerate(lines.split('\n'))]
            return '\n'.join(formatted_lines)
        
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