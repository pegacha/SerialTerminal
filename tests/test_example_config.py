"""project.example.yml is the config new users start from, so it must stay valid.

project.yml itself is git-ignored (it holds device-specific commands), which
makes the example the only config the repository ships.
"""

from pathlib import Path

import pytest
import yaml

from serialterminal.sequence_handler import SequenceHandler
from serialterminal.ui.widgets.dynamic_control_buttons import normalize_buttons
from serialterminal.utils.payload import build_frame

EXAMPLE = Path(__file__).resolve().parent.parent / "project.example.yml"


@pytest.fixture(scope="module")
def example():
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_passes_the_import_validator(example):
    from serialterminal.ui.app import TUIApp

    assert TUIApp.validate_config(None, example) == (True, "")


def test_buttons_need_no_repairs(example):
    buttons, problems = normalize_buttons(example["buttons"])
    assert problems == []
    assert len(buttons) == len(example["buttons"])


def test_every_button_builds_a_frame(example):
    for button in example["buttons"]:
        frame = build_frame(button["message"], button.get("format", "ascii"),
                            button.get("checksum", "none"), button.get("line_ending", "none"))
        assert frame, button["id"]


def test_modbus_example_gets_the_right_crc(example):
    read = next(b for b in example["buttons"] if b["id"] == "modbus-read")
    frame = build_frame(read["message"], read["format"], read["checksum"])
    assert frame.hex(" ").upper() == "01 03 00 00 00 0A C5 CD"


def test_sequences_all_load(example):
    handler = SequenceHandler(config_data=example["sequences"])
    assert handler.skipped == 0
    assert len(handler.sequences) == len(example["sequences"])
    assert handler.check_data(b"\x05").name == "ENQ -> ACK"
    assert handler.check_data(b"ID7").name == "ID query"


async def test_app_starts_from_it_without_errors(isolated_cwd, make_app):
    (isolated_cwd / "project.yml").write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        log_text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
        assert "[Error]" not in log_text
        assert len(list(app.query(".control-button"))) == len(yaml.safe_load(EXAMPLE.read_text())["buttons"])
