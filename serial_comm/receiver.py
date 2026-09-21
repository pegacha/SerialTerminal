import logging
import threading
import time
from typing import Callable, Optional
from serial_comm.connection import SerialConnection

log = logging.getLogger("serialterminal.receiver")


class SerialReceiver:
    """Serial data receiver with automatic baud-rate-dependent message buffering."""

    # Character transmission time calculation constants
    BITS_PER_BYTE = 10  # 1 start + 8 data + 1 stop bit (typical)
    SAFETY_MULTIPLIER = 3  # Wait for 3 character times of silence
    MIN_TIMEOUT = 0.005  # 5ms minimum (for very high baud rates)
    MAX_TIMEOUT = 0.200  # 200ms maximum (for very low baud rates)

    def __init__(
        self,
        connection: SerialConnection,
        on_frame: Callable[[bytes], None],
        baud_rate: Optional[int] = None,
        message_timeout: Optional[float] = None
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
        self.baud_rate = baud_rate
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.buffer = bytearray()
        self.last_receive_time = 0.0

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

    def stop(self):
        """Stop the receiver thread."""
        log.debug("stopping")
        self.running = False

        # Flush any remaining buffered data
        if self.buffer:
            log.debug("flushing %d buffered bytes", len(self.buffer))
            self._send_buffered_message()

        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                log.warning("receiver thread did not stop gracefully")

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

                current_time = time.time()

                # Check if buffer has timed out
                if self.buffer and self.last_receive_time > 0:
                    time_since_last = current_time - self.last_receive_time
                    if time_since_last >= self.message_timeout:
                        # Timeout reached, send buffered message
                        self._send_buffered_message()

                # Read data from serial connection
                try:
                    data = self.connection.read()

                    if data:
                        # Add to buffer
                        self.buffer.extend(data)
                        self.last_receive_time = current_time
                    else:
                        # No data, sleep briefly to avoid busy-waiting
                        time.sleep(0.001)  # 1ms sleep

                except Exception as e:
                    log.exception("error reading data: %s", e)
                    time.sleep(0.01)

        except Exception as e:
            log.exception("fatal error in receive loop: %s", e)

        log.debug("receive loop ended")
