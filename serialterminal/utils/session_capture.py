"""Recording a session's traffic to a text file.

Distinct from serialterminal.log, which holds the app's own diagnostics: this
is the exchange itself, one line per log entry, written as it happens.
"""

from datetime import datetime
from pathlib import Path

_LABELS = {
    'tx': 'TX',
    'rx': 'RX',
    'error': 'ERR',
    'seq_comment': 'SEQ',
}


def _printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def format_capture_line(when: datetime, type: str, message) -> str:
    """One capture line: date-time, direction, then hex and printable ASCII."""
    stamp = when.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    label = _LABELS.get(type, 'INFO')
    if isinstance(message, (bytes, bytearray)):
        hex_str = " ".join(f"{b:02X}" for b in message)
        return f"{stamp} {label:<4} {hex_str}  |{_printable(message)}|"
    # One entry per line, so the file stays greppable and line-oriented tools
    # (tail -f, sort, diff) see whole entries: escape embedded line breaks.
    text = str(message).replace("\r", "\\r").replace("\n", "\\n")
    return f"{stamp} {label:<4} {text}"


class SessionCapture:
    """Appends log entries to a file until stopped.

    Opened in append mode so pointing it at an existing capture never destroys
    it, and line-buffered so `tail -f` sees each entry immediately and a crash
    loses nothing already shown on screen.
    """

    def __init__(self):
        self._file = None
        self.path: Path | None = None

    @property
    def active(self) -> bool:
        return self._file is not None

    def start(self, path) -> None:
        """Begin recording to `path`. Raises OSError if it can't be opened."""
        self.stop()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a", encoding="utf-8", buffering=1)
        try:
            handle.write(f"# capture started {datetime.now().isoformat(timespec='seconds')}\n")
        except OSError:
            # Don't leave a half-open capture that claims to be recording.
            handle.close()
            raise
        self._file = handle
        self.path = path

    def write(self, when: datetime, type: str, message) -> None:
        """Record one entry. Raises OSError if the write fails."""
        if self._file is not None:
            self._file.write(format_capture_line(when, type, message) + "\n")

    def stop(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            handle.write(f"# capture stopped {datetime.now().isoformat(timespec='seconds')}\n")
        except OSError:
            pass  # e.g. the drive went away; still release the handle below
        finally:
            try:
                handle.close()
            except OSError:
                pass
