"""Timestamp formats (Settings > Timestamps) and stamping RX at its first byte."""

import re
import threading
import time
from datetime import datetime, timedelta

import pytest

from serialterminal.serial_comm.receiver import SerialReceiver
from serialterminal.ui.app import SerialData
from serialterminal.utils.formatting import TIME_FORMATS, format_stamp
from tests.conftest import MINIMAL_CONFIG
from tests.fakes import FakeSerialConnection

T0 = datetime(2026, 10, 13, 9, 5, 7, 123456)


class TestFormats:
    def test_every_format(self):
        assert format_stamp(T0, "milliseconds") == "09:05:07.123"
        assert format_stamp(T0, "seconds") == "09:05:07"
        assert format_stamp(T0, "date") == "2026-10-13 09:05:07.123"
        assert format_stamp(T0, "off") == ""

    def test_delta(self):
        assert format_stamp(T0, "delta") == "+0.000", "the first line"
        assert format_stamp(T0 + timedelta(milliseconds=16), "delta", T0) == "+0.016"
        assert format_stamp(T0 + timedelta(seconds=75.5), "delta", T0) == "+75.500"
        # A frame stamped at its first byte can start before the line above it.
        assert format_stamp(T0, "delta", T0 + timedelta(milliseconds=12)) == "-0.012"

    def test_every_format_is_offered(self):
        assert set(TIME_FORMATS) == {"milliseconds", "seconds", "date", "delta", "off"}


def ascii_lines(app):
    return app.query_one("#tab-ascii LogPanel").lines


async def with_format(make_app, write_config, isolated_cwd, time_format):
    import yaml
    write_config(MINIMAL_CONFIG)
    (isolated_cwd / "settings.yml").write_text(yaml.dump({"time_format": time_format}))
    return make_app()


class TestInTheLog:
    async def test_date(self, write_config, make_app, isolated_cwd):
        app = await with_format(make_app, write_config, isolated_cwd, "date")
        async with app.run_test(size=(120, 40)) as pilot:
            app.log_message(b"PING", "tx", when=T0)
            await pilot.pause()
            assert ascii_lines(app)[-1] == "[2026-10-13 09:05:07.123] [TX] PING"

    async def test_delta_since_previous_line_and_clear_restarts_it(self, write_config,
                                                                    make_app, isolated_cwd):
        app = await with_format(make_app, write_config, isolated_cwd, "delta")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_clearlog_message()
            app.log_message(b"PING", "tx", when=T0)
            app.log_message(b"PONG", "rx", when=T0 + timedelta(milliseconds=250))
            await pilot.pause()
            assert ascii_lines(app)[-2:] == ["[+0.000] [TX] PING", "[+0.250] [RX] PONG"]
            app.action_clearlog_message()
            app.log_message("again", "info", when=T0 + timedelta(seconds=9))
            await pilot.pause()
            assert ascii_lines(app)[-1] == "[+0.000] again"

    async def test_off(self, write_config, make_app, isolated_cwd):
        app = await with_format(make_app, write_config, isolated_cwd, "off")
        async with app.run_test(size=(120, 40)) as pilot:
            app.log_message(b"PING\r\nPONG", "rx")
            app.log_message("ENQ received", "seq_comment")
            await pilot.pause()
            assert ascii_lines(app)[-3:] == ["[RX] PING<CR><LF>", "     PONG",
                                             "[Sequence] ENQ received"]

    async def test_filter_still_searches_the_tag_when_off(self, write_config, make_app,
                                                          isolated_cwd):
        """With no stamp, the filter's "skip the leading [..]" used to drop the
        [RX] tag itself."""
        app = await with_format(make_app, write_config, isolated_cwd, "off")
        async with app.run_test(size=(120, 40)) as pilot:
            app.log_message(b"PING", "tx")
            app.log_message(b"PONG", "rx")
            await pilot.pause()
            panel = app.query_one("#tab-ascii LogPanel")
            panel.set_filter("[rx]")
            assert panel.match_count == 1

    @pytest.mark.parametrize("time_format", ["date", "delta", "seconds"])
    async def test_filter_never_matches_the_stamp(self, write_config, make_app, isolated_cwd,
                                                  time_format):
        app = await with_format(make_app, write_config, isolated_cwd, time_format)
        async with app.run_test(size=(120, 40)) as pilot:
            app.log_message(b"PING", "tx", when=T0)
            await pilot.pause()
            panel = app.query_one("#tab-hex LogPanel")
            panel.set_filter("09")  # in every stamp; not in 50 49 4E 47
            assert panel.match_count == 0


class TestReceivedFramesAreStampedAtTheirFirstByte:
    def test_receiver_records_when_the_frame_began(self):
        """The frame is dispatched only after the gap, so the dispatch time is
        late by at least the gap; the recorded start is not."""
        port = FakeSerialConnection([b"PI", None, b"NG"])
        seen = []
        receiver = None

        def on_frame(data):
            seen.append((data, receiver.frame_started_at, datetime.now()))

        receiver = SerialReceiver(port, on_frame, message_timeout=0.1)
        before = datetime.now()
        receiver.start()
        deadline = time.monotonic() + 2
        while not seen and time.monotonic() < deadline:
            time.sleep(0.01)
        receiver.stop()
        [(data, started, dispatched)] = seen
        assert data == b"PING"
        assert before <= started < dispatched
        assert (dispatched - started).total_seconds() >= 0.09, "dispatch waited out the gap"

    async def test_rx_line_and_recording_use_the_first_byte_time(self, write_config, make_app,
                                                                 isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            recording = isolated_cwd / "session.log"
            app.capture.start(recording)
            app.on_serial_data(SerialData(b"PONG", started=T0))
            await pilot.pause()
            app.capture.stop()
            assert ascii_lines(app)[-1] == "[09:05:07.123] [RX] PONG"
            assert "2026-10-13 09:05:07.123 RX" in recording.read_text(encoding="utf-8")

    async def test_frame_from_the_receive_thread_carries_its_start(self, write_config,
                                                                   make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.receiver.frame_started_at = T0
            thread = threading.Thread(target=app._on_frame_received_threadsafe,
                                      args=(b"PONG",))
            thread.start()
            thread.join()
            await pilot.pause()
            assert re.search(r"\[09:05:07\.123\] \[RX\] PONG$", ascii_lines(app)[-1])
