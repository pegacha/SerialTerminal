"""Recent files and favourite folders/files for the file dialogs.

Kept in settings.yml, which is per-machine: paths mean nothing on another
computer, so they don't belong in the shareable project.yml.

    recent_files:
      config: [C:\\...\\bench.yml, ...]     # Ctrl+T import, Ctrl+E export
      capture: [C:\\...\\session.log, ...]  # Ctrl+S recording
    favorites: [C:\\...\\Configs, C:\\...\\bench.yml]
"""

from pathlib import Path
from typing import Callable

MAX_RECENT = 10


def _key(path) -> str:
    """One spelling per file, so the same file is never listed twice."""
    try:
        return str(Path(path).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(Path(path).expanduser().absolute())


class Places:
    def __init__(self, settings: dict, save: Callable[[], None]):
        """`settings` is the live settings.yml dict; `save` writes it to disk."""
        self._settings = settings
        self._save = save

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------

    def _recent_table(self) -> dict:
        table = self._settings.get("recent_files")
        if not isinstance(table, dict):
            table = self._settings["recent_files"] = {}
        return table

    def recent(self, kind: str) -> list[str]:
        """Most recent first, leaving out files that no longer exist."""
        entries = self._recent_table().get(kind)
        if not isinstance(entries, list):
            return []
        return [p for p in entries if isinstance(p, str) and Path(p).is_file()]

    def add_recent(self, path, kind: str) -> None:
        table = self._recent_table()
        entries = table.get(kind) if isinstance(table.get(kind), list) else []
        key = _key(path)
        entries = [key] + [p for p in entries if p != key]
        table[kind] = entries[:MAX_RECENT]
        self._save()

    # ------------------------------------------------------------------
    # Favourites
    # ------------------------------------------------------------------

    def _favorite_list(self) -> list:
        entries = self._settings.get("favorites")
        if not isinstance(entries, list):
            entries = self._settings["favorites"] = []
        return entries

    def favorites(self) -> list[str]:
        """Favourite folders and files that still exist, in the order added."""
        return [p for p in self._favorite_list() if isinstance(p, str) and Path(p).exists()]

    def is_favorite(self, path) -> bool:
        return _key(path) in self._favorite_list()

    def toggle_favorite(self, path) -> bool:
        """Add `path` to the favourites, or remove it if it's there. Returns True if added."""
        entries = self._favorite_list()
        key = _key(path)
        if key in entries:
            entries.remove(key)
            added = False
        else:
            entries.append(key)
            added = True
        self._save()
        return added
