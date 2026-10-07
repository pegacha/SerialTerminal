"""Turning typed or configured text into the bytes that go on the wire.

One implementation shared by quick send, buttons and sequence responses, so
the three can't drift apart, and so the quick-send box can validate input as
it is typed with exactly the rules that will apply when it is sent.
"""

import re
import string

from serialterminal.utils.checksum import checksum_bytes
from serialterminal.utils.formatting import CONTROL_NAMES

FORMATS = ("ascii", "hex", "decimal", "binary")

# "<cr>" -> 0x0D etc., for the editor's ASCII mode (case-insensitive).
_TOKEN_BYTES = {name.lower(): byte for byte, name in CONTROL_NAMES.items()}
_TOKEN = re.compile(r"<[A-Za-z0-9]{2,3}>")

# key -> (label shown in the UI, bytes appended)
LINE_ENDINGS = {
    "none": ("No EOL", b""),
    "cr": ("CR", b"\r"),
    "lf": ("LF", b"\n"),
    "crlf": ("CRLF", b"\r\n"),
}


def parse_payload(text, fmt: str) -> bytes:
    """Convert `text` written in notation `fmt` to bytes.

    Raises ValueError with a message fit to show the user. Unknown formats are
    treated as ASCII, which is what the send paths always did.
    """
    text = "" if text is None else str(text)

    if fmt == "hex":
        digits = text.replace("0x", "").replace("0X", "")
        digits = "".join(digits.split())
        for ch in digits:
            if ch not in "0123456789abcdefABCDEF":
                raise ValueError(f"{ch!r} is not a hex digit")
        if len(digits) % 2:
            raise ValueError("odd number of hex digits")
        return bytes.fromhex(digits)

    if fmt == "decimal":
        values = []
        for token in text.split():
            if not (token.isascii() and token.isdigit()):
                raise ValueError(f"{token!r} is not a number")
            value = int(token)
            if value > 255:
                raise ValueError(f"{value} is out of range 0-255")
            values.append(value)
        return bytes(values)

    if fmt == "binary":
        bits = "".join(text.split())
        for ch in bits:
            if ch not in "01":
                raise ValueError(f"{ch!r} is not a binary digit")
        # A short final group is read as a smaller value, as before.
        return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))

    for ch in text:
        if ord(ch) > 127:
            raise ValueError(f"{ch!r} is not ASCII")
    return text.encode("ascii")


def line_ending_bytes(kind: str = "none") -> bytes:
    """The terminator for `kind`. Raises ValueError for an unknown kind."""
    try:
        return LINE_ENDINGS[kind or "none"][1]
    except KeyError:
        raise ValueError(
            f"unknown line ending {kind!r} (expected one of {', '.join(LINE_ENDINGS)})"
        ) from None


def build_frame(text, fmt: str, checksum: str = "none", line_ending: str = "none") -> bytes:
    """Payload, then its checksum, then the line ending.

    The checksum covers the payload only. The line ending is ASCII-only: a hex
    or binary frame is sent exactly as written, so a CRLF chosen for text never
    corrupts a binary frame.
    """
    data = parse_payload(text, fmt)
    data += checksum_bytes(data, checksum)
    eol = line_ending_bytes(line_ending)
    if fmt not in ("hex", "decimal", "binary"):
        data += eol
    return data


# ----------------------------------------------------------------------------
# The button editor's notation
# ----------------------------------------------------------------------------
#
# Like the config notation, except that in ASCII mode control characters are
# written as <CR>, <LF>, <STX>, ... - the names the log's ASCII tab shows -
# instead of being invisible. That makes every byte below 0x80 visible and
# typable in ASCII mode, so switching the edit mode between ASCII, HEX,
# Decimal and Binary converts the sequence without losing anything.

def parse_editor_text(text, fmt: str) -> bytes:
    """Bytes for `text` written in the editor's notation for `fmt`.

    Raises ValueError with a message fit to show the user.
    """
    text = "" if text is None else str(text)
    if fmt != "ascii":
        return parse_payload(text, fmt)

    out = bytearray()
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            match = _TOKEN.match(text, i)
            if match and match.group(0).lower() in _TOKEN_BYTES:
                out.append(_TOKEN_BYTES[match.group(0).lower()])
                i = match.end()
                continue
        if ch in "\r\n":
            raise ValueError("line breaks aren't sent - type <CR> or <LF>, "
                             "or pick one on the Line ending tab")
        if not (32 <= ord(ch) < 127):
            raise ValueError(f"{ch!r} isn't printable ASCII - switch to HEX to enter it")
        out.append(ord(ch))
        i += 1
    return bytes(out)


def format_editor_text(data: bytes, fmt: str) -> str:
    """`data` in the editor's notation for `fmt` - the inverse of parse_editor_text.

    Raises ValueError if ASCII mode can't show it (a byte above 0x7F).
    """
    if fmt == "hex":
        return " ".join(f"{b:02X}" for b in data)
    if fmt == "decimal":
        return " ".join(str(b) for b in data)
    if fmt == "binary":
        return " ".join(f"{b:08b}" for b in data)
    parts = []
    for b in data:
        if b in CONTROL_NAMES:
            parts.append(CONTROL_NAMES[b])
        elif 32 <= b < 127:
            parts.append(chr(b))
        else:
            raise ValueError(f"byte 0x{b:02X} has no ASCII form - keep it in HEX")
    return "".join(parts)


def config_message(data: bytes, fmt: str) -> str:
    """How `data` is stored as a button's `message` for `fmt`.

    Canonical spacing for the numeric notations. For ASCII the real characters,
    control characters included: YAML writes them as escapes ("PING\\r\\n") and
    parse_payload reads them back, so a button made in the editor sends
    exactly what the editor showed.
    """
    if fmt == "ascii":
        return data.decode("ascii")
    return format_editor_text(data, fmt)


def editor_byte_position(text: str, fmt: str, offset: int) -> int:
    """How many whole bytes come before character `offset` - the editor's "Pos.".

    Tolerant of text that doesn't parse yet; it counts what it can.
    """
    prefix = (text or "")[:max(0, offset)]
    if fmt == "hex":
        prefix = prefix.replace("0x", "").replace("0X", "")
        return sum(ch in string.hexdigits for ch in prefix) // 2
    if fmt == "binary":
        return sum(ch in "01" for ch in prefix) // 8
    if fmt == "decimal":
        tokens = prefix.split()
        if tokens and not prefix[-1].isspace():
            tokens = tokens[:-1]  # the number under the cursor isn't finished
        return len(tokens)
    count, i = 0, 0
    while i < len(prefix):
        match = _TOKEN.match(prefix, i)
        if prefix[i] == "<" and match and match.group(0).lower() in _TOKEN_BYTES:
            i = match.end()
        else:
            i += 1
        count += 1
    return count
