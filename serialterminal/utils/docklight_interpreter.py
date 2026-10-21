"""Import Docklight project files (.ptp) as a SerialTerminal config.

A .ptp is plain text (Windows ANSI, CRLF): blocks that start with a keyword line
(VERSION, COMMSETTINGS, SEND, RECEIVE, ...) and end with an empty line, one
value per line. The layout here follows the sample projects Docklight V2.4
itself saved, and the meaning of the options the Docklight V2.4 User Manual.

Docklight can express things SerialTerminal can't - wildcards that match zero
bytes, pauses, handshake signals, send parameters, some checksum layouts.
Those are never imported half-right: the sequence is left out and the reason
added to `problems`, which the app shows after the import. Each line in the
data is a HEX token or a doubled special character:

    ??  wildcard: exactly one byte          ##  wildcard: zero or one byte
    &&  pause / delay (next byte: x 10 ms)   !!  handshake signals / parity switch
    ^^  bitwise compare (mask, value)        ~~  any byte except the next one
    %%  break state
"""

import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

FUNCTION_TOKENS = {"&&", "!!", "^^", "~~", "%%"}
WILDCARD_TOKENS = {"??", "##"}
_HEX_BYTE = re.compile(r"^[0-9A-Fa-f]{2}$")

# Blocks whose value lines may be empty, so they can't be read up to the blank
# line that ends a block: CHANNELALIAS holds two (usually empty) aliases, and a
# sequence's index, name and data come first even when the name is empty.
_FIXED_LENGTH = {"CHANNELALIAS": 2}
_FIXED_PREFIX = {"SEND": 3, "RECEIVE": 3}

# COMMSETTINGS line 4: index into Docklight's alphabetical parity list. Checked
# against the manual: ModemDiagnostics ("No parity") stores 2, ModbusRtuCrc
# ("Even parity") stores 0.
_PARITY = {"0": "E", "1": "M", "2": "N", "3": "O", "4": "S"}
# Lines 6 and 7: only these codes are confirmed (8 data bits, 1 stop bit, in
# every sample whose settings the manual states). Other codes are reported.
_DATA_BITS = {"4": "8"}
_STOP_BITS = {"0": "1"}

# Docklight checksum algorithm -> (SerialTerminal checksum, bytes, byte order).
# Byte order: True = little endian (Docklight's "L"), None = single byte.
_GENERIC_CRC = {
    "CRC:16,8005,FFFF,0000,YES,YES": "CRC-MODBUS",
    "CRC:16,1021,FFFF,0000,NO,NO": "CRC-CCITT",
}
_CHECKSUMS = {
    "MOD256": ("sum8", 1, None),
    "XOR": ("xor8", 1, None),
    "LRC": ("lrc8", 1, None),
    "-MOD256": ("lrc8", 1, None),
    "CRC-MODBUS": ("crc16_modbus", 2, True),   # SerialTerminal: low byte first
    "CRC-CCITT": ("crc16_ccitt", 2, False),    # SerialTerminal: high byte first
}
_CHECKSUM_LINE = re.compile(
    r"^\s*(?:\(\s*(?P<start>-?\d+)\s*,\s*(?P<length>-?\d+)\s*\))?"
    r"\s*(?P<spec>\S+)(?P<flags>(?:\s+[AL])*)\s*(?:@\s*(?P<target>-?\d+))?\s*$")


