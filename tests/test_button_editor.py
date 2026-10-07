"""The button editor, auto-send buttons, and the editor's sequence notation."""

import inspect

import pytest
import yaml
from textual.pilot import Pilot
from textual.widgets import Button, Checkbox, Input, RadioButton, Select, TextArea

from serialterminal.sequence_handler import SequenceHandler, sequences_from_buttons
from serialterminal.ui.widgets.button_editor import ButtonEditor
from serialterminal.ui.widgets.dynamic_control_buttons import ControlButton
from serialterminal.utils.payload import (
    config_message, editor_byte_position, format_editor_text, parse_editor_text, parse_payload,
)
from tests.conftest import MINIMAL_CONFIG
from tests.fakes import FakeSerialConnection

MODES = ("ascii", "hex", "decimal", "binary")


# ----------------------------------------------------------------------------
# Editor notation
# ----------------------------------------------------------------------------

class TestEditorNotation:
    @pytest.mark.parametrize("data", [b"PING\r\n", b"\x02AB\x03", b"", b"\x00\x7f"])
    def test_every_mode_round_trips(self, data):
        for mode in MODES:
            assert parse_editor_text(format_editor_text(data, mode), mode) == data

    def test_ascii_shows_control_characters_by_name(self):
        assert format_editor_text(b"\x02OK\r\n", "ascii") == "<STX>OK<CR><LF>"

    def test_ascii_tokens_are_case_insensitive(self):
        assert parse_editor_text("a<cr><Lf>", "ascii") == b"a\r\n"

    def test_unknown_angle_text_is_literal(self):
        assert parse_editor_text("<b>", "ascii") == b"<b>"

    def test_ascii_refuses_line_breaks_with_a_hint(self):
        with pytest.raises(ValueError, match="<CR> or <LF>"):
            parse_editor_text("A\nB", "ascii")

    def test_ascii_refuses_non_ascii(self):
        with pytest.raises(ValueError, match="HEX"):
            parse_editor_text("café", "ascii")

    def test_ascii_cannot_show_high_bytes(self):
        with pytest.raises(ValueError, match="0xFF"):
            format_editor_text(b"\xff", "ascii")

    def test_numeric_modes_are_canonical(self):
        assert format_editor_text(b"\x01\x0a", "hex") == "01 0A"
        assert format_editor_text(b"\x01\x0a", "decimal") == "1 10"
        assert format_editor_text(b"\x01", "binary") == "00000001"

    def test_ascii_is_stored_as_real_characters(self):
        """parse_payload, which sends it, must read back what the editor stored."""
        stored = config_message(b"PING\r\n", "ascii")
        assert stored == "PING\r\n"
        assert parse_payload(stored, "ascii") == b"PING\r\n"

    @pytest.mark.parametrize(
        "text,mode,offset,expected",
        [("01 03 00", "hex", 0, 0), ("01 03 00", "hex", 3, 1), ("01 03 00", "hex", 8, 3),
         ("1 3 0", "decimal", 3, 1), ("1 30", "decimal", 3, 1),
         ("0000000111111111", "binary", 16, 2),
         ("A<CR>B", "ascii", 5, 2), ("A<CR>B", "ascii", 2, 2)],
    )
    def test_byte_position(self, text, mode, offset, expected):
        assert editor_byte_position(text, mode, offset) == expected


# ----------------------------------------------------------------------------
# Auto-send buttons become receive sequences
# ----------------------------------------------------------------------------

ACK_BUTTON = {
    "id": "ack", "label": "ACK", "message": "06", "format": "hex",
    "auto_send": {"receive": {"data": "05", "format": "hex"}, "delay": 0},
}


