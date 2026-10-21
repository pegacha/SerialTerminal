"""Check GitHub for a newer release, and install it.

The check asks GitHub's API for the latest published release of REPO (no
account, nothing sent but the request). Pre-releases and drafts are never
offered. Installing runs pip after the app has closed - see __main__ - from
the release's attached wheel if it has one, else from the tag's source
archive, so neither git nor a GitHub account is needed.

A source checkout (a git clone, or an editable install) is not updated with
pip: that would install a second copy beside it that the checkout never
uses. There the prompt says to git pull instead.
"""

import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PureWindowsPath

from serialterminal import __version__

log = logging.getLogger("serialterminal.updater")

REPO = "pegacha/SerialTerminal"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL_HOURS = 24


@dataclass
class Release:
    version: str        # "0.3.2"
    tag: str            # "v0.3.2"
    page: str           # the release's web page
    notes: str          # its description (Markdown)
    wheel_url: str | None = None

    @property
    def install_target(self) -> str:
        """What pip installs: the attached wheel, else the tag's source archive."""
        return self.wheel_url or f"https://github.com/{REPO}/archive/refs/tags/{self.tag}.zip"


def parse_version(text) -> tuple[int, ...] | None:
    """(0, 3, 2) for "v0.3.2" or "0.3.2"; None for anything else (pre-releases
    such as "0.4.0rc1" included - only plain releases are offered)."""
    if not isinstance(text, str):
        return None
    parts = text.strip().removeprefix("v").split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return new is not None and old is not None and new > old


def release_from_api(data: dict) -> Release | None:
    """A Release from GitHub's JSON, or None if it isn't a usable release."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    if parse_version(tag) is None:
        return None
    wheel = next((asset.get("browser_download_url") for asset in data.get("assets") or []
                  if isinstance(asset, dict)
                  and str(asset.get("name", "")).endswith("-py3-none-any.whl")), None)
    return Release(version=tag.removeprefix("v"), tag=tag,
                   page=data.get("html_url") or f"https://github.com/{REPO}/releases",
                   notes=data.get("body") or "", wheel_url=wheel)


def fetch_latest(timeout: float = 5.0) -> Release | None:
    """The latest published release, or None (none published, offline, ...)."""
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"SerialTerminal/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return release_from_api(json.load(response))
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404: no release published yet
            log.info("update check failed: HTTP %s", e.code)
    except (OSError, ValueError) as e:
        log.info("update check failed: %s", e)
    return None


def source_checkout() -> Path | None:
    """The project folder if running from a git clone or an editable install."""
    package = Path(__file__).resolve().parent
    if (package.parent / ".git").exists():
        return package.parent
    try:
        direct = metadata.distribution("serialterminal").read_text("direct_url.json")
        if direct and json.loads(direct).get("dir_info", {}).get("editable"):
            return package.parent
    except (metadata.PackageNotFoundError, ValueError):
        pass
    return None


def install(target: str) -> int:
    """pip-install `target` over the running copy. Returns pip's exit code.

    Run after the app has closed, in the same console, so pip's output shows.
    """
    command = [sys.executable, "-m", "pip", "install", "--upgrade", target]
    print("Updating SerialTerminal:\n  " + " ".join(command), flush=True)
    return subprocess.call(command)


def launched_by_exe() -> bool:
    """True when started by the `serialterminal` command on Windows.

    That command is a small .exe launcher which runs Python and waits for it.
    It keeps its own file open meanwhile, so pip can neither replace nor
    rename it (WinError 32) and an update must wait until it has exited.
    """
    return (sys.platform == "win32"
            # PureWindowsPath: the path is a Windows one by definition here,
            # and Path() on another OS doesn't split it at backslashes.
            and PureWindowsPath(sys.argv[0]).name.lower() == "serialterminal.exe")


def install_after_exit(target: str) -> None:
    """Hand the update to a helper in its own console window, which waits for
    the launcher (our parent) to exit, installs, then starts the app again."""
    subprocess.Popen(
        [sys.executable, "-m", "serialterminal.updater",
         "--wait", str(os.getppid()), "--restart", target],
        cwd=os.getcwd(), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def wait_for_exit(pid: int, timeout: float = 30.0) -> None:
    """Wait (Windows) until process `pid` has exited, or `timeout` seconds."""
    if sys.platform != "win32":
        return
    import ctypes
    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if handle:  # 0: already gone
        kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        kernel32.CloseHandle(handle)


def main(argv=None) -> int:
    """The helper install_after_exit starts:
    python -m serialterminal.updater [--wait PID] [--restart] TARGET"""
    import argparse
    parser = argparse.ArgumentParser(prog="python -m serialterminal.updater")
    parser.add_argument("--wait", type=int, metavar="PID",
                        help="first wait for this process to exit")
    parser.add_argument("--restart", action="store_true",
                        help="start SerialTerminal again after a successful update")
    parser.add_argument("target", help="what pip installs: a wheel or archive URL or path")
    args = parser.parse_args(argv)
    if args.wait:
        print("Waiting for SerialTerminal to close...", flush=True)
        wait_for_exit(args.wait)
    code = install(args.target)
    if code != 0:
        print("\nThe update failed; SerialTerminal is unchanged.")
        input("Press Enter to close this window.")
        return code
    if args.restart:
        print("Updated. Starting SerialTerminal...", flush=True)
        return subprocess.call([sys.executable, "-m", "serialterminal"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