def read_blocks(text: str) -> List[tuple]:
    """[(keyword, [value lines]), ...] in file order."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        keyword = lines[i].strip()
        i += 1
        if not keyword:
            continue
        if keyword in _FIXED_LENGTH:
            values = lines[i:i + _FIXED_LENGTH[keyword]]
            i += _FIXED_LENGTH[keyword]
        else:
            prefix = _FIXED_PREFIX.get(keyword, 0)
            values = lines[i:i + prefix]
            i += prefix
            while i < len(lines) and lines[i].strip():
                values.append(lines[i])
                i += 1
        blocks.append((keyword, [v.strip() for v in values]))
    return blocks


def parse_checksum(line: str):
    """A CHECKSUM line as (SerialTerminal checksum, size in bytes), or a str
    saying why it can't be represented. The Docklight form is
    `[(start, len)] spec [A] [L] [@ target] [# comment]`."""
    text = line[len("CHECKSUM"):].split("#", 1)[0]
    match = _CHECKSUM_LINE.match(text)
    if not match:
        return f"checksum '{text.strip()}' not understood"
    spec = match["spec"].upper()
    spec = _GENERIC_CRC.get(spec.replace(" ", ""), spec)
    flags = match["flags"].split()
    if spec not in _CHECKSUMS:
        return f"checksum {match['spec']} isn't available in SerialTerminal"
    name, size, little_endian = _CHECKSUMS[spec]
    if "A" in flags:
        return f"checksum {match['spec']} as ASCII text (A) isn't available in SerialTerminal"
    if little_endian is not None and ("L" in flags) != little_endian:
        order = "low byte first" if "L" in flags else "high byte first"
        return f"checksum {match['spec']} {order} isn't available in SerialTerminal"
    # SerialTerminal computes over everything before the checksum and appends
    # it: only Docklight's default area and position match that.
    if match["start"] is not None and (int(match["start"]), int(match["length"])) != (1, -(size + 1)):
        return f"checksum over bytes ({match['start']}, {match['length']}) only, not the whole frame"
    if match["target"] is not None and int(match["target"]) != -size:
        return f"checksum stored at position {match['target']}, not at the end"
    return name, size


def _clean_comment(comment: str, name: str, index: int) -> str:
    """Docklight comment macros, made readable as plain text."""
    comment = re.sub(r"%_[A-Z]\(\s*-?\d+\s*(?:,\s*-?\d+\s*)?\)", "[VALUE]", comment)
    comment = comment.replace("%_N", name).replace("%_I", str(index))
    comment = re.sub(r"%_[AHDB]", "[VALUE]", comment)
    comment = comment.replace("%_L", " ")
    comment = re.sub(r"%_[STCX]", "", comment)
    return " ".join(comment.split())


class DocklightConfigInterpreter:
    """Interpreter for Docklight .ptp format to unified config.

    After parse_file(), `problems` lists everything that was left out or
    changed, one sentence each, for the user to see.
    """

    def __init__(self):
        self.buttons: List[dict] = []
        self.sequences: List[dict] = []
        self.serial_config: dict = {}
        self.problems: List[str] = []
        # Docklight send index -> imported button, or None if it was left out.
        self._sends: Dict[int, dict | None] = {}

    def parse_file(self, filepath: Path) -> Dict[str, Any]:
        """Parse Docklight config file and return unified config dict.

        Raises ValueError for a file that isn't a Docklight project at all
        (missing or non-numeric fields), so nothing is imported half-built.
        """
        raw = Path(filepath).read_bytes()
        # Docklight is a Windows program and writes .ptp files in the ANSI
        # code page, not UTF-8. UTF-8 first (a file re-saved by a modern
        # editor), then cp1252, which can't fail.
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")

        blocks = read_blocks(text)
        channels = next((values for keyword, values in blocks if keyword == "COMMCHANNELS"), None)
        for keyword, values in blocks:
            if keyword == "COMMSETTINGS":
                self._parse_comm_settings(values, channels)
        # Sends first: a receive's answer refers to a send by its index.
        for keyword, values in blocks:
            if keyword == "SEND":
                self._parse_send(values)
        for keyword, values in blocks:
            if keyword == "RECEIVE":
                self._parse_receive(values)

        config = {'buttons': self.buttons, 'sequences': self.sequences}
        if self.serial_config:
            config = {'serial': self.serial_config, **config}
        return config

    # ------------------------------------------------------------------
    # COMMSETTINGS
    # ------------------------------------------------------------------

    def _parse_comm_settings(self, values: List[str], channels: List[str] | None):
        if len(values) < 4:
            raise ValueError("COMMSETTINGS is incomplete")
        get = lambda i: values[i] if i < len(values) else ""

        if get(0) == "1":
            self.problems.append("The project is in Docklight's Monitoring mode (two ports); "
                                 "SerialTerminal uses channel 1 only.")
        port = channels[0] if channels else get(1)
        if port.isdigit():
            port = f"COM{port}"  # VERSION 7 files store the COM number alone
        if not port.upper().startswith("COM"):
            if port:
                self.problems.append(f"Port {port} isn't a COM port; pick one in the serial bar.")
            port = "none"

        try:
            baud = int(get(3))
        except ValueError:
            self.problems.append(f"Baud rate '{get(3)}' isn't a number; using 9600.")
            baud = 9600

        def setting(code, table, label, default):
            if code in table:
                return table[code]
            self.problems.append(f"Unknown Docklight {label} code '{code}'; using {default} - "
                                 f"check it in the serial bar.")
            return default

        self.serial_config = {
            'port': port,
            'baud_rate': baud,
            'parity': setting(get(4), _PARITY, "parity", "N"),
            'data_bits': setting(get(6), _DATA_BITS, "data bits", "8"),
            'stop_bits': setting(get(7), _STOP_BITS, "stop bits", "1"),
        }

    # ------------------------------------------------------------------
    # SEND -> button
    # ------------------------------------------------------------------

    def _parse_send(self, values: List[str]):
        """index, name, data, repeat on (0/1), repeat seconds, [CHECKSUM ...]"""
        if len(values) < 3:
            raise ValueError("SEND is incomplete")
        index, label, data = int(values[0]), values[1], values[2]
        title = label or f"Send {index}"
        tokens = data.split()
        self._sends[index] = None

        special = sorted({t for t in tokens if t in FUNCTION_TOKENS | WILDCARD_TOKENS})
        if special:
            why = ("asks for parameters when sent (" + " ".join(special) + ")"
                   if set(special) <= WILDCARD_TOKENS
                   else "uses Docklight function characters (" + " ".join(special) + ")")
            self.problems.append(f"Button '{title}' not imported: it {why}, "
                                 f"which SerialTerminal buttons don't support.")
            return
        bad = [t for t in tokens if not _HEX_BYTE.match(t)]
        if bad:
            self.problems.append(f"Button '{title}' not imported: '{bad[0]}' isn't a byte.")
            return

        button = {
            'id': f"docklight-send-{index}",
            'label': title,
            'message': data,
            'format': 'hex',
            'tooltip': f"Send {title}",
        }

        checksum_line = next((v for v in values[5:] if v.startswith("CHECKSUM")), None)
        if checksum_line:
            parsed = parse_checksum(checksum_line)
            if isinstance(parsed, str):
                self.problems.append(f"Button '{title}' not imported: {parsed}.")
                return
            name, size = parsed
            if len(tokens) <= size:
                self.problems.append(f"Button '{title}' not imported: no room for its checksum.")
                return
            # Docklight writes the checksum over placeholder bytes at the end;
            # SerialTerminal appends it, so the placeholders go.
            button['message'] = " ".join(tokens[:-size])
            button['checksum'] = name

        repeat_on = len(values) > 3 and values[3] == "1"
        try:
            seconds = float(values[4]) if len(values) > 4 else 0.0
        except ValueError:
            seconds = 0.0
        button['repeat'] = int(seconds * 1000) if repeat_on and seconds > 0 else 0

        self.buttons.append(button)
        self._sends[index] = button

    # ------------------------------------------------------------------
    # RECEIVE -> sequence
    # ------------------------------------------------------------------

    def _parse_receive(self, values: List[str]):
        """index, name, data, answer (send index or -1), comment on, COMMENT
        text, option flags, [CHECKSUM spec, checksum mode]"""
        if len(values) < 4:
            raise ValueError("RECEIVE is incomplete")
        index, name, data = int(values[0]), values[1], values[2]
        answer = int(values[3])
        title = name or f"Receive {index}"
        tokens = data.split()

        functions = sorted({t for t in tokens if t in FUNCTION_TOKENS})
        if functions:
            self.problems.append(
                f"Sequence '{title}' not imported: it uses Docklight function characters "
                f"({' '.join(functions)}) - pauses, handshake signals or bit masks - "
                f"that SerialTerminal can't match.")
            return
        # '#' matches zero or one byte. At either end of a pattern it changes
        # nothing (the manual says so for the end; a match is searched for
        # anywhere in the stream, so the start is the same). Inside, it allows
        # variable lengths that '??' (exactly one byte) can't express.
        while tokens and tokens[-1] == "##":
            tokens.pop()
        while tokens and tokens[0] == "##":
            tokens.pop(0)
        if "##" in tokens:
            self.problems.append(f"Sequence '{title}' not imported: it has optional bytes (##) "
                                 f"inside the pattern, which SerialTerminal can't match.")
            return
        bad = [t for t in tokens if t != "??" and not _HEX_BYTE.match(t)]
        if bad or not tokens:
            self.problems.append(f"Sequence '{title}' not imported: "
                                 + (f"'{bad[0]}' isn't a byte." if bad else "its pattern is empty."))
            return

        checksum_line = next((v for v in values[6:] if v.startswith("CHECKSUM")), None)
        if checksum_line:
            parsed = parse_checksum(checksum_line)
            size = parsed[1] if not isinstance(parsed, str) else None
            if size is None or len(tokens) < size:
                self.problems.append(f"Sequence '{title}' not imported: its checksum can't be "
                                     f"matched ({parsed if isinstance(parsed, str) else 'too short'}).")
                return
            # The pattern holds placeholder bytes where Docklight checks the
            # checksum. SerialTerminal doesn't validate received checksums, so
            # match any value there instead of the placeholder.
            tokens[-size:] = ["??"] * size
            self.problems.append(f"Sequence '{title}': the received checksum isn't checked "
                                 f"(SerialTerminal accepts any value).")

        comment_line = next((v for v in values[5:] if v.startswith("COMMENT")), "")
        comment_on = len(values) > 4 and values[4] == "1"
        comment = _clean_comment(comment_line[len("COMMENT"):], title, index) if comment_on else ""

        sequence = {
            'name': title,
            'active': True,
            'delay': 0,
            'receive': {'data': " ".join(tokens), 'format': 'hex'},
            'comment': comment or title,
            'send': {'data': '', 'format': 'hex'},
        }
        if answer >= 0:
            button = self._sends.get(answer)
            if button is None:
                self.problems.append(f"Sequence '{title}' imported without its answer: "
                                     f"send sequence {answer} wasn't imported.")
            else:
                sequence['send'] = {'data': button['message'], 'format': 'hex'}
                if button.get('checksum'):
                    sequence['send']['checksum'] = button['checksum']
        self.sequences.append(sequence)

    # ------------------------------------------------------------------

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
        for problem in self.problems:
            print(f"  ! {problem}")

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
