import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional
from serialterminal.serial_comm.connection import SerialConnection

log = logging.getLogger("serialterminal.receiver")


class SerialReceiver:
    """Serial data receiver with automatic baud-rate-dependent message buffering."""

    # Character transmission time calculation constants
    BITS_PER_BYTE = 10  # 1 start + 8 data + 1 stop bit (typical)
    SAFETY_MULTIPLIER = 3  # Wait for 3 character times of silence
    # Floor for the automatic gap. USB-serial adapters deliver bytes in bursts,
    # not as they arrive on the wire: an FTDI chip flushes every 16 ms by
    # default. With the old 5 ms floor a message the device sent in one go was
    # cut at each burst and logged as several messages.
    MIN_TIMEOUT = 0.030
    MAX_TIMEOUT = 0.200  # 200ms maximum (for very low baud rates)
    # A frame ends at a gap, but a device that sends without ever pausing would
    # otherwise build one message forever - nothing shown, memory growing, and
    # a multi-megabyte entry to render when it finally stopped. Show what has
    # arrived once it reaches either limit.
    MAX_FRAME_BYTES = 4096
    MAX_FRAME_SECONDS = 0.5

    def __init__(
        self,
        connection: SerialConnection,
        on_frame: Callable[[bytes], None],
        baud_rate: Optional[int] = None,
        message_timeout: Optional[float] = None,
        on_lost: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the serial receiver.

        Args:
            connection: SerialConnection instance
            on_frame: Callback function for complete messages
            baud_rate: Baud rate for automatic timeout calculation (optional)
            message_timeout: Manual timeout override in seconds (optional)
                           If not provided, calculates from baud_rate
        """
        self.connection = connection
        self.on_frame = on_frame
        # Called (from the receive thread) with the reason when the port fails
        # under us - unplugged, device reset - rather than on a requested stop.
        self.on_lost = on_lost
        self.baud_rate = baud_rate
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.buffer = bytearray()
        self.last_receive_time = 0.0
        self.frame_started = 0.0
        # Wall-clock time of the first byte of the frame being built. The
        # frame is only dispatched after the gap, so on_frame reads this to
        # stamp it with when it began arriving, not when it was shown.
        self.frame_started_at: datetime | None = None

        # Calculate or set timeout
        if message_timeout is not None:
            self.message_timeout = message_timeout
            self.auto_timeout = False
        elif baud_rate is not None:
            self.message_timeout = self._calculate_timeout(baud_rate)
            self.auto_timeout = True
        else:
            # Default fallback
            self.message_timeout = 0.05
            self.auto_timeout = False

    def _calculate_timeout(self, baud_rate: int) -> float:
        """
        Calculate optimal timeout based on baud rate.

        Timeout = time for 3 characters to transmit
        This allows for small gaps in transmission while detecting message boundaries.

        Args:
            baud_rate: Baud rate in bits per second

        Returns:
            Timeout in seconds
        """
        # Time to transmit one character (in seconds)
        char_time = self.BITS_PER_BYTE / baud_rate

        # Wait for 3 character times of silence
        timeout = char_time * self.SAFETY_MULTIPLIER

        # Clamp to reasonable bounds
        timeout = max(self.MIN_TIMEOUT, min(self.MAX_TIMEOUT, timeout))

        log.debug(
            "timeout for %d baud: char=%.2fms -> %.2fms (%dx)",
            baud_rate, char_time * 1000, timeout * 1000, self.SAFETY_MULTIPLIER,
        )
        return timeout

    def set_baud_rate(self, baud_rate: int):
        """
        Update baud rate and recalculate the message-framing timeout.

        Providing an explicit baud rate always re-frames RX by that rate
        (and re-enables auto framing), so the caller's UI-selected baud is
        honoured instead of the fixed default.

        Args:
            baud_rate: New baud rate
        """
        self.baud_rate = baud_rate
        old_timeout = self.message_timeout
        self.message_timeout = self._calculate_timeout(baud_rate)
        self.auto_timeout = True
        log.debug("timeout updated: %.1fms -> %.1fms",
                  old_timeout * 1000, self.message_timeout * 1000)

    def set_timeout(self, timeout: float, auto: bool = False):
        """
        Change the message timeout manually.

        Args:
            timeout: New timeout in seconds
            auto: If True, will recalculate on baud rate changes
        """
        self.message_timeout = timeout
        self.auto_timeout = auto
        log.debug("timeout set to %.1fms (auto=%s)", timeout * 1000, auto)

    def start(self):
        """Start the receiver thread."""
        if not self.running:
            log.debug("starting with %.1fms timeout", self.message_timeout * 1000)
            self.running = True
            self.buffer.clear()
            self.last_receive_time = 0.0
            self.thread = threading.Thread(
                target=self._receive_loop,
                daemon=True,
                name="SerialReceiver"
            )
            self.thread.start()

    def stop(self) -> bytes:
        """Stop the receiver thread and return any unframed tail bytes.

        The tail is *returned* rather than pushed through on_frame. stop() is
        called from the UI thread (disconnect, unmount) and on_frame marshals
        back onto it, so dispatching here either raises - call_from_thread
        refuses to run on the app's own thread - or deadlocks against the
        join() below. Previously it raised, the exception was swallowed, and
        the last frame received before a disconnect vanished with no trace.
        Callers log the returned bytes themselves, already on the UI thread.

        Returns:
            Buffered bytes not yet dispatched as a frame, or b'' if none.
        """
        log.debug("stopping")
        self.running = False

        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                # Thread still touching self.buffer; leave it alone.
                log.warning("receiver thread did not stop gracefully")
                return b''
            self.thread = None

        # The thread is dead, so the buffer is ours to drain safely.
        tail = bytes(self.buffer)
        if tail:
            log.debug("returning %d unframed tail bytes: %r", len(tail), tail)
        self.buffer.clear()
        self.last_receive_time = 0.0
        return tail

    def _send_buffered_message(self):
        """Send the buffered message via callback and clear buffer."""
        if self.buffer:
            message = bytes(self.buffer)
            log.debug("dispatching buffered message (%d bytes): %r", len(message), message)
            try:
                self.on_frame(message)
            except Exception as e:
                log.exception("error in on_frame callback: %s", e)

            self.buffer.clear()
            self.last_receive_time = 0.0

    def _receive_loop(self):
        """Main receive loop with message buffering."""
        log.debug("receive loop started")

        try:
            while self.running:
                # Check connection status
                if not self.connection.connected:
                    log.debug("connection lost, exiting loop")
                    break

                # Read BEFORE deciding a message has ended. The old order checked
                # the gap first, so bytes that arrived while the loop slept (up
                # to ~16 ms per sleep on some Windows Pythons) counted as silence
                # and the message was cut before they were read.
                try:
                    data = self.connection.read()
                except Exception as e:
                    log.exception("error reading data: %s", e)
                    time.sleep(0.01)
                    continue

                now = time.monotonic()  # wall-clock jumps must not cut frames
                if data:
                    if not self.buffer:
                        self.frame_started = now
                        self.frame_started_at = datetime.now()
                    self.buffer.extend(data)
                    self.last_receive_time = now
                    if (len(self.buffer) >= self.MAX_FRAME_BYTES
                            or now - self.frame_started >= self.MAX_FRAME_SECONDS):
                        self._send_buffered_message()
                    continue  # drain whatever else is already waiting

                if self.buffer and now - self.last_receive_time >= self.message_timeout:
                    self._send_buffered_message()
                time.sleep(0.001)

        except Exception as e:
            log.exception("fatal error in receive loop: %s", e)

        lost = self.running and not self.connection.connected
        # The thread is ending either way. Left True after a loss, the next
        # start() thought a thread was already running and started none.
        self.running = False
        if lost:
            # The port failed under us rather than being closed on request: show
            # what had arrived, then say why the connection ended.
            if self.buffer:
                self._send_buffered_message()
            reason = getattr(self.connection, "lost_reason", None) or "connection lost"
            log.debug("receive loop ended: %s", reason)
            if self.on_lost is not None:
                try:
                    self.on_lost(reason)
                except Exception as e:
                    log.exception("error in on_lost callback: %s", e)
            return

        log.debug("receive loop ended")
