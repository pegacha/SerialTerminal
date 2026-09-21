"""SerialReceiver framing, lifecycle and baud-derived timeout."""

import threading
import time

import pytest

from serial_comm.receiver import SerialReceiver
from tests.fakes import FakeSerialConnection


class FrameCollector:
    """Thread-safe sink for frames dispatched by the receive thread."""

    def __init__(self):
        self.frames = []
        self._event = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, frame: bytes):
        with self._lock:
            self.frames.append(frame)
        self._event.set()

    def wait_for(self, count: int, timeout: float = 2.0) -> bool:
        """Block until `count` frames have arrived, or give up."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.frames) >= count:
                    return True
            self._event.wait(0.01)
            self._event.clear()
        with self._lock:
            return len(self.frames) >= count


@pytest.fixture
def collector():
    return FrameCollector()


class TestTimeoutCalculation:
    @pytest.mark.parametrize(
        "baud,expected_ms",
        [
            (9600, 3.125),     # 10 bits / 9600 * 3 = 3.125ms -> clamped up to 5
            (1200, 25.0),
            (300, 100.0),
            (110, 200.0),      # 272ms -> clamped down to 200
            (230400, 0.13),    # -> clamped up to 5
        ],
    )
    def test_timeout_is_three_character_times_within_bounds(self, baud, expected_ms):
        receiver = SerialReceiver(FakeSerialConnection(), lambda f: None, baud_rate=baud)
        raw = expected_ms / 1000.0
        clamped = max(SerialReceiver.MIN_TIMEOUT, min(SerialReceiver.MAX_TIMEOUT, raw))
        assert receiver.message_timeout == pytest.approx(clamped, rel=1e-3)

    def test_explicit_timeout_wins_over_baud(self):
        receiver = SerialReceiver(
            FakeSerialConnection(), lambda f: None, baud_rate=9600, message_timeout=0.5
        )
        assert receiver.message_timeout == 0.5
        assert receiver.auto_timeout is False

    def test_default_timeout_when_nothing_supplied(self):
        receiver = SerialReceiver(FakeSerialConnection(), lambda f: None)
        assert receiver.message_timeout == 0.05

    def test_set_baud_rate_re_enables_auto_framing(self):
        receiver = SerialReceiver(
            FakeSerialConnection(), lambda f: None, message_timeout=0.5
        )
        assert receiver.auto_timeout is False
        receiver.set_baud_rate(1200)
        assert receiver.auto_timeout is True
        assert receiver.message_timeout == pytest.approx(0.025, rel=1e-3)

    def test_set_timeout_manual_override(self):
        receiver = SerialReceiver(FakeSerialConnection(), lambda f: None)
        receiver.set_timeout(0.123)
        assert receiver.message_timeout == 0.123
        assert receiver.auto_timeout is False


class TestFraming:
    def test_bytes_arriving_together_form_one_frame(self, collector):
        conn = FakeSerialConnection([b"\x01\x02\x03"])
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        assert collector.wait_for(1)
        receiver.stop()
        assert collector.frames == [b"\x01\x02\x03"]

    def test_contiguous_chunks_coalesce_into_one_frame(self, collector):
        conn = FakeSerialConnection([b"\x01", b"\x02", b"\x03"])
        receiver = SerialReceiver(conn, collector, message_timeout=0.05)
        receiver.start()
        assert collector.wait_for(1)
        receiver.stop()
        assert collector.frames == [b"\x01\x02\x03"]

    def test_a_gap_splits_two_frames(self, collector):
        # None means "nothing available this poll"; enough of them exceed the
        # timeout and close the first frame.
        conn = FakeSerialConnection([b"\x01\x02"] + [None] * 60 + [b"\x03\x04"])
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        assert collector.wait_for(2), f"only got {collector.frames}"
        receiver.stop()
        assert collector.frames[:2] == [b"\x01\x02", b"\x03\x04"]

    def test_callback_exception_does_not_kill_the_loop(self, collector):
        calls = []

        def explode(frame):
            calls.append(frame)
            raise RuntimeError("callback blew up")

        conn = FakeSerialConnection([b"\x01"] + [None] * 60 + [b"\x02"])
        receiver = SerialReceiver(conn, explode, message_timeout=0.02)
        receiver.start()
        deadline = time.monotonic() + 2
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        receiver.stop()
        assert calls == [b"\x01", b"\x02"]


class TestLifecycle:
    def test_start_is_idempotent(self, collector):
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        first = receiver.thread
        receiver.start()
        assert receiver.thread is first
        receiver.stop()

    def test_stop_joins_the_thread(self, collector):
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        thread = receiver.thread
        receiver.stop()
        assert not thread.is_alive()
        assert receiver.thread is None

    def test_loop_exits_when_the_connection_drops(self, collector):
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        thread = receiver.thread
        conn.disconnect()
        thread.join(timeout=2)
        assert not thread.is_alive()
        receiver.stop()

    def test_regression_stop_returns_unframed_tail(self, collector):
        """REGRESSION: the tail was pushed through on_frame, which marshals to
        the UI thread - but stop() runs there, so it raised, got swallowed, and
        the last frame before a disconnect vanished."""
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=10)
        receiver.start()
        conn.feed(b"\xaa\xbb")
        deadline = time.monotonic() + 2
        while not receiver.buffer and time.monotonic() < deadline:
            time.sleep(0.01)
        tail = receiver.stop()
        assert tail == b"\xaa\xbb"
        assert collector.frames == [], "tail must be returned, not dispatched"

    def test_stop_returns_empty_when_nothing_buffered(self, collector):
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=0.02)
        receiver.start()
        assert receiver.stop() == b""

    def test_stop_without_start_is_safe(self, collector):
        receiver = SerialReceiver(FakeSerialConnection(), collector)
        assert receiver.stop() == b""

    def test_buffer_cleared_between_sessions(self, collector):
        conn = FakeSerialConnection()
        receiver = SerialReceiver(conn, collector, message_timeout=10)
        receiver.start()
        conn.feed(b"\xaa")
        deadline = time.monotonic() + 2
        while not receiver.buffer and time.monotonic() < deadline:
            time.sleep(0.01)
        receiver.stop()
        receiver.start()
        assert receiver.buffer == bytearray()
        receiver.stop()
