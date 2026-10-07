"""PATH offer and --add-to-path.

Nothing here touches the real registry or the real state file: the autouse
fixture swaps both for in-memory fakes, and Windows path rules are forced so
the suite behaves the same on a Linux runner.
"""

import pytest

from serialterminal import path_setup
from serialterminal.path_setup import REG_EXPAND_SZ, REG_SZ

SCRIPTS = r"C:\Users\me\AppData\Local\Python\pythoncore-3.14-64\Scripts"


class FakeRegistry:
    def __init__(self):
        self.value = r"C:\Tools;%USERPROFILE%\bin"
        self.kind = REG_EXPAND_SZ
        self.writes = []
        self.broadcasts = 0
        self.fail_write = False

    def read(self):
        return self.value, self.kind

    def write(self, value, kind):
        if self.fail_write:
            raise PermissionError("access denied")
        self.writes.append((value, kind))
        self.value, self.kind = value, kind

    def broadcast(self):
        self.broadcasts += 1


@pytest.fixture(autouse=True)
def registry(monkeypatch, tmp_path):
    reg = FakeRegistry()
    monkeypatch.setattr(path_setup.sys, "platform", "win32")
    monkeypatch.setattr(path_setup, "_read_user_path", reg.read)
    monkeypatch.setattr(path_setup, "_write_user_path", reg.write)
    monkeypatch.setattr(path_setup, "_broadcast_environment_change", reg.broadcast)
    monkeypatch.setattr(path_setup, "_state_file", lambda: tmp_path / "state" / "state.yml")
    monkeypatch.setattr(path_setup, "launcher_dir", lambda: SCRIPTS)
    monkeypatch.setattr(path_setup, "_interactive", lambda: True)
    monkeypatch.setattr(path_setup, "_in_venv", lambda: False)
    monkeypatch.setenv("PATH", r"C:\Windows\system32")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\me")
    return reg


class Console:
    """Records what the offer prints and answers its question."""

    def __init__(self, answer=""):
        self.answer = answer
        self.asked = 0
        self.lines = []

    def ask(self, prompt):
        self.asked += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def say(self, line=""):
        self.lines.append(line)

    @property
    def text(self):
        return "\n".join(self.lines)


class TestAddToUserPath:
    def test_appends_and_keeps_expandable_type(self, registry):
        assert path_setup.add_to_user_path(SCRIPTS) is True
        assert registry.writes == [(rf"C:\Tools;%USERPROFILE%\bin;{SCRIPTS}", REG_EXPAND_SZ)]
        assert registry.broadcasts == 1

    def test_keeps_plain_string_type(self, registry):
        registry.kind = REG_SZ
        path_setup.add_to_user_path(SCRIPTS)
        assert registry.writes[0][1] == REG_SZ

    @pytest.mark.parametrize("existing", ["", ";", None])
    def test_empty_or_missing_path(self, registry, existing):
        registry.value = existing
        path_setup.add_to_user_path(SCRIPTS)
        assert registry.writes[0][0] == SCRIPTS

    def test_trailing_separator_not_doubled(self, registry):
        registry.value = "C:\\Tools;"
        path_setup.add_to_user_path(SCRIPTS)
        assert registry.writes[0][0] == f"C:\\Tools;{SCRIPTS}"

    @pytest.mark.parametrize(
        "spelling",
        [SCRIPTS.upper(), SCRIPTS + "\\", f'"{SCRIPTS}"',
         r"%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\Scripts"],
    )
    def test_no_duplicate_for_equivalent_spelling(self, registry, spelling):
        registry.value = f"C:\\Tools;{spelling}"
        assert path_setup.add_to_user_path(SCRIPTS) is False
        assert registry.writes == []

    def test_broadcast_failure_does_not_undo_the_write(self, registry, monkeypatch):
        def boom():
            raise OSError("no window station")

        monkeypatch.setattr(path_setup, "_broadcast_environment_change", boom)
        assert path_setup.add_to_user_path(SCRIPTS) is True
        assert registry.writes

    def test_unexpected_registry_type_becomes_expandable(self, registry):
        registry.kind = 7  # REG_MULTI_SZ: not a valid PATH type
        path_setup.add_to_user_path(SCRIPTS)
        assert registry.writes[0][1] == REG_EXPAND_SZ


class TestOnPath:
    def test_found_on_process_path(self, monkeypatch):
        monkeypatch.setenv("PATH", rf"C:\Windows;{SCRIPTS.lower()}")
        assert path_setup.on_path(SCRIPTS)

    def test_found_in_saved_user_path_before_terminal_restart(self, registry):
        registry.value = f"C:\\Tools;{SCRIPTS}"
        assert path_setup.on_path(SCRIPTS)

    def test_absent(self):
        assert not path_setup.on_path(SCRIPTS)

    def test_registry_error_means_absent_not_crash(self, monkeypatch):
        def denied():
            raise PermissionError("denied")

        monkeypatch.setattr(path_setup, "_read_user_path", denied)
        assert not path_setup.on_path(SCRIPTS)


