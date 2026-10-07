"""Offering to put the `serialterminal` command on PATH.

pip has no post-install hook - a wheel cannot run code when it is installed -
so the offer is made once, on first launch, before the TUI takes over the
terminal. `python -m serialterminal --add-to-path` does it on demand.

On Windows the user PATH is edited in the registry directly rather than with
`setx`, which rewrites REG_EXPAND_SZ as REG_SZ (breaking %VAR% entries) and
truncates values longer than 1024 characters.
"""

import ntpath
import os
import posixpath
import sys
import sysconfig
from pathlib import Path

import yaml

# Win32 registry value types. Literal so the logic is testable off Windows.
REG_SZ = 1
REG_EXPAND_SZ = 2


def _windows() -> bool:
    return sys.platform == "win32"


def _launcher_name() -> str:
    return "serialterminal.exe" if _windows() else "serialterminal"


def launcher_dir() -> Path | None:
    """The scripts directory holding this interpreter's launcher, if any."""
    candidates = [sysconfig.get_path("scripts")]
    try:
        candidates.append(sysconfig.get_path("scripts", sysconfig.get_preferred_scheme("user")))
    except (AttributeError, KeyError):
        pass
    for path in candidates:
        if path and (Path(path) / _launcher_name()).is_file():
            return Path(path)
    return None


def _norm(entry: str) -> str:
    mod = ntpath if _windows() else posixpath
    return mod.normcase(mod.normpath(mod.expandvars(entry.strip().strip('"'))))


def _contains(path_value: str, directory) -> bool:
    separator = ";" if _windows() else ":"
    target = _norm(str(directory))
    return any(_norm(p) == target for p in (path_value or "").split(separator) if p.strip())


# ----------------------------------------------------------------------------
# Windows user PATH (HKCU\Environment\Path)
# ----------------------------------------------------------------------------

def _read_user_path() -> tuple[str, int]:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        return "", REG_EXPAND_SZ


def _write_user_path(value: str, kind: int) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)


def _broadcast_environment_change() -> None:
    """Tell running programs (Explorer, Start menu) the environment changed."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send = user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = wintypes.LPARAM
    result = ctypes.c_size_t()
    # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG, 5 s timeout
    send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))


def on_path(directory) -> bool:
    """True if `directory` is on this process's PATH or, on Windows, already in
    the saved user PATH (added earlier, terminal not restarted since)."""
    if _contains(os.environ.get("PATH", ""), directory):
        return True
    if _windows():
        try:
            return _contains(_read_user_path()[0], directory)
        except OSError:
            return False
    return False


def add_to_user_path(directory) -> bool:
    """Append `directory` to the persistent user PATH. Windows only.

    Returns False if it was already there. Keeps the value's registry type so
    %VAR% entries keep expanding. Raises OSError if the registry write fails.
    """
    value, kind = _read_user_path()
    if _contains(value, directory):
        return False
    if kind not in (REG_SZ, REG_EXPAND_SZ):
        kind = REG_EXPAND_SZ
    trimmed = (value or "").rstrip(";")
    _write_user_path(f"{trimmed};{directory}" if trimmed else str(directory), kind)
    try:
        _broadcast_environment_change()
    except Exception:
        pass  # the value is saved; it applies after sign-out at the latest
    return True


# ----------------------------------------------------------------------------
# Asking once
# ----------------------------------------------------------------------------

def _state_file() -> Path:
    """Per-user, not per-directory: settings.yml lives in the working directory,
    which would re-ask in every folder the app is started from."""
    if _windows():
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "SerialTerminal" / "state.yml"
    if sys.platform == "darwin":
        # macOS keeps per-user app state here, not in ~/.local (an XDG-ism).
        return Path.home() / "Library" / "Application Support" / "SerialTerminal" / "state.yml"
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "serialterminal" / "state.yml"


def _already_offered() -> bool:
    try:
        state = yaml.safe_load(_state_file().read_text(encoding="utf-8")) or {}
        return bool(state.get("path_offered"))
    except (OSError, yaml.YAMLError, AttributeError):
        return False


def _remember_offered() -> None:
    path = _state_file()
    try:
        try:
            state = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        state["path_offered"] = True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(state), encoding="utf-8")
    except OSError:
        pass  # worst case we ask again next launch


def _interactive() -> bool:
    return bool(sys.stdin and sys.stdin.isatty())


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def _posix_hint(directory, say) -> None:
    say("Add this line to your shell profile (~/.bashrc, ~/.zshrc, ...):")
    say(f'  export PATH="{directory}:$PATH"')


def _apply(directory, say) -> bool:
    try:
        added = add_to_user_path(directory)
    except OSError as e:
        say(f"Could not update PATH: {e}")
        say(f"Add {directory} to your user PATH by hand (Settings > System > About > "
            f"Advanced system settings > Environment Variables).")
        return False
    if added:
        say(f"Added {directory} to your user PATH.")
        say("Open a new terminal and `serialterminal` will work. If new tabs still "
            "don't see it, restart the terminal app.")
    else:
        say(f"{directory} is already on your user PATH. Open a new terminal to pick it up.")
    return True


def offer_on_first_launch(ask=input, say=print) -> None:
    """Ask once whether to put the launcher's folder on PATH.

    Skipped in a venv (activation manages PATH), when not attached to a
    terminal, when there is no installed launcher, when it is already on PATH,
    and once asked. Never raises: a problem here must not stop the app opening.
    """
    try:
        if _in_venv() or not _interactive():
            return
        directory = launcher_dir()
        if directory is None or on_path(directory) or _already_offered():
            return

        say(f"The `serialterminal` command is installed in {directory},")
        say("but that folder is not on your PATH, so typing `serialterminal` won't find it.")
        if not _windows():
            _posix_hint(directory, say)
            _remember_offered()
            return

        try:
            answer = ask("Add it to your user PATH now? [y/N] ")
        except EOFError:
            answer = ""
        _remember_offered()
        if answer.strip().lower() in ("y", "yes"):
            _apply(directory, say)
        else:
            say("Skipped - you won't be asked again. "
                "Run `python -m serialterminal --add-to-path` any time.")
    except Exception as e:  # pragma: no cover - defensive
        say(f"(PATH check skipped: {e})")


def add_to_path_command(say=print) -> int:
    """`python -m serialterminal --add-to-path`. Returns a process exit code."""
    directory = launcher_dir()
    if directory is None:
        say(f"No serialterminal launcher found for this Python ({sys.executable}). "
            "Install it first: pip install .")
        return 1
    if on_path(directory):
        say(f"{directory} is already on your PATH.")
        return 0
    if not _windows():
        say(f"serialterminal is installed in {directory}.")
        _posix_hint(directory, say)
        return 0
    return 0 if _apply(directory, say) else 1