class TestSequencesFromButtons:
    def test_auto_send_button_answers_its_trigger(self):
        handler = SequenceHandler(config_data=sequences_from_buttons([ACK_BUTTON]))
        match = handler.check_data(b"\x05")
        assert match.name == "ACK (auto-send)"
        assert match.get_response_bytes() == b"\x06"

    def test_reply_uses_the_buttons_checksum_and_line_ending(self):
        button = dict(ACK_BUTTON, message="OK", format="ascii", line_ending="crlf",
                      checksum="xor8")
        reply = SequenceHandler(config_data=sequences_from_buttons([button])
                                ).check_data(b"\x05").get_response_bytes()
        assert reply == b"OK" + bytes([ord("O") ^ ord("K")]) + b"\r\n"

    def test_buttons_without_auto_send_are_ignored(self):
        assert sequences_from_buttons([{"id": "x", "message": "X"}]) == []

    def test_disabled_auto_send_is_ignored(self):
        button = dict(ACK_BUTTON, auto_send=dict(ACK_BUTTON["auto_send"], enabled=False))
        assert sequences_from_buttons([button]) == []

    @pytest.mark.parametrize("buttons", [None, "text", {"a": 1}, ["junk", 5]])
    def test_malformed_input_is_harmless(self, buttons):
        assert sequences_from_buttons(buttons) == []


# ----------------------------------------------------------------------------
# The editor in the app
# ----------------------------------------------------------------------------

def tab_text(app):
    return "\n".join(app.query_one("#tab-ascii LogPanel").lines)


def saved(isolated_cwd):
    return yaml.safe_load((isolated_cwd / "project.yml").read_text(encoding="utf-8"))


async def open_new(app, pilot):
    await pilot.press("ctrl+n")
    await pilot.pause()
    assert isinstance(app.screen, ButtonEditor)
    return app.screen


async def set_mode(editor, pilot, mode):
    editor.query_one(f"#ed-mode-{mode}", RadioButton).value = True
    await pilot.pause()


async def fill(editor, pilot, name=None, sequence=None, mode=None):
    if mode:
        await set_mode(editor, pilot, mode)
    if name is not None:
        editor.query_one("#ed-name", Input).value = name
    if sequence is not None:
        editor.query_one("#ed-sequence", TextArea).load_text(sequence)
    await pilot.pause()


class TestCreating:
    async def test_new_button_is_saved_and_shown(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "Read regs", "01 03 00 00 00 0a", mode="hex")
            editor.query_one("#ed-checksum", Select).value = "crc16_modbus"
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert not isinstance(app.screen, ButtonEditor)
            entry = saved(isolated_cwd)["buttons"][-1]
            assert entry == {"id": "read-regs", "label": "Read regs",
                             "message": "01 03 00 00 00 0A", "format": "hex",
                             "checksum": "crc16_modbus"}
            assert app.query_one("#read-regs", Button).label.plain == "Read regs"

    async def test_new_button_sends_what_the_editor_showed(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "Hello", "HI<CR><LF>")
            await pilot.click("#ed-ok")
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            await pilot.click("#hello")
            await pilot.pause()
            assert port.written == [b"HI\r\n"]

    async def test_ids_are_unique_and_legal(self, write_config, make_app, isolated_cwd):
        write_config(dict(MINIMAL_CONFIG, buttons=[{"id": "ping", "label": "Ping"}]))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            for _ in range(2):
                editor = await open_new(app, pilot)
                await fill(editor, pilot, "Ping", "P")
                await pilot.click("#ed-ok")
                await pilot.pause()
            ids = [b["id"] for b in saved(isolated_cwd)["buttons"]]
            assert ids == ["ping", "ping-2", "ping-3"]

    async def test_new_button_from_the_panel(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#new-button")
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor)

    async def test_first_button_in_an_empty_project(self, isolated_cwd, make_app):
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "First", "X")
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert [b["label"] for b in saved(isolated_cwd)["buttons"]] == ["First"]