class TestFirstLaunchOffer:
    def test_yes_adds_and_says_to_open_a_new_terminal(self, registry):
        console = Console("y")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert registry.writes
        assert "new terminal" in console.text

    @pytest.mark.parametrize("answer", ["", "n", "no", "nope", EOFError()])
    def test_anything_but_yes_declines(self, registry, answer):
        console = Console(answer)
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert registry.writes == []
        assert "--add-to-path" in console.text

    def test_asked_only_once(self, registry):
        first = Console("n")
        path_setup.offer_on_first_launch(first.ask, first.say)
        second = Console("y")
        path_setup.offer_on_first_launch(second.ask, second.say)
        assert second.asked == 0 and second.lines == []
        assert registry.writes == []

    def test_ctrl_c_at_the_prompt_asks_again_next_time(self, registry):
        with pytest.raises(KeyboardInterrupt):
            path_setup.offer_on_first_launch(Console(KeyboardInterrupt()).ask, lambda *_: None)
        again = Console("n")
        path_setup.offer_on_first_launch(again.ask, again.say)
        assert again.asked == 1

    @pytest.mark.parametrize(
        "attr,value",
        [
            ("_in_venv", lambda: True),
            ("_interactive", lambda: False),
            ("launcher_dir", lambda: None),
        ],
    )
    def test_skipped_silently(self, registry, monkeypatch, attr, value):
        monkeypatch.setattr(path_setup, attr, value)
        console = Console("y")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert console.asked == 0 and console.lines == []
        assert registry.writes == []

    def test_skipped_when_already_on_path(self, registry, monkeypatch):
        monkeypatch.setenv("PATH", SCRIPTS)
        console = Console("y")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert console.asked == 0

    def test_registry_write_failure_is_reported_not_raised(self, registry):
        registry.fail_write = True
        console = Console("y")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert "Could not update PATH" in console.text
        assert "Environment Variables" in console.text

    def test_posix_prints_the_export_line_without_asking(self, registry, monkeypatch):
        monkeypatch.setattr(path_setup.sys, "platform", "linux")
        monkeypatch.setattr(path_setup, "launcher_dir", lambda: "/home/me/.local/bin")
        monkeypatch.setenv("PATH", "/usr/bin")
        console = Console("y")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert console.asked == 0
        assert 'export PATH="/home/me/.local/bin:$PATH"' in console.text
        assert registry.writes == []

    def test_corrupt_state_file_is_treated_as_never_asked(self, registry, tmp_path):
        state = tmp_path / "state" / "state.yml"
        state.parent.mkdir()
        state.write_text("{[ not yaml", encoding="utf-8")
        console = Console("n")
        path_setup.offer_on_first_launch(console.ask, console.say)
        assert console.asked == 1


class TestAddToPathCommand:
    def test_adds(self, registry):
        console = Console()
        assert path_setup.add_to_path_command(console.say) == 0
        assert registry.writes

    def test_already_present(self, registry, monkeypatch):
        monkeypatch.setenv("PATH", SCRIPTS)
        console = Console()
        assert path_setup.add_to_path_command(console.say) == 0
        assert "already" in console.text and registry.writes == []

    def test_no_launcher(self, registry, monkeypatch):
        monkeypatch.setattr(path_setup, "launcher_dir", lambda: None)
        console = Console()
        assert path_setup.add_to_path_command(console.say) == 1
        assert "pip install" in console.text

    def test_write_failure_exits_non_zero(self, registry):
        registry.fail_write = True
        assert path_setup.add_to_path_command(Console().say) == 1


class TestEntryPoint:
    def test_add_to_path_flag_never_starts_the_tui(self, monkeypatch):
        from serialterminal import __main__ as entry
        import serialterminal.ui.app as app_module

        monkeypatch.setattr(path_setup, "add_to_path_command", lambda: 0)
        monkeypatch.setattr(app_module, "TUIApp", lambda: pytest.fail("TUI started"))
        assert entry.main(["--add-to-path"]) == 0

    def test_normal_launch_offers_then_runs(self, monkeypatch):
        from serialterminal import __main__ as entry
        import serialterminal.ui.app as app_module

        calls = []

        class StubApp:
            def run(self):
                calls.append("run")

        monkeypatch.setattr(path_setup, "offer_on_first_launch", lambda: calls.append("offer"))
        monkeypatch.setattr(app_module, "TUIApp", StubApp)
        assert entry.main([]) == 0
        assert calls == ["offer", "run"]
