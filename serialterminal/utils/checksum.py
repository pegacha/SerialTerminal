"""Checksums that can be appended to an outgoing frame.

Each algorithm returns the raw bytes to append, in the byte order its
specification puts on the wire. Parameters follow the CRC catalogue names, so
the check value for b"123456789" can be looked up and tested.
"""


def _sum8(data: bytes) -> bytes:
    return bytes([sum(data) & 0xFF])


def _xor8(data: bytes) -> bytes:
    value = 0
    for byte in data:
        value ^= byte
    return bytes([value])


def _lrc8(data: bytes) -> bytes:
    # Two's complement of the 8-bit sum, so sum(data + lrc) & 0xFF == 0.
    return bytes([(-sum(data)) & 0xFF])


def _crc16_modbus(data: bytes) -> bytes:
    # Reflected poly 0x8005 (0xA001), init 0xFFFF; low byte goes first.
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def _crc16_ccitt(data: bytes) -> bytes:
    # CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, unreflected; high byte first.
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc.to_bytes(2, "big")


# key -> (label shown in the UI, function)
CHECKSUMS = {
    "none": ("None", lambda data: b""),
    "sum8": ("SUM-8", _sum8),
    "xor8": ("XOR-8", _xor8),
    "lrc8": ("LRC-8", _lrc8),
    "crc16_modbus": ("CRC-16/MODBUS", _crc16_modbus),
    "crc16_ccitt": ("CRC-16/CCITT", _crc16_ccitt),
}


def checksum_bytes(data: bytes, kind: str = "none") -> bytes:
    """The bytes `kind` appends to `data`. Raises ValueError for an unknown kind."""
    try:
        _, func = CHECKSUMS[kind or "none"]
    except KeyError:
        raise ValueError(
            f"unknown checksum {kind!r} (expected one of {', '.join(CHECKSUMS)})"
        ) from None
    return func(data)
