"""The update check (GitHub's latest release), the dialog, and installing."""

import io
import json
import urllib.error

import pytest
import yaml
from textual.widgets import Button

import serialterminal.__main__ as entry
from serialterminal import __version__, updater
from serialterminal.updater import Release, fetch_latest as real_fetch_latest
from serialterminal.ui.widgets.update_screen import UpdateScreen
from tests.conftest import MINIMAL_CONFIG

NEWER = Release(version="99.0.0", tag="v99.0.0",
                page="https://github.com/pegacha/SerialTerminal/releases/tag/v99.0.0",
                notes="- Something new")


class TestVersions:
    @pytest.mark.parametrize("text,expected", [
        ("v0.3.2", (0, 3, 2)), ("0.3.2", (0, 3, 2)), ("1.10", (1, 10)),
        ("0.4.0rc1", None), ("v", None), ("", None), (None, None), ("latest", None),
    ])
    def test_parse(self, text, expected):
        assert updater.parse_version(text) == expected

    def test_newer(self):
        assert updater.is_newer("0.3.10", "0.3.9"), "numeric, not alphabetical"
        assert not updater.is_newer("0.3.1", "0.3.1")
        assert not updater.is_newer("0.3.0", "0.3.1")
        assert not updater.is_newer("0.4.0rc1", "0.3.1"), "pre-releases are not offered"


def api(tag="v0.3.2", **extra):
    return {"tag_name": tag, "html_url": f"https://example/{tag}", "body": "notes",
            "draft": False, "prerelease": False, "assets": [], **extra}


class TestReleaseFromGitHub:
    def test_archive_when_no_wheel_is_attached(self):
        release = updater.release_from_api(api())
        assert release.version == "0.3.2"
        assert release.install_target == \
            "https://github.com/pegacha/SerialTerminal/archive/refs/tags/v0.3.2.zip"

    def test_attached_wheel_preferred(self):
        wheel = "https://example/serialterminal-0.3.2-py3-none-any.whl"
        release = updater.release_from_api(api(assets=[
            {"name": "notes.txt", "browser_download_url": "https://example/notes.txt"},
            {"name": "serialterminal-0.3.2-py3-none-any.whl", "browser_download_url": wheel}]))
        assert release.install_target == wheel

    @pytest.mark.parametrize("data", [api(draft=True), api(prerelease=True), api(tag="nightly"),
                                      "not a dict", None])
    def test_unusable(self, data):
        assert updater.release_from_api(data) is None


class TestFetch:
    def test_reads_the_latest_release(self, monkeypatch):
        def fake_urlopen(request, timeout):
            assert request.full_url == updater.LATEST_URL
            assert request.get_header("User-agent").startswith("SerialTerminal/")
            return io.BytesIO(json.dumps(api("v1.2.3")).encode())
        monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
        assert real_fetch_latest().version == "1.2.3"

    @pytest.mark.parametrize("error", [
        urllib.error.HTTPError(updater.LATEST_URL, 404, "Not Found", {}, None),  # none published
        urllib.error.HTTPError(updater.LATEST_URL, 403, "rate limited", {}, None),
        urllib.error.URLError("offline"),
        TimeoutError("slow"),
    ])
    def test_failures_are_quiet(self, monkeypatch, error):
        def fail(request, timeout):
            raise error
        monkeypatch.setattr(updater.urllib.request, "urlopen", fail)
        assert real_fetch_latest() is None

    def test_this_repository_is_a_checkout(self):
        assert updater.source_checkout() is not None


def offer(monkeypatch, release=NEWER, checkout=None):
    monkeypatch.setattr(updater, "fetch_latest", lambda timeout=5.0: release)
    monkeypatch.setattr(updater, "source_checkout", lambda: checkout)


async def settle(pilot, condition, tries=40):
    for _ in range(tries):
        await pilot.pause(0.05)
        if condition():
            return


