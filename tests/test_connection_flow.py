"""Connecting, staying connected, and framing what arrives.

Auto-connect on send, disconnect when the port or line settings change, the
frame-gap setting, recovery when the device disappears, and framing bytes that
arrive in USB bursts.
"""

import logging
import threading
import time

import pytest
import serial
from textual.widgets import Input, Select

from serialterminal.serial_comm.connection import SerialConnection
from serialterminal.serial_comm.receiver import SerialReceiver
from tests.conftest import MINIMAL_CONFIG
from tests.fakes import FakeSerialConnection


class FakePort(FakeSerialConnection):
    """A port that starts closed and opens on connect(), like SerialConnection."""

    def __init__(self, fail: Exception | None = None):
        super().__init__()
        self.connected = False
        self.fail = fail
        self.opened = []
        self.lost_reason = None

    def connect(self, port, baud_rate=9600, **settings):
        if self.fail is not None:
            raise self.fail
        self.opened.append((port, baud_rate))
        self.connected = True
        self.lost_reason = None
        return True

    def disconnect(self):
        self.connected = False


def install(app, port: FakePort) -> FakePort:
    """Use `port` for both sending and the receive thread."""
    app.serial_conn = port
    app.receiver.connection = port
    return port


def offer_ports(app, *names):
    select = app.query_one("#serial-port-select", Select)
    select.set_options([("No port", "none")] + [(n, n) for n in names])
    return select


def tab_text(app):
    return "\n".join(app.query_one("#tab-ascii LogPanel").lines)


async def connected_app(write_config, make_app, pilot_size=(120, 40)):
    write_config(MINIMAL_CONFIG)
    return make_app()


# ----------------------------------------------------------------------------
# Auto-connect
# ----------------------------------------------------------------------------

