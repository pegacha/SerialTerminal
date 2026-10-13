"""Dropping a project file onto the window opens it (terminals paste the path)."""

from pathlib import Path

import pytest
import yaml
from textual import events
from textual.widgets import Input

from serialterminal.utils.dropped import dropped_path, dropped_project
from tests.conftest import MINIMAL_CONFIG

OTHER = {**MINIMAL_CONFIG,
         "buttons": [{"id": "btn-other", "label": "Other", "message": "X", "format": "ascii"}]}


class TestHowTerminalsWriteADrop:
    @pytest.mark.parametrize("text,platform,expected", [
        ('"C:\\My Configs\\bench.yml"', "win32", "C:\\My Configs\\bench.yml"),  # Windows Terminal
        ("C:\\Configs\\bench.yml", "win32", "C:\\Configs\\bench.yml"),          # old console
        ("/Users/me/My\\ Configs/bench.yml", "darwin", "/Users/me/My Configs/bench.yml"),
        ("'/home/me/My Configs/bench.yml'", "linux", "/home/me/My Configs/bench.yml"),
        ("  /home/me/bench.yml \n", "linux", "/home/me/bench.yml"),
    ])
    def test_path_spellings(self, text, platform, expected):
        assert str(dropped_path(text, platform)) == str(Path(expected))

    def test_file_uri(self, tmp_path):
        target = tmp_path / "My Configs" / "bench.yml"
        target.parent.mkdir()
        target.write_text("{}")
        assert dropped_project(target.as_uri()) == target

    @pytest.mark.parametrize("text", ["", "PING", "01 03 00 00", "a.yml\nb.yml"])
    def test_not_a_single_path(self, text):
        assert dropped_project(text) is None


class TestOnlyExistingProjectFiles:
    @pytest.mark.parametrize("name", ["bench.yml", "bench.YAML", "legacy.ptp"])
    def test_project_files(self, tmp_path, name):
        (tmp_path / name).write_text("{}")
        assert dropped_project(f'"{tmp_path / name}"') == tmp_path / name

    def test_other_files_are_just_text(self, tmp_path):
        (tmp_path / "session.log").write_text("x")
        assert dropped_project(str(tmp_path / "session.log")) is None

    def test_missing_file(self, tmp_path):
        assert dropped_project(str(tmp_path / "gone.yml")) is None

    def test_a_folder(self, tmp_path):
        (tmp_path / "folder.yml").mkdir()
        assert dropped_project(str(tmp_path / "folder.yml")) is None


def other_project(folder):
    path = folder / "My Configs" / "other.yml"
    path.parent.mkdir()
    path.write_text(yaml.dump(OTHER), encoding="utf-8")
    return path


async def drop(app, pilot, text):
    app.post_message(events.Paste(text))
    for _ in range(40):  # the import rebuilds the button panel
        await pilot.pause(0.05)
        if app.query("#btn-other"):
            break


class TestDroppingOntoTheWindow:
    async def test_opens_it_even_with_the_command_box_focused(self, write_config, make_app,
                                                               isolated_cwd):
        write_config(MINIMAL_CONFIG)
        path = other_project(isolated_cwd)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.click("#quick-send-input")
            await drop(app, pilot, f'"{path}"')
            assert app.query("#btn-other"), "imported"
            assert app.query_one("#quick-send-input", Input).value == "", "not pasted as text"
            assert (isolated_cwd / "project.backup.yml").exists()
            assert app.places.recent("config") == [str(path.resolve())]

    async def test_ordinary_paste_still_reaches_the_box(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.click("#quick-send-input")
            app.post_message(events.Paste("PING"))
            await pilot.pause()
            assert app.query_one("#quick-send-input", Input).value == "PING"

    async def test_in_a_dialog_a_path_stays_text(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        path = other_project(isolated_cwd)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("ctrl+n")  # the button editor
            await pilot.pause(0.3)
            await pilot.click("#ed-name")
            app.post_message(events.Paste(str(path)))
            await pilot.pause(0.2)
            assert app.screen.query_one("#ed-name", Input).value == str(path)
            assert not app.query("#btn-other")
