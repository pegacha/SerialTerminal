"""Recent files and favourites in the file dialogs."""

from pathlib import Path

import pytest
import yaml
from textual.widgets import Button, Input, Select
from textual_fspicker.parts import DirectoryNavigation

from serialterminal.utils.places import MAX_RECENT, Places
from tests.conftest import MINIMAL_CONFIG


def make_places(settings=None):
    saves = []
    places = Places(settings if settings is not None else {}, lambda: saves.append(1))
    return places, saves


class TestPlacesStore:
    def test_recent_is_most_recent_first_without_duplicates(self, tmp_path):
        places, saves = make_places()
        a, b = tmp_path / "a.yml", tmp_path / "b.yml"
        a.write_text("x"), b.write_text("x")
        places.add_recent(a, "config")
        places.add_recent(b, "config")
        places.add_recent(a, "config")
        assert places.recent("config") == [str(a.resolve()), str(b.resolve())]
        assert len(saves) == 3

    def test_kinds_are_separate(self, tmp_path):
        places, _ = make_places()
        log = tmp_path / "s.log"
        log.write_text("x")
        places.add_recent(log, "capture")
        assert places.recent("config") == []
        assert places.recent("capture") == [str(log.resolve())]

    def test_recent_is_capped(self, tmp_path):
        places, _ = make_places()
        for i in range(MAX_RECENT + 5):
            f = tmp_path / f"{i}.yml"
            f.write_text("x")
            places.add_recent(f, "config")
        assert len(places.recent("config")) == MAX_RECENT

    def test_missing_files_are_not_offered(self, tmp_path):
        places, _ = make_places()
        gone = tmp_path / "gone.yml"
        gone.write_text("x")
        places.add_recent(gone, "config")
        gone.unlink()
        assert places.recent("config") == []

    def test_favorites_toggle(self, tmp_path):
        places, _ = make_places()
        assert places.toggle_favorite(tmp_path) is True
        assert places.is_favorite(tmp_path)
        assert places.favorites() == [str(tmp_path.resolve())]
        assert places.toggle_favorite(tmp_path) is False
        assert places.favorites() == []

    @pytest.mark.parametrize("junk", [None, "text", 5, {"config": "nope"}])
    def test_malformed_settings_are_tolerated(self, junk):
        places, _ = make_places({"recent_files": junk, "favorites": junk})
        assert places.recent("config") == [] and places.favorites() == []


# ----------------------------------------------------------------------------
# In the dialogs
# ----------------------------------------------------------------------------

@pytest.fixture
def bench(isolated_cwd):
    """A saved config in a sub-folder, as a recent file would be."""
    folder = isolated_cwd / "configs"
    folder.mkdir()
    path = folder / "bench.yml"
    path.write_text(yaml.dump(dict(MINIMAL_CONFIG, buttons=[
        {"id": "bench-ping", "label": "Bench ping", "message": "BP"}])), encoding="utf-8")
    return path


async def open_dialog(app, pilot, key):
    await pilot.press(key)
    for _ in range(20):
        await pilot.pause(0.05)
        if app.screen.query("#picker-places"):
            return app.screen
    raise AssertionError("dialog has no Recent / Favorites row")


def location(dialog) -> Path:
    return Path(dialog.query_one(DirectoryNavigation).location).resolve()


class TestRecentInDialogs:
    async def test_picking_a_recent_config_imports_it(self, write_config, make_app, bench):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.places.add_recent(bench, "config")
            dialog = await open_dialog(app, pilot, "ctrl+t")
            dialog.query_one("#picker-recent", Select).value = str(bench.resolve())
            await pilot.pause(0.3)
            assert type(app.screen).__name__ != "CompactFileOpen", "opened straight away"
            assert app.query("#bench-ping"), "the recent config was imported"

    async def test_import_and_export_become_recent(self, write_config, make_app, bench, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = await open_dialog(app, pilot, "ctrl+t")
            dialog.dismiss(bench)
            await pilot.pause(0.3)
            assert app.places.recent("config")[0] == str(bench.resolve())
            settings = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
            assert str(bench.resolve()) in settings["recent_files"]["config"]

    async def test_dialogs_start_where_the_last_file_was(self, write_config, make_app, bench):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.places.add_recent(bench, "config")
            dialog = await open_dialog(app, pilot, "ctrl+e")
            assert location(dialog) == bench.parent.resolve()

    async def test_save_dialog_fills_in_a_recent_file_instead_of_saving(self, write_config, make_app,
                                                                        bench, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.places.add_recent(bench, "config")
            (isolated_cwd / "elsewhere").mkdir()
            dialog = await open_dialog(app, pilot, "ctrl+e")
            dialog.query_one(DirectoryNavigation).location = isolated_cwd / "elsewhere"
            await pilot.pause()
            dialog.query_one("#picker-recent", Select).value = str(bench.resolve())
            await pilot.pause()
            assert type(app.screen).__name__ == "CompactFileSave", "still asking"
            assert dialog.query_one("InputBar Input", Input).value == "bench.yml"
            assert location(dialog) == bench.parent.resolve()


class TestFavoritesInDialogs:
    async def test_regression_star_folder_adds_and_removes_it(self, write_config, make_app,
                                                              isolated_cwd):
        """REGRESSION: the handlers were declared with @on on a plain mixin,
        which Textual never collects - clicking the star did nothing."""
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = await open_dialog(app, pilot, "ctrl+s")
            folder = location(dialog)
            await pilot.click("#picker-fav-folder")
            await pilot.pause()
            assert app.places.is_favorite(folder)
            assert str(dialog.query_one("#picker-fav-folder", Button).label) == "★ Folder"
            assert not dialog.query_one("#picker-favorites", Select).disabled
            settings = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
            assert str(folder) in settings["favorites"]
            await pilot.pause(0.3)
            await pilot.click("#picker-fav-folder")
            await pilot.pause()
            assert not app.places.is_favorite(folder)

    async def test_picking_a_favorite_folder_goes_there(self, write_config, make_app, bench):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.places.toggle_favorite(bench.parent)
            dialog = await open_dialog(app, pilot, "ctrl+s")
            dialog.query_one("#picker-favorites", Select).value = str(bench.parent.resolve())
            await pilot.pause()
            assert location(dialog) == bench.parent.resolve()

    async def test_star_file_needs_an_existing_file(self, write_config, make_app, bench):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = await open_dialog(app, pilot, "ctrl+t")
            star = dialog.query_one("#picker-fav-file", Button)
            dialog.query_one("InputBar Input", Input).value = "nope.yml"
            await pilot.pause()
            assert star.disabled
            dialog.query_one(DirectoryNavigation).location = bench.parent
            dialog.query_one("InputBar Input", Input).value = "bench.yml"
            await pilot.pause()
            assert not star.disabled
            await pilot.click("#picker-fav-file")
            await pilot.pause()
            assert app.places.is_favorite(bench)

    async def test_picking_a_favorite_file_opens_it(self, write_config, make_app, bench):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.places.toggle_favorite(bench)
            dialog = await open_dialog(app, pilot, "ctrl+t")
            dialog.query_one("#picker-favorites", Select).value = str(bench.resolve())
            await pilot.pause(0.3)
            assert app.query("#bench-ping")

    async def test_empty_lists_are_disabled(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = await open_dialog(app, pilot, "ctrl+t")
            assert dialog.query_one("#picker-recent", Select).disabled
            assert dialog.query_one("#picker-favorites", Select).disabled
