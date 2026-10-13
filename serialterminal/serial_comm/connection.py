import logging
import serial
import serial.tools.list_ports
from typing import Optional

log = logging.getLogger("serialterminal.connection")


class SerialConnection:
    """Wrapper for serial port connection."""

    def __init__(self):
        self.connection: Optional[serial.Serial] = None
        self.connected = False
        # Why the port failed under us (unplugged, device reset), or None. Set
        # rather than raised so the receive thread can stop cleanly and the
        # app can report it once.
        self.lost_reason: Optional[str] = None
        # The most recent read/write failure, for an error message that says why.
        self.last_error: Optional[str] = None

    @staticmethod
    def list_ports():
        """List available serial ports."""
        ports = serial.tools.list_ports.comports()
        return [(port.device, port.name, port.description) for port in ports]

    def connect(self, port: str, baud_rate: int = 9600,
                bytesize=None, parity=None, stopbits=None):
        """
        Connect to a serial port with the given line settings.

        Line settings (bytesize/parity/stopbits) are applied atomically when the
        port is opened - pyserial opens on construction, so mutating them after
        the fact is unreliable. Any omitted setting defaults to 8N1.

        Raises the underlying serial.SerialException on failure so the caller
        can surface the real reason (port busy, access denied, missing, ...).
        Never leaves a stale/partial handle behind on error.
        """
        # Reset state up front so a failed attempt can't look connected.
        self.connected = False
        self.connection = None
        self.lost_reason = None

        # CRITICAL: timeout must be small (non-blocking) for receiver to work
        self.connection = serial.Serial(
            port=port,
            baudrate=baud_rate,
            timeout=0.1,  # 100ms timeout - don't block forever!
            write_timeout=1.0,
            bytesize=bytesize if bytesize is not None else serial.EIGHTBITS,
            parity=parity if parity is not None else serial.PARITY_NONE,
            stopbits=stopbits if stopbits is not None else serial.STOPBITS_ONE,
        )

        self.connected = True
        log.debug("connected to %s @ %s baud (%s)", port, baud_rate, self.connection)
        return True

    def disconnect(self):
        """Disconnect from serial port."""
        if self.connection and self.connection.is_open:
            log.debug("disconnecting from %s", self.connection.port)
            self.connection.close()
        self.connected = False
        self.connection = None

    def read(self, size: int = 1024) -> bytes:
        """
        Read available data from serial port.

        THIS IS THE CRITICAL METHOD FOR RX!

        Args:
            size: Maximum number of bytes to read

        Returns:
            Bytes read from serial port, or empty bytes if nothing available
        """
        handle = self.connection
        if not self.connected or handle is None:
            return b''

        try:
            # Check how many bytes are waiting
            waiting = handle.in_waiting

            if waiting > 0:
                # Read all available bytes (up to 'size')
                data = handle.read(min(waiting, size))
                log.debug("read %d bytes: %r", len(data), data)
                return data

            # No data available
            return b''

        except (serial.SerialException, OSError) as e:
            # The device is gone: "ClearCommError failed ... Access is denied"
            # on Windows, EIO or "device reports readiness to read but returned
            # no data" on Linux. No retry can succeed. This used to log a full
            # traceback and retry ~1000 times a second, flooding the log, while
            # the app still showed Connected.
            self._lose(e)
            return b''

    def write(self, data: bytes) -> int:
        """Write data to serial port."""
        handle = self.connection
        if not self.connected or handle is None:
            log.warning("write called while not connected")
            return 0

        try:
            written = handle.write(data)
            handle.flush()  # Ensure data is sent immediately
            log.debug("wrote %d bytes: %r", written, data)
            return written

        except serial.SerialTimeoutException as e:
            # The port is fine but not draining (flow control, device busy).
            log.error("write timed out: %s", e)
            self.last_error = f"write timed out ({e})"
            return 0
        except (serial.SerialException, OSError) as e:
            self._lose(e)
            return 0

    def _lose(self, error: Exception):
        """The port failed under us: stop using it, close it, remember why."""
        if self.lost_reason is None:
            self.lost_reason = str(error) or type(error).__name__
            log.error("port lost: %s", self.lost_reason)
        self.last_error = self.lost_reason
        self.connected = False
        handle, self.connection = self.connection, None
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass

    def flush_input(self):
        """Flush input buffer."""
        if self.connected and self.connection:
            self.connection.reset_input_buffer()
            log.debug("input buffer flushed")

    def flush_output(self):
        """Flush output buffer."""
        if self.connected and self.connection:
            self.connection.reset_output_buffer()
            log.debug("output buffer flushed")
