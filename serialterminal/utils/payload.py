"""Turning typed or configured text into the bytes that go on the wire.

One implementation shared by quick send, buttons and sequence responses, so
the three can't drift apart, and so the quick-send box can validate input as
it is typed with exactly the rules that will apply when it is sent.
"""

from serialterminal.utils.checksum import checksum_bytes

FORMATS = ("ascii", "hex", "decimal", "binary")

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