class TestAtStart:
    async def test_newer_release_is_offered(self, write_config, make_app, monkeypatch):
        write_config(MINIMAL_CONFIG)
        offer(monkeypatch)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, lambda: isinstance(app.screen, UpdateScreen))
            assert isinstance(app.screen, UpdateScreen)
            assert app.screen.query("#update-now")

    async def test_update_and_restart_closes_with_the_target(self, write_config, make_app,
                                                             monkeypatch):
        write_config(MINIMAL_CONFIG)
        offer(monkeypatch)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, lambda: isinstance(app.screen, UpdateScreen))
            app.screen.query_one("#update-now", Button).press()
            await pilot.pause()
        assert app.update_target == NEWER.install_target

    async def test_checkout_gets_git_pull_instead(self, write_config, make_app, monkeypatch,
                                                  tmp_path):
        write_config(MINIMAL_CONFIG)
        offer(monkeypatch, checkout=tmp_path)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, lambda: isinstance(app.screen, UpdateScreen))
            assert not app.screen.query("#update-now")
            assert "git pull" in str(app.screen.query_one("#update-checkout").render())

    async def test_skipped_version_is_not_offered_again(self, write_config, make_app,
                                                        monkeypatch, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        offer(monkeypatch)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, lambda: isinstance(app.screen, UpdateScreen))
            app.screen.query_one("#update-skip", Button).press()
            await pilot.pause()
        saved = yaml.safe_load((isolated_cwd / "settings.yml").read_text())
        assert saved["updates"]["skip"] == "99.0.0"

        saved["updates"].pop("last_checked")  # make the next start check again
        (isolated_cwd / "settings.yml").write_text(yaml.dump(saved))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            assert not isinstance(app.screen, UpdateScreen)

    async def test_checked_at_most_once_a_day(self, write_config, make_app, monkeypatch,
                                              isolated_cwd):
        write_config(MINIMAL_CONFIG)
        calls = []
        monkeypatch.setattr(updater, "fetch_latest", lambda timeout=5.0: calls.append(1))
        for _ in range(2):
            app = make_app()
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause(0.3)
        assert len(calls) == 1

    async def test_can_be_turned_off(self, write_config, make_app, monkeypatch, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        (isolated_cwd / "settings.yml").write_text(yaml.dump({"updates": {"check": False}}))
        calls = []
        monkeypatch.setattr(updater, "fetch_latest", lambda timeout=5.0: calls.append(1))
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
        assert calls == []


class TestCheckNow:
    async def test_reports_when_up_to_date(self, write_config, make_app, monkeypatch):
        write_config(MINIMAL_CONFIG)
        current = Release(version=__version__, tag=f"v{__version__}", page="", notes="")
        offer(monkeypatch, release=current)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            seen = []
            app.notify = lambda message, **kwargs: seen.append(message)
            await pilot.press("f2")
            await pilot.pause(0.2)
            app.screen.query_one("#settings-update-now").press()  # below the fold at 40 rows
            await settle(pilot, lambda: seen)
            assert seen == [f"You have the latest version ({__version__})."]

    async def test_offers_a_skipped_version_when_asked(self, write_config, make_app,
                                                       monkeypatch, isolated_cwd):
        write_config(MINIMAL_CONFIG)
        (isolated_cwd / "settings.yml").write_text(yaml.dump({"updates": {"skip": "99.0.0"}}))
        offer(monkeypatch)
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            assert not isinstance(app.screen, UpdateScreen)
            app.check_for_updates(manual=True)
            await settle(pilot, lambda: isinstance(app.screen, UpdateScreen))
            assert isinstance(app.screen, UpdateScreen)


class TestInstallAfterClosing:
    def run(self, monkeypatch, target, install_code):
        class FakeApp:
            def run(self):
                self.update_target = target

        calls = []
        monkeypatch.setattr("serialterminal.ui.app.TUIApp", FakeApp)
        monkeypatch.setattr(entry.path_setup, "offer_on_first_launch", lambda: None)
        monkeypatch.setattr(updater, "install", lambda t: calls.append(("install", t))
                            or install_code)
        monkeypatch.setattr(entry.subprocess, "call", lambda cmd: calls.append(("start", cmd))
                            or 0)
        return entry.main([]), calls

    def test_installs_then_restarts(self, monkeypatch):
        code, calls = self.run(monkeypatch, "https://example/x.whl", 0)
        assert code == 0
        assert calls[0] == ("install", "https://example/x.whl")
        assert calls[1][0] == "start" and calls[1][1][1:] == ["-m", "serialterminal"]

    def test_failed_install_does_not_restart(self, monkeypatch, capsys):
        code, calls = self.run(monkeypatch, "https://example/x.whl", 1)
        assert code == 1 and [c[0] for c in calls] == ["install"]
        assert "pip install --upgrade https://example/x.whl" in capsys.readouterr().out

    def test_no_update_just_exits(self, monkeypatch):
        code, calls = self.run(monkeypatch, None, 0)
        assert code == 0 and calls == []


class TestStartedByTheExe:
    """pip can't replace the running serialterminal.exe (WinError 32), so when
    it started the app the update runs in a helper once it has exited."""

    @pytest.mark.parametrize("argv0,platform,expected", [
        (r"C:\venv\Scripts\serialterminal.exe", "win32", True),
        (r"C:\venv\Scripts\SerialTerminal.EXE", "win32", True),
        ("-m", "win32", False),                       # python -m serialterminal
        ("/usr/local/bin/serialterminal", "linux", False),
    ])
    def test_detection(self, monkeypatch, argv0, platform, expected):
        monkeypatch.setattr(updater.sys, "argv", [argv0])
        monkeypatch.setattr(updater.sys, "platform", platform)
        assert updater.launched_by_exe() is expected

    def test_main_hands_off_to_the_helper(self, monkeypatch):
        class FakeApp:
            def run(self):
                self.update_target = "https://example/x.whl"

        handed = []
        monkeypatch.setattr("serialterminal.ui.app.TUIApp", FakeApp)
        monkeypatch.setattr(entry.path_setup, "offer_on_first_launch", lambda: None)
        monkeypatch.setattr(updater, "launched_by_exe", lambda: True)
        monkeypatch.setattr(updater, "install_after_exit", handed.append)
        monkeypatch.setattr(updater, "install", lambda t: pytest.fail("installed in-process"))
        assert entry.main([]) == 0
        assert handed == ["https://example/x.whl"]

    def test_helper_waits_then_installs_then_restarts(self, monkeypatch):
        steps = []
        monkeypatch.setattr(updater, "wait_for_exit", lambda pid: steps.append(("wait", pid)))
        monkeypatch.setattr(updater, "install", lambda t: steps.append(("install", t)) or 0)
        monkeypatch.setattr(updater.subprocess, "call",
                            lambda cmd: steps.append(("start", cmd[1:])) or 0)
        assert updater.main(["--wait", "1234", "--restart", "x.whl"]) == 0
        assert steps == [("wait", 1234), ("install", "x.whl"),
                         ("start", ["-m", "serialterminal"])]