class TestAutoConnect:
    async def test_button_press_connects_then_sends(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.opened == [("COM_FAKE", 9600)]
            assert port.written == [b"PING"]
            assert "Connected" in str(app.query_one("#serial-status").render())
            app.receiver.stop()

    async def test_quick_send_connects_then_sends(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            box = app.query_one("#quick-send-input", Input)
            box.focus()
            box.value = "HELLO"
            await pilot.press("enter")
            await pilot.pause()
            assert port.written == [b"HELLO"]
            assert box.value == ""
            app.receiver.stop()

    async def test_no_port_selected_says_so_and_keeps_the_text(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            box = app.query_one("#quick-send-input", Input)
            box.value = "HELLO"
            app._quick_send()
            await pilot.pause()
            assert port.written == [] and box.value == "HELLO"
            assert "No serial port selected" in tab_text(app)
            assert "Not connected - nothing sent" in tab_text(app)

    async def test_failed_connect_reports_and_sends_nothing(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort(fail=serial.SerialException(
                "could not open port 'COM_FAKE': PermissionError(13, 'Access is denied.')")))
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.written == []
            assert "Error: couldn't open COM_FAKE" in tab_text(app)
            assert "PermissionError" not in tab_text(app), "short by default"
            assert "Not connected - nothing sent" in tab_text(app)

    async def test_already_connected_does_not_reopen(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            await pilot.click("#btn-ping")
            await pilot.pause(0.3)
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert len(port.opened) == 1 and port.written == [b"PING", b"PING"]
            app.receiver.stop()


# ----------------------------------------------------------------------------
# Changing the port or line settings while connected
# ----------------------------------------------------------------------------

class TestSettingsChangeWhileConnected:
    async def connect(self, app, pilot, port_name="COM_A"):
        port = install(app, FakePort())
        offer_ports(app, "COM_A", "COM_B").value = port_name
        assert app._connect_serial()
        await pilot.pause()
        return port

    async def test_switching_port_disconnects_from_the_old_one(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = await self.connect(app, pilot)
            app.query_one("#serial-port-select", Select).value = "COM_B"
            await pilot.pause()
            assert not port.connected
            assert "Disconnected from COM_A: port changed to COM_B" in tab_text(app)
            assert "Disconnected" in str(app.query_one("#serial-status").render())

    async def test_next_send_connects_to_the_new_port(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = await self.connect(app, pilot)
            app.query_one("#serial-port-select", Select).value = "COM_B"
            await pilot.pause()
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.opened[-1] == ("COM_B", 9600) and port.connected
            app.receiver.stop()

    @pytest.mark.parametrize("widget_id,value", [
        ("#serial-baud", "19200"), ("#serial-parity", "E"),
        ("#serial-bits", "7"), ("#serial-stop-bits", "2"),
    ])
    async def test_changing_line_settings_disconnects(self, write_config, make_app, widget_id, value):
        """The open port keeps the settings it was opened with, so carrying on
        would show one baud rate while talking at another."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = await self.connect(app, pilot)
            app.query_one(widget_id, Select).value = value
            await pilot.pause()
            assert not port.connected
            assert "line settings changed" in tab_text(app)

    async def test_reselecting_the_same_values_keeps_the_connection(self, write_config, make_app):
        """Restoring settings and Refresh set values programmatically; only a
        real difference from the open port may disconnect."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = await self.connect(app, pilot)
            app.query_one("#serial-baud", Select).value = "19200"
            app.query_one("#serial-baud", Select).value = "9600"  # back before the event lands
            app.query_one("#serial-port-select", Select).value = "COM_A"
            await pilot.pause()
            assert port.connected
            app.receiver.stop()

    async def test_changing_the_gap_applies_without_reconnecting(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = await self.connect(app, pilot)
            app.set_frame_gap("100")  # what Settings (F2) calls
            await pilot.pause()
            assert port.connected
            assert app.receiver.message_timeout == pytest.approx(0.1)
            app.receiver.stop()


class TestFrameGapSetting:
    async def test_auto_uses_the_floor_at_normal_baud_rates(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            install(app, FakePort())
            offer_ports(app, "COM_A").value = "COM_A"
            app._connect_serial()
            assert app.receiver.message_timeout == pytest.approx(SerialReceiver.MIN_TIMEOUT)
            app.receiver.stop()

    async def test_saved_and_restored(self, write_config, make_app, isolated_cwd):
        import yaml

        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.set_frame_gap("200")
            await pilot.pause()
        assert yaml.safe_load((isolated_cwd / "project.yml").read_text())["serial"]["frame_gap"] == 200
        reopened = make_app()
        async with reopened.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert reopened.frame_gap() == "200"


# ----------------------------------------------------------------------------
# The device going away
# ----------------------------------------------------------------------------

class DeadHandle:
    """A pyserial handle for a port that has been unplugged."""

    port = "COM_GONE"
    is_open = True

    def __init__(self):
        self.closed = False

    @property
    def in_waiting(self):
        raise serial.SerialException(
            "ClearCommError failed (PermissionError(13, 'Access is denied.', None, 5))")

    def write(self, data):
        raise serial.SerialException("WriteFile failed (PermissionError(13, 'Access is denied.'))")

    def close(self):
        self.closed = True
        self.is_open = False


def dead_connection() -> SerialConnection:
    connection = SerialConnection()
    connection.connection = DeadHandle()
    connection.connected = True
    return connection


class TestPortLoss:
    def test_regression_read_failure_ends_the_connection_once(self, caplog):
        """REGRESSION: every read retried and logged a full traceback, ~1000 a
        second, while the app still showed Connected."""
        connection = dead_connection()
        handle = connection.connection
        with caplog.at_level(logging.DEBUG, logger="serialterminal.connection"):
            for _ in range(50):
                assert connection.read() == b""
        assert not connection.connected
        assert handle.closed
        assert "ClearCommError" in connection.lost_reason
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1
        assert not any(r.exc_info for r in caplog.records), "no traceback for a lost port"

    def test_write_failure_also_ends_the_connection(self):
        connection = dead_connection()
        assert connection.write(b"X") == 0
        assert not connection.connected and connection.lost_reason

    def test_write_timeout_is_not_a_lost_port(self):
        class SlowHandle(DeadHandle):
            def write(self, data):
                raise serial.SerialTimeoutException("Write timeout")

        connection = SerialConnection()
        connection.connection = SlowHandle()
        connection.connected = True
        assert connection.write(b"X") == 0
        assert connection.connected

    def test_receiver_reports_the_loss_once(self):
        connection = dead_connection()
        lost = []
        done = threading.Event()

        def on_lost(reason):
            lost.append(reason)
            done.set()

        receiver = SerialReceiver(connection, lambda frame: None, on_lost=on_lost)
        receiver.start()
        assert done.wait(2)
        receiver.stop()
        assert len(lost) == 1 and "ClearCommError" in lost[0]

    def test_requested_stop_is_not_a_loss(self):
        connection = FakeSerialConnection()
        lost = []
        receiver = SerialReceiver(connection, lambda frame: None, on_lost=lost.append)
        receiver.start()
        time.sleep(0.05)
        receiver.stop()
        assert lost == []

    async def test_app_shows_the_loss_and_resets(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            assert app._connect_serial()
            poll = app.query_one("#btn-poll")
            app._start_repeating_button(poll.id, poll, "AA", "hex", 500)
            # The device disappears.
            port.lost_reason = "ClearCommError failed (Access is denied)"
            port.connected = False
            for _ in range(40):
                await pilot.pause(0.05)
                if "lost" in tab_text(app):
                    break
            assert "Error: connection to COM_FAKE lost" in tab_text(app)
            assert "Disconnected" in str(app.query_one("#serial-status").render())
            assert not app.query_one("#serial-connect").disabled
            assert app.repeating_buttons == {}, "repeats stop with the port"

            port.connected = False  # a send reconnects
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.connected and port.written[-1] == b"PING"
            app.receiver.stop()


# ----------------------------------------------------------------------------
# Framing bytes that arrive in bursts
# ----------------------------------------------------------------------------

class TimedPort(FakeSerialConnection):
    """Delivers each chunk only once its time has come, like a USB adapter."""

    def __init__(self, schedule):
        super().__init__()
        self.start = time.monotonic()
        self.schedule = list(schedule)

    def read(self, size=1024):
        now = time.monotonic() - self.start
        ready = b""
        while self.schedule and self.schedule[0][0] <= now:
            ready += self.schedule.pop(0)[1]
        return ready


def collect_frames(receiver, wait=0.4):
    frames = []
    receiver.on_frame = frames.append
    receiver.start()
    time.sleep(wait)
    receiver.stop()
    return frames


class TestBurstFraming:
    # One 30-byte message, delivered the way an FTDI adapter does: in pieces,
    # flushed every 16 ms.
    BURSTS = [(0.000, b"STATUS=OK "), (0.016, b"T1=23.4 T2="), (0.032, b"19.8\r\n")]

    def test_regression_usb_bursts_are_one_message(self):
        """REGRESSION: with a 5 ms gap, checked before reading, the message was
        logged as three."""
        receiver = SerialReceiver(TimedPort(self.BURSTS), None, baud_rate=9600)
        frames = collect_frames(receiver)
        assert frames == [b"STATUS=OK T1=23.4 T2=19.8\r\n"]

    def test_a_too_small_gap_would_split_it(self):
        """The same data with the old 5 ms gap - shows the test can tell."""
        receiver = SerialReceiver(TimedPort(self.BURSTS), None, message_timeout=0.005)
        # Split at least once. How many pieces depends on how coarse the OS
        # sleep is (Windows on Python 3.10/3.11 merges two of the three).
        assert len(collect_frames(receiver)) >= 2

    def test_separate_messages_stay_separate(self):
        receiver = SerialReceiver(
            TimedPort([(0.0, b"ONE\r\n"), (0.150, b"TWO\r\n")]), None, baud_rate=9600)
        assert collect_frames(receiver, wait=0.5) == [b"ONE\r\n", b"TWO\r\n"]


# ----------------------------------------------------------------------------
# File dialogs on Windows with an unreadable drive
# ----------------------------------------------------------------------------

class TestDriveListing:
    def test_regression_unreadable_drive_no_longer_breaks_dialogs(self, monkeypatch):
        """REGRESSION: on Python 3.10/3.11 the library listed drives with
        Path.exists(), which raises WinError 1117 for some drives - every file
        dialog then failed to open and took the app down."""
        import os

        from serialterminal.ui.widgets import file_pickers
        from textual_fspicker.parts import drive_navigation

        def raising_listdrives():
            raise OSError(22, "The request could not be performed because of an I/O device error")

        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.delattr(os, "listdrives", raising=False)
        monkeypatch.setattr(drive_navigation, "listdrives", raising_listdrives)
        file_pickers._patch_drive_listing()
        assert drive_navigation.listdrives is file_pickers._listdrives_safely
        assert isinstance(drive_navigation.listdrives(), list)

    def test_left_alone_where_os_listdrives_exists(self, monkeypatch):
        import os

        from serialterminal.ui.widgets import file_pickers
        from textual_fspicker.parts import drive_navigation

        sentinel = object()
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(os, "listdrives", lambda: ["C:"], raising=False)
        monkeypatch.setattr(drive_navigation, "listdrives", sentinel)
        file_pickers._patch_drive_listing()
        assert drive_navigation.listdrives is sentinel


# ----------------------------------------------------------------------------
# Never stuck on Connected
# ----------------------------------------------------------------------------

class DyingPort(FakePort):
    """Delivers a frame now and then, then fails like an unplugged adapter."""

    def __init__(self, die_after: float):
        super().__init__()
        self.die_after = die_after
        self.opened_at = None

    def connect(self, port, baud_rate=9600, **settings):
        super().connect(port, baud_rate, **settings)
        self.opened_at = time.monotonic()
        return True

    last_frame = 0.0

    def read(self, size=1024):
        if not self.connected:
            return b""
        now = time.monotonic()
        if now - self.opened_at > self.die_after:
            self.lost_reason = "ClearCommError failed (PermissionError(13, 'Access is denied.'))"
            self.connected = False
            return b""
        if now - self.last_frame >= 0.06:  # a reply every 60 ms, like a polled device
            self.last_frame = now
            return b"DATA\r\n"
        return b""


async def wait_for(pilot, condition, timeout=3.0):
    start = time.monotonic()
    while not condition():
        if time.monotonic() - start > timeout:
            return None
        await pilot.pause(0.02)
    return time.monotonic() - start


class TestNeverStuckConnected:
    async def test_regression_port_loss_does_not_freeze(self, write_config, make_app):
        """REGRESSION (from a real log): after 'port lost', the UI waited for the
        receive thread while the receive thread waited for the UI. A 2 s join
        timeout broke it - 'receiver thread did not stop gracefully' - with
        Connected shown the whole time."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, DyingPort(die_after=0.3))
            offer_ports(app, "COM16").value = "COM16"
            assert app._connect_serial()
            status = app.query_one("#serial-status")
            took = await wait_for(pilot, lambda: "Disconnected" in str(status.render()))
            assert took is not None, "stuck on Connected"
            assert took < 1.5, f"took {took:.2f}s - the 2 s deadlock is back"
            assert app.receiver.thread is None or not app.receiver.thread.is_alive()
            assert "Error: connection to COM16 lost" in tab_text(app)

    async def test_disconnect_while_data_flows_is_immediate(self, write_config, make_app):
        """Pressing Disconnect mid-stream hit the same deadlock."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            install(app, DyingPort(die_after=60))
            offer_ports(app, "COM16").value = "COM16"
            assert app._connect_serial()
            await pilot.pause(0.2)  # frames arriving continuously
            start = time.monotonic()
            app._disconnect_serial()
            assert time.monotonic() - start < 0.5
            assert app.receiver.thread is None

    async def test_reconnect_after_a_loss_starts_a_new_receive_thread(self, write_config, make_app):
        """The receiver left `running` set after a loss, so the next connect
        started no thread: Connected, but nothing received and no loss seen."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, DyingPort(die_after=0.2))
            offer_ports(app, "COM16").value = "COM16"
            assert app._connect_serial()
            status = app.query_one("#serial-status")
            assert await wait_for(pilot, lambda: "Disconnected" in str(status.render()))
            port.die_after = 60
            assert app._connect_serial()
            await pilot.pause(0.2)
            assert app.receiver.thread is not None and app.receiver.thread.is_alive()
            assert "DATA" in tab_text(app)
            app._disconnect_serial()

    async def test_watchdog_catches_a_loss_nobody_reported(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = install(app, FakePort())
            offer_ports(app, "COM16").value = "COM16"
            assert app._connect_serial()
            app.receiver.stop()  # no receive thread to notice anything
            port.lost_reason = "gone"
            port.connected = False
            status = app.query_one("#serial-status")
            assert await wait_for(pilot, lambda: "Disconnected" in str(status.render()), 2.0)

    def test_receiver_is_restartable_after_a_loss(self):
        connection = dead_connection()
        done = threading.Event()
        receiver = SerialReceiver(connection, lambda f: None, on_lost=lambda r: done.set())
        receiver.start()
        assert done.wait(2)
        receiver.thread.join(1)
        assert receiver.running is False
        connection.connection, connection.connected = None, True  # "reconnected"
        receiver.start()
        assert receiver.thread.is_alive()
        receiver.stop()


class TestContinuousStream:
    """A device that never pauses must still be shown, in bounded pieces."""

    class Firehose(FakeSerialConnection):
        def read(self, size=1024):
            return b"x" * 64  # data on every poll, no gaps at all

    def test_shown_in_pieces_without_waiting_for_a_gap(self):
        frames = []
        first = threading.Event()

        def on_frame(frame):
            frames.append(frame)
            first.set()

        receiver = SerialReceiver(self.Firehose(), on_frame, baud_rate=115200)
        start = time.monotonic()
        receiver.start()
        assert first.wait(2), "nothing shown while the stream never paused"
        assert time.monotonic() - start < SerialReceiver.MAX_FRAME_SECONDS + 0.5
        receiver.stop()
        assert all(len(f) < SerialReceiver.MAX_FRAME_BYTES + 64 for f in frames)


class TestPortListRescansWhenOpened:
    async def test_opening_the_list_finds_a_newly_plugged_adapter(self, write_config, make_app,
                                                                   monkeypatch):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            ports = [("COM_OLD", "COM_OLD", "old")]
            monkeypatch.setattr(SerialConnection, "list_ports", staticmethod(lambda: list(ports)))
            app.refresh_serial_ports()
            select = offer_ports(app, "COM_OLD")
            select.value = "COM_OLD"
            ports.append(("COM_NEW", "COM_NEW", "plugged in after launch"))
            await pilot.click("#serial-port-select")
            await pilot.pause()
            assert select.expanded, "the list stays open"
            assert "COM_NEW" in [value for _, value in select._options]
            assert select.value == "COM_OLD", "the selection survives the rescan"

    async def test_rescan_while_connected_keeps_the_connection(self, write_config, make_app,
                                                               monkeypatch):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(SerialConnection, "list_ports",
                                staticmethod(lambda: [("COM_FAKE", "COM_FAKE", "fake")]))
            port = install(app, FakePort())
            offer_ports(app, "COM_FAKE").value = "COM_FAKE"
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.connected
            await pilot.click("#serial-port-select")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert port.connected and app.serial_conn.connected
