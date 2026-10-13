"""Up / Down in the Send Command box recall earlier commands, like a shell."""

import yaml
from textual.widgets import Input, Select

from serialterminal.ui.widgets.quick_send import MAX_HISTORY, QuickSend, clean_history
from tests.conftest import MINIMAL_CONFIG
from tests.test_connection_flow import FakePort, install, offer_ports


async def ready(app, pilot):
    await pilot.pause()
    install(app, FakePort())
    offer_ports(app, "COM_FAKE").value = "COM_FAKE"
    await pilot.click("#quick-send-input")


async def send(pilot, app, text, fmt="ascii"):
    app.query_one("#send-format-select", Select).value = fmt
    box = app.query_one("#quick-send-input", Input)
    box.value = text
    await pilot.press("enter")
    await pilot.pause()
    assert box.value == "", f"{text!r} was not sent"


def box(app):
    return app.query_one("#quick-send-input", Input)


def shown(app):
    return box(app).value, app.query_one("#send-format-select", Select).value


class TestRecall:
    async def test_up_steps_back_and_down_returns_to_the_draft(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            await send(pilot, app, "PING")
            await send(pilot, app, "01 03", "hex")
            app.query_one("#send-format-select", Select).value = "ascii"
            box(app).value = "half-typed"
            await pilot.press("up")
            assert shown(app) == ("01 03", "hex"), "the format comes back too"
            await pilot.press("up")
            assert shown(app) == ("PING", "ascii")
            await pilot.press("up")
            assert shown(app) == ("PING", "ascii"), "stops at the oldest"
            await pilot.press("down")
            assert shown(app) == ("01 03", "hex")
            await pilot.press("down")
            assert shown(app) == ("half-typed", "ascii"), "back to what was being typed"
            await pilot.press("down")
            assert shown(app) == ("half-typed", "ascii")

    async def test_recalled_command_sends_again(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            await send(pilot, app, "PING")
            await pilot.press("up", "enter")
            await pilot.pause()
            assert app.serial_conn.written[-2:] == [b"PING", b"PING"]
            assert box(app).cursor_position == 0 and box(app).value == ""

    async def test_cursor_goes_to_the_end(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            await send(pilot, app, "PING")
            await pilot.press("up")
            assert box(app).cursor_position == len("PING")

    async def test_no_history_does_nothing(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            box(app).value = "typed"
            await pilot.press("up", "down")
            assert box(app).value == "typed"

    async def test_failed_sends_are_not_remembered(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            app.query_one("#send-format-select", Select).value = "hex"
            box(app).value = "GG"  # not hex: refused
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one(QuickSend).history == []

    async def test_repeats_are_stored_once(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            await send(pilot, app, "PING")
            await send(pilot, app, "PING")
            assert len(app.query_one(QuickSend).history) == 1


class TestPersistence:
    async def test_history_survives_a_restart(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await ready(app, pilot)
            await send(pilot, app, "01 03", "hex")
        saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
        assert saved["send_history"] == [{"text": "01 03", "format": "hex"}]

        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#quick-send-input")
            await pilot.press("up")
            assert shown(app) == ("01 03", "hex")

    def test_malformed_entries_are_dropped(self):
        raw = [{"text": "ok", "format": "hex"}, {"text": 5, "format": "hex"},
               {"text": "x", "format": "morse"}, "loose", None]
        assert clean_history(raw) == [{"text": "ok", "format": "hex"}]
        assert clean_history("not a list") == []

    def test_capped(self):
        raw = [{"text": str(i), "format": "ascii"} for i in range(MAX_HISTORY + 5)]
        assert len(clean_history(raw)) == MAX_HISTORY
        quick = QuickSend(history=clean_history(raw))
        quick.remember("new", "ascii")
        assert len(quick.history) == MAX_HISTORY and quick.history[-1]["text"] == "new"