class TestValidation:
    async def test_nothing_is_saved_while_invalid(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor)
            error = str(editor.query_one("#ed-error").render())
            assert "Name is required" in error and "Sequence is empty" in error
            assert len(saved(isolated_cwd)["buttons"]) == len(MINIMAL_CONFIG["buttons"])

    async def test_empty_form_does_not_nag_before_saving(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            assert str(editor.query_one("#ed-error").render()).strip() == ""

    async def test_bad_sequence_is_reported_live(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, sequence="4G", mode="hex")
            assert "not a hex digit" in str(editor.query_one("#ed-error").render())

    async def test_repeat_needs_positive_seconds(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "R", "R")
            editor.query_one("#ed-repeat", Checkbox).value = True
            editor.query_one("#ed-repeat-seconds", Input).value = "0"
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert "seconds above 0" in str(editor.query_one("#ed-error").render())

    async def test_invalid_auto_send_pattern_is_rejected(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "A", "A")
            editor.query_one("#ed-auto", Checkbox).value = True
            editor.query_one("#ed-auto-data", Input).value = "ZZ"
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert "isn't valid HEX" in str(editor.query_one("#ed-error").render())


class TestEditMode:
    async def test_switching_mode_converts_the_sequence(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, sequence="PING<CR><LF>")
            area = editor.query_one("#ed-sequence", TextArea)
            await set_mode(editor, pilot, "hex")
            assert area.text == "50 49 4E 47 0D 0A"
            await set_mode(editor, pilot, "decimal")
            assert area.text == "80 73 78 71 13 10"
            await set_mode(editor, pilot, "ascii")
            assert area.text == "PING<CR><LF>"

    async def test_switch_that_would_lose_bytes_is_refused(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, sequence="FF", mode="hex")
            await set_mode(editor, pilot, "ascii")
            assert editor.mode == "hex"
            assert editor.query_one("#ed-sequence", TextArea).text == "FF"
            assert editor.query_one("#ed-mode-hex", RadioButton).value
            assert "Can't switch to ASCII" in str(editor.query_one("#ed-error").render())

    async def test_line_ending_only_for_ascii(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            assert not editor.query_one("#ed-eol", Select).disabled
            await set_mode(editor, pilot, "hex")
            assert editor.query_one("#ed-eol", Select).disabled

    async def test_position_indicator(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, sequence="01 02 03", mode="hex")
            editor.query_one("#ed-sequence", TextArea).move_cursor((0, 3))
            await pilot.pause()
            assert str(editor.query_one("#ed-pos").render()) == "Pos. 2 / 3"


class TestEditing:
    async def test_fields_are_loaded(self, write_config, make_app):
        write_config(dict(MINIMAL_CONFIG, buttons=[{
            "id": "poll", "label": "Poll", "message": "01 03", "format": "hex",
            "checksum": "crc16_modbus", "repeat": 1500, "tooltip": "Reads regs",
            "auto_send": {"receive": {"data": "ID??", "format": "ascii"}, "delay": 20},
        }]))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(0)
            await pilot.pause()
            ed = app.screen
            assert ed.query_one("#ed-name", Input).value == "Poll"
            assert ed.query_one("#ed-sequence", TextArea).text == "01 03"
            assert ed.query_one("#ed-mode-hex", RadioButton).value
            assert ed.query_one("#ed-checksum", Select).value == "crc16_modbus"
            assert ed.query_one("#ed-repeat", Checkbox).value
            assert ed.query_one("#ed-repeat-seconds", Input).value == "1.5"
            assert ed.query_one("#ed-auto", Checkbox).value
            assert ed.query_one("#ed-auto-format", Select).value == "ascii"
            assert ed.query_one("#ed-auto-data", Input).value == "ID??"
            assert ed.query_one("#ed-auto-delay", Input).value == "20"
            assert ed.query_one("#ed-doc", TextArea).text == "Reads regs"
            assert ed.query_one("#ed-apply", Button).disabled, "nothing changed yet"

    async def test_edit_keeps_id_and_unknown_keys(self, write_config, make_app, isolated_cwd):
        write_config(dict(MINIMAL_CONFIG, buttons=[
            {"id": "ping", "label": "Ping", "message": "P", "format": "ascii", "custom": 42}]))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(0)
            await pilot.pause()
            await fill(app.screen, pilot, name="Ping!")
            await pilot.click("#ed-ok")
            await pilot.pause()
            entry = saved(isolated_cwd)["buttons"][0]
            assert entry["id"] == "ping" and entry["label"] == "Ping!" and entry["custom"] == 42

    async def test_repeat_seconds_stored_as_milliseconds(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(0)
            await pilot.pause()
            ed = app.screen
            ed.query_one("#ed-repeat", Checkbox).value = True
            ed.query_one("#ed-repeat-seconds", Input).value = "0.25"
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert saved(isolated_cwd)["buttons"][0]["repeat"] == 250

    async def test_unticking_repeat_removes_it(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)  # buttons[1] repeats every 500 ms
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(1)
            await pilot.pause()
            app.screen.query_one("#ed-repeat", Checkbox).value = False
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert "repeat" not in saved(isolated_cwd)["buttons"][1]

    async def test_cancel_discards(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(0)
            await pilot.pause()
            await fill(app.screen, pilot, name="Changed")
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ButtonEditor)
            assert saved(isolated_cwd)["buttons"][0]["label"] == "Ping"

    async def test_apply_saves_and_stays_open(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "Draft", "D")
            assert not editor.query_one("#ed-apply", Button).disabled
            await pilot.click("#ed-apply")
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor)
            assert editor.query_one("#ed-apply", Button).disabled
            assert not editor.query_one("#ed-delete", Button).disabled
            await fill(editor, pilot, name="Final")
            await pilot.click("#ed-ok")
            await pilot.pause()
            labels = [b["label"] for b in saved(isolated_cwd)["buttons"]]
            assert labels.count("Final") == 1 and "Draft" not in labels, "Apply then OK: one button"

    async def test_regression_editing_keeps_other_repeats_running(self, write_config, make_app):
        """A full reload stops every repeating button; an edit must not."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.serial_conn = FakeSerialConnection()
            poll = app.query_one("#btn-poll", Button)
            app._start_repeating_button(poll.id, poll, "AA", "hex", 500)
            app.open_button_editor(0)  # edit Ping, not Poll
            await pilot.pause()
            await fill(app.screen, pilot, name="Ping 2")
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert "btn-poll" in app.repeating_buttons
            assert app.query_one("#btn-poll", Button).has_class("button-repeating")

    async def test_editing_a_repeating_button_stops_it(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.serial_conn = FakeSerialConnection()
            poll = app.query_one("#btn-poll", Button)
            app._start_repeating_button(poll.id, poll, "AA", "hex", 500)
            app.open_button_editor(1)
            await pilot.pause()
            await fill(app.screen, pilot, sequence="BB")
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert "btn-poll" not in app.repeating_buttons

    async def test_refused_when_project_yml_is_unreadable(self, isolated_cwd, make_app):
        (isolated_cwd / "project.yml").write_text("buttons: [unclosed", encoding="utf-8")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert not isinstance(app.screen, ButtonEditor)
            assert "Can't edit buttons" in tab_text(app)


class TestDeleting:
    async def test_needs_two_clicks(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.open_button_editor(0)
            await pilot.pause()
            await pilot.click("#ed-delete")
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor), "first click only arms it"
            assert app.screen.query_one("#ed-delete", Button).label.plain == "Confirm delete"
            await pilot.pause(0.3)  # a Button ignores clicks during its 0.2 s press animation
            await pilot.click("#ed-delete")
            await pilot.pause()
            assert not isinstance(app.screen, ButtonEditor)
            assert [b["id"] for b in saved(isolated_cwd)["buttons"]] == ["btn-poll"]
            assert not app.query("#btn-ping")

    async def test_new_button_cannot_be_deleted(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            assert editor.query_one("#ed-delete", Button).disabled


class FakeClick:
    def __init__(self, button):
        self.button = button
        self.stopped = False

    def stop(self):
        self.stopped = True


class TestOpeningAnExistingButton:
    async def test_right_click_opens_the_editor_and_does_not_send(self, write_config, make_app):
        """Exercises ControlButton directly, so it runs on every Textual version."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            button = app.query_one("#btn-ping", ControlButton)
            event = FakeClick(3)
            await button._on_click(event)
            await pilot.pause()
            assert event.stopped
            assert isinstance(app.screen, ButtonEditor) and app.screen.index == 0
            assert port.written == []

    async def test_regression_left_click_still_sends(self, write_config, make_app):
        """REGRESSION: the right-click override called Button._on_click (a
        coroutine) without awaiting it, so a plain click sent nothing."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            await app.query_one("#btn-ping", ControlButton)._on_click(FakeClick(1))
            await pilot.pause()
            assert port.written == [b"PING"]

    @pytest.mark.skipif("button" not in inspect.signature(Pilot.click).parameters,
                        reason="this Textual's pilot can't right-click")
    async def test_right_click_end_to_end(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#btn-poll", button=3)
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor) and app.screen.index == 1

    async def test_edit_mode_click_edits_instead_of_sending(self, write_config, make_app):
        """Edit mode works in terminals that keep the right button to themselves."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            await pilot.click("#edit-buttons")
            await pilot.pause()
            assert app.query_one("#control-buttons").has_class("-editing")
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert isinstance(app.screen, ButtonEditor) and app.screen.index == 0
            assert port.written == []
            await pilot.press("escape")
            await pilot.pause()
            await pilot.click("#edit-buttons")  # Done
            await pilot.pause()
            await pilot.click("#btn-ping")
            await pilot.pause()
            assert port.written == [b"PING"]


class TestAutoSend:
    async def test_button_answers_a_received_frame(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor = await open_new(app, pilot)
            await fill(editor, pilot, "ACK", "06", mode="hex")
            editor.query_one("#ed-auto", Checkbox).value = True
            editor.query_one("#ed-auto-data", Input).value = "05"
            await pilot.click("#ed-ok")
            await pilot.pause()
            assert saved(isolated_cwd)["buttons"][-1]["auto_send"] == {
                "receive": {"data": "05", "format": "hex"}, "delay": 0}

            port = FakeSerialConnection()
            app.serial_conn = port
            app._on_frame_received(b"\x05")
            await pilot.pause()
            assert b"\x06" in port.written
            assert "Auto-sent: ACK" in tab_text(app)

    async def test_auto_send_buttons_load_from_project_yml(self, write_config, make_app):
        write_config(dict(MINIMAL_CONFIG, buttons=[ACK_BUTTON]))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            app._on_frame_received(b"\x05")
            await pilot.pause()
            assert port.written == [b"\x06"]

    async def test_deleting_the_button_removes_its_auto_send(self, write_config, make_app):
        write_config(dict(MINIMAL_CONFIG, buttons=[ACK_BUTTON]))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.delete_button(0)
            await pilot.pause()
            port = FakeSerialConnection()
            app.serial_conn = port
            app._on_frame_received(b"\x05")
            await pilot.pause()
            assert port.written == []


class TestPanelAtSmallSizes:
    async def test_regression_toolbar_leaves_a_row_of_buttons_visible(self, write_config, make_app):
        """REGRESSION: at 80x24 the stacked panel is two rows tall, and the new
        toolbar plus its spacing row pushed every button out of view."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            panel = app.query_one("#control-buttons")
            first = app.query_one("#btn-ping", Button)
            assert panel.content_region.contains_region(first.region)
            assert panel.content_region.contains_region(app.query_one("#new-button").region)
