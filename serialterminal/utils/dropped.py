"""Recognise a project file dropped onto the terminal window.

A terminal app never receives a dropped file, only text: terminals type the
file's path as if it were pasted. How it is written varies:

    Windows Terminal       "C:\\Users\\me\\My Configs\\bench.yml"   (quoted if spaces)
    old Windows console    C:\\Users\\me\\bench.yml
    macOS Terminal, iTerm  /Users/me/My\\ Configs/bench.yml       (spaces escaped)
    many Linux terminals   file:///home/me/My%20Configs/bench.yml or a quoted path
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

PROJECT_SUFFIXES = {".yml", ".yaml", ".ptp"}


def dropped_path(text: str, platform: str | None = None) -> Path | None:
    """The single path in `text` as a terminal writes a dropped file, else None."""
    platform = sys.platform if platform is None else platform
    text = text.strip()
    if not text or "\n" in text or "\r" in text:
        return None  # several files, or ordinary multi-line text
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        text = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc != "localhost":
            text = f"//{parsed.netloc}{text}"  # a network share
    elif platform != "win32":
        # Shell-style escapes (macOS: "My\ Configs"). On Windows a
        # backslash is the path separator, so it is left alone.
        text = re.sub(r"\\(.)", r"\1", text)
    return Path(text)


def dropped_project(text: str, platform: str | None = None) -> Path | None:
    """An existing project file (.yml, .yaml or Docklight .ptp) dropped as `text`."""
    path = dropped_path(text, platform)
    try:
        if path is not None and path.suffix.lower() in PROJECT_SUFFIXES and path.is_file():
            return path
    except (OSError, ValueError):
        pass  # not a usable path at all: it was just text
    return None
