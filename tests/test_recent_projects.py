"""The Recent projects sidebar (F3): collapsed by default, imports on click."""

import yaml
from textual.widgets import OptionList

from serialterminal.ui.widgets.recent_panel import RecentFiles, entry, tail
from tests.conftest import MINIMAL_CONFIG

OTHER = {**MINIMAL_CONFIG,
         "buttons": [{"id": "btn-other", "label": "Other", "message": "X", "format": "ascii"}]}


def project(folder, name, config=OTHER):
    path = folder / name
    path.write_text(yaml.dump(config), encoding="utf-8")
    return path


def listed(app):
    return [option.id for option in app.query_one("#recent-list", OptionList).options]


class TestCollapsible:
    async def test_collapsed_by_default(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one(RecentFiles)
            assert not panel.expanded
            assert panel.region.width == 3, "a one-column strip and its button"
            assert not app.query_one("#recent-body").display

    async def test_f3_and_the_button_toggle_it(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one(RecentFiles)
            await pilot.press("f3")
            await pilot.pause()
            assert panel.expanded and panel.region.width == 32
            await pilot.click("#recent-toggle")
            await pilot.pause()
            assert not panel.expanded

    async def test_stays_on_the_left_in_a_narrow_window(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f3")
            await pilot.pause()
            panel = app.query_one(RecentFiles).region
            log = app.query_one("#log-column").region
            assert panel.x == 0 and log.x >= panel.right


class TestList:
    async def test_lists_recent_projects_only_newest_first(self, write_config, make_app,
                                                           isolated_cwd):
        write_config(MINIMAL_CONFIG)
        older = project(isolated_cwd, "older.yml")
        newer = project(isolated_cwd, "newer.yml")
        recording = isolated_cwd / "session.log"
        recording.write_text("x")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.places.add_recent(older, "config")
            app.places.add_recent(newer, "config")
            app.places.add_recent(recording, "capture")
            await pilot.press("f3")
            await pilot.pause()
            assert listed(app) == [str(newer.resolve()), str(older.resolve())]

    async def test_updates_while_open(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f3")
            await pilot.pause()
            assert listed(app) == []
            assert app.query_one("#recent-empty").display
            app.places.add_recent(project(isolated_cwd, "bench.yml"), "config")
            await pilot.pause()
            assert len(listed(app)) == 1
            assert not app.query_one("#recent-empty").display

    def test_long_paths_are_cut_from_the_left(self):
        assert tail("short") == "short"
        cut = tail("C:\\very\\long\\folder\\that\\does\\not\\fit\\configs", 20)
        assert len(cut) == 20 and cut.startswith("…") and cut.endswith("configs")
        # A path in this OS's own form: Linux doesn't split C:\x\bench.yml.
        from pathlib import Path
        folder = Path("x")
        assert entry(str(folder / "bench.yml")).plain == f"bench.yml\n{folder}"


class TestOpening:
    async def test_click_imports_with_a_backup(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        other = project(isolated_cwd, "other.yml")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.places.add_recent(other, "config")
            await pilot.press("f3")
            await pilot.pause()
            app.query_one("#recent-list", OptionList).highlighted = 0
            app.query_one("#recent-list", OptionList).action_select()
            # The import rebuilds the button panel; wait for it, not a fixed time.
            for _ in range(50):
                await pilot.pause(0.05)
                if app.query("#btn-other"):
                    break
            assert app.query("#btn-other"), "the picked project's buttons are shown"
            assert (isolated_cwd / "project.backup.yml").exists()
            saved = yaml.safe_load((isolated_cwd / "project.yml").read_text())
            assert saved["buttons"][0]["id"] == "btn-other"

    async def test_a_file_deleted_since_is_reported(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        gone = project(isolated_cwd, "gone.yml")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.places.add_recent(gone, "config")
            await pilot.press("f3")
            await pilot.pause()
            gone.unlink()
            app.query_one("#recent-list", OptionList).highlighted = 0
            app.query_one("#recent-list", OptionList).action_select()
            await pilot.pause()
            text = "\n".join(app.query_one("#tab-ascii LogPanel").lines)
            assert "gone.yml no longer exists" in text
            assert listed(app) == []
            assert app.query("#btn-ping"), "the current project is untouched"


# ----------------------------------------------------------------------------
# The control buttons panel collapses too (F4), open by default
# ----------------------------------------------------------------------------

from serialterminal.ui.widgets.dynamic_control_buttons import DynamicControlButtons  # noqa: E402
from serialterminal.ui.widgets.side_strip import SideStrip  # noqa: E402


class TestButtonsPanel:
    async def test_open_by_default(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert app.query_one(DynamicControlButtons).display
            assert not app.query_one("#buttons-strip").display

    async def test_hide_and_show(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.click("#hide-buttons")
            await pilot.pause()
            strip = app.query_one("#buttons-strip", SideStrip)
            assert not app.query_one(DynamicControlButtons).display and strip.display
            assert strip.region.width == 3 and strip.region.right == 120, "a strip on the right"
            await pilot.click("#buttons-strip")
            await pilot.pause()
            assert app.query_one(DynamicControlButtons).display and not strip.display
            await pilot.press("f4")
            await pilot.pause()
            assert not app.query_one(DynamicControlButtons).display

    async def test_hiding_leaves_repeats_running(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            poll = app.query_one("#btn-poll")
            app._toggle_repeat_button(poll, "AA", "hex", 500)
            await pilot.press("f4")
            await pilot.pause()
            assert "btn-poll" in app.repeating_buttons
            await pilot.press("f4")
            await pilot.pause()
            assert app.query_one("#btn-poll").has_class("button-repeating")

    async def test_narrow_strip_is_one_row_across(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f4")
            await pilot.pause()
            strip = app.query_one("#buttons-strip")
            assert strip.region.height == 3 and strip.region.width > 40
            assert strip.query_one(".strip-horizontal").display
            assert not strip.query_one(".strip-vertical").display


class TestStripLabels:
    async def test_names_are_written_downwards(self, write_config, make_app):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("f4")
            await pilot.pause()
            for strip_id, name in (("#recent-strip", "Recent projects"),
                                   ("#buttons-strip", "Control buttons")):
                label = app.query_one(f"{strip_id} .strip-vertical")
                assert str(label.render()).split("\n") == list(name)
                assert label.region.height >= len(name), f"{name} fits at 40 rows"


# ----------------------------------------------------------------------------
# A path that doesn't fit scrolls while hovered
# ----------------------------------------------------------------------------

from serialterminal.ui.widgets.recent_panel import (  # noqa: E402
    ENTRY_WIDTH, HOLD_STEPS, RecentList, window,
)


class TestWindow:
    TEXT = r"C:\Users\someone\Documents\Projects\Bench rigs\configs"

    def test_fits_is_left_alone(self):
        assert window("short", 3) == "short"

    def test_at_rest_shows_the_tail(self):
        assert window(self.TEXT, None) == "…" + self.TEXT[-(ENTRY_WIDTH - 1):]

    def test_scroll_holds_slides_holds_repeats(self):
        overflow = len(self.TEXT) - ENTRY_WIDTH
        frames = [window(self.TEXT, step) for step in range(overflow + 2 * HOLD_STEPS + 1)]
        assert all(len(frame) == ENTRY_WIDTH for frame in frames)
        assert frames[0] == frames[HOLD_STEPS] == self.TEXT[:ENTRY_WIDTH], "rests at the start"
        assert frames[HOLD_STEPS + overflow] == self.TEXT[-ENTRY_WIDTH:], "reaches the end"
        assert frames[-2] == self.TEXT[-ENTRY_WIDTH:], "rests at the end"
        assert frames[-1] == frames[0], "then starts over"


class TestHoverScroll:
    async def test_hovered_long_path_scrolls_and_resets(self, write_config, make_app,
                                                        isolated_cwd):
        write_config(MINIMAL_CONFIG)
        deep = isolated_cwd / "a fairly long folder name" / "and another one here"
        deep.mkdir(parents=True)
        path = project(deep, "bench.yml")
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            app.places.add_recent(path, "config")
            await pilot.press("f3")
            await pilot.pause()
            options = app.query_one("#recent-list", RecentList)
            at_rest = str(options.get_option_at_index(0).prompt)
            await pilot.hover("#recent-list", offset=(2, 1))
            await pilot.pause(0.12 * (HOLD_STEPS + 6))
            assert options.scrolling == 0
            scrolled = str(options.get_option_at_index(0).prompt)
            assert scrolled != at_rest, "the folder line moved"
            await pilot.hover("#recent-title")
            await pilot.pause()
            assert options.scrolling is None
            assert str(options.get_option_at_index(0).prompt) == at_rest

    async def test_short_paths_do_not_scroll(self, write_config, make_app, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            options = app.query_one("#recent-list", RecentList)
            options.paths = [r"C:\x\bench.yml"]
            options._scroll(0)
            assert options.scrolling is None
