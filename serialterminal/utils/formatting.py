from datetime import datetime

# Names for the control characters, as the ASCII log tab shows them. The
# button editor's ASCII mode reads and writes the same names, so what you see
# in the log is what you can type.
CONTROL_NAMES = {
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


# Settings (F2) > Timestamps: settings.yml value -> what the option shows.
TIME_FORMATS = {
    "milliseconds": "12:34:56.789",
    "seconds": "12:34:56",
    "date": "2026-10-13 12:34:56.789",
    "delta": "+0.016 (since previous line)",
    "off": "Off",
}


def timestamp(now: datetime = None, milliseconds: bool = True) -> str:
    """`now` (default: current time) as HH:MM:SS.mmm - or HH:MM:SS - the stamp
    on every log line."""
    stamp = (now or datetime.now()).strftime("%H:%M:%S.%f")
    return stamp[:-3] if milliseconds else stamp[:8]


def format_stamp(when: datetime, time_format: str, previous: datetime | None = None) -> str:
    """The stamp for a line at `when` in one of TIME_FORMATS; '' for off.

    "delta" is the time since `previous` (the line before), in seconds; it is
    negative when a received frame - stamped at its first byte - began before
    the line shown just above it.
    """
    if time_format == "off":
        return ""
    if time_format == "seconds":
        return timestamp(when, milliseconds=False)
    if time_format == "date":
        return when.strftime("%Y-%m-%d ") + timestamp(when)
    if time_format == "delta":
        seconds = 0.0 if previous is None else (when - previous).total_seconds()
        return f"{seconds:+.3f}"
    return timestamp(when)


def _head(stamp: str) -> str:
    """What goes before a line's text: "[stamp] ", or nothing with timestamps off."""
    return f"[{stamp}] " if stamp else ""


def format_log_message(message, stamp: str = None) -> str:
    """Add timestamp to a log message."""
    stamp = stamp if stamp is not None else timestamp()
    
    if isinstance(message, bytes):
        return f"{_head(stamp)}{message.hex()}"
    return f"{_head(stamp)}{message}"

def format_log_message_ascii(message, stamp: str = None) -> str:
    """Format log message as ASCII text with timestamp."""
    stamp = stamp if stamp is not None else timestamp()
    
    if isinstance(message, bytes):
        ctrl_chars = CONTROL_NAMES

        # Line terminators stay visible - whether the device sent CR, LF or
        # CRLF is exactly what you need to see when line endings are the bug -
        # and a new line starts after each one. A terminator that ends the
        # frame starts nothing: it used to leave an empty line under every
        # CRLF-terminated frame, so text protocols filled half the log with
        # blanks. Decided per byte, not by searching the rendered text, so a
        # device that literally sends the characters "<CR>" isn't split.
        lines, current = [], []
        i, n = 0, len(message)
        while i < n:
            byte = message[i]
            if byte == 0x0D and i + 1 < n and message[i + 1] == 0x0A:
                current.append('<CR><LF>')
                lines.append(''.join(current))
                current = []
                i += 2
                continue
            if byte in (0x0A, 0x0D):
                current.append(ctrl_chars[byte])
                lines.append(''.join(current))
                current = []
            elif byte in ctrl_chars:
                current.append(ctrl_chars[byte])
            elif 32 <= byte < 127:
                current.append(chr(byte))
            else:
                current.append(f'\\x{byte:02x}')
            i += 1
        if current or not lines:
            lines.append(''.join(current))

        head = _head(stamp)
        indent = " " * len(head)  # continuation lines line up with the data
        return "\n".join(head + line if k == 0 else indent + line
                         for k, line in enumerate(lines))

    return f"{_head(stamp)}{message}"

def format_log_message_hex(message, stamp: str = None) -> str:
    """Format log message as space-separated hex bytes with timestamp."""
    stamp = stamp if stamp is not None else timestamp()
    
    if isinstance(message, bytes):
        hex_str = " ".join(f"{byte:02X}" for byte in message)
        return f"{_head(stamp)}{hex_str}"
    
    return f"{_head(stamp)}{message}"

def format_log_message_decimal(message, stamp: str = None) -> str:
    """Format log message as space-separated decimal bytes with timestamp."""
    stamp = stamp if stamp is not None else timestamp()
    
    if isinstance(message, bytes):
        dec_str = " ".join(str(byte) for byte in message)
        return f"{_head(stamp)}{dec_str}"
    
    return f"{_head(stamp)}{message}"

def format_log_message_binary(message, stamp: str = None) -> str:
    """Format log message as space-separated 8-bit binary bytes with timestamp."""
    stamp = stamp if stamp is not None else timestamp()
    
    if isinstance(message, bytes):
        bin_str = " ".join(f"{byte:08b}" for byte in message)
        return f"{_head(stamp)}{bin_str}"
    
    return f"{_head(stamp)}{message}"
