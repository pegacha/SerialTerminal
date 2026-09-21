"""Test doubles that stand in for hardware."""

import threading


class FakeSerialConnection:
    """A SerialConnection with a scripted read stream and no serial port.

    Mirrors the surface SerialReceiver actually uses: `connected`, `read()` and
    `write()`. Reads are served from a queue of chunks; a `None` chunk means
    "nothing available this poll", which is how a real port signals a gap
    between frames. Once the script runs out, read() keeps returning b'' so a
    receive loop can spin harmlessly until it is told to stop.
    """

    def __init__(self, chunks=None):
        self.connected = True
        self._chunks = list(chunks or [])
        self._lock = threading.Lock()
        self.written = []
        self.reads_after_script = 0

    def feed(self, *chunks):
        """Append more chunks to the read script."""
        with self._lock:
            self._chunks.extend(chunks)

    def read(self, size: int = 1024) -> bytes:
        with self._lock:
            if not self._chunks:
                self.reads_after_script += 1
                return b''
            chunk = self._chunks.pop(0)
        return b'' if chunk is None else chunk

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def disconnect(self):
        self.connected = False

    @property
    def script_exhausted(self) -> bool:
        with self._lock:
            return not self._chunks
