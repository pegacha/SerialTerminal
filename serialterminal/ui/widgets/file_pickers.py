"""textual-fspicker's file dialogs, with compact controls.

The library builds its input bar from Textual's default three-row Button,
Input and Select. These subclasses switch them to one-row compact mode to
match the rest of the app. Subclasses rather than CSS: compact is a widget
property, and copying its internal styles would break with Textual updates.
"""

import os
import string
from pathlib import Path

from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Select
from textual_fspicker import FileOpen, FileSave
from textual_fspicker.parts import DirectoryNavigation


def _listdrives_safely() -> list[str]:
    """Drive letters that exist, treating any drive that errors as absent."""
    return [f"{letter}:" for letter in string.ascii_uppercase
            if os.path.exists(f"{letter}:\\")]


def _patch_drive_listing() -> None:
    """Stop an unreadable drive letter from crashing every file dialog.

    On Windows the dialogs list drives with os.listdrives() where it exists
    (Python 3.12+), otherwise with Path(f"{letter}:\\").exists(). On 3.10 and
    3.11 that raises for some drive states - WinError 1117 "I/O device error"
    from an empty card reader or a dropped network drive - so the dialog failed
    to compose and the error ended the app. os.path.exists returns False instead.
    """
    if os.name != "nt" or hasattr(os, "listdrives"):
        return
    try:
        from textual_fspicker.parts import drive_navigation
    except ImportError:
        return
    if hasattr(drive_navigation, "listdrives"):
        drive_navigation.listdrives = _listdrives_safely


_patch_drive_listing()


class _CompactInputBar:
    def on_mount(self) -> None:
        # Textual calls every on_mount along the MRO, so the library's own
        # mount handling still runs.
        for widget in self.query("InputBar > *"):
            if isinstance(widget, (Button, Input, Select)):
                widget.compact = True


def _place_label(path: str) -> str:
    """'bench.yml  · Configs', or 'Configs\\  · Documents' for a folder."""
    p = Path(path)
    name = p.name or str(p)
    if p.is_dir():
        name += os.sep
    parent = p.parent.name or str(p.parent)
    return f"{name}  · {parent}" if parent and parent != name else name


class _Places:
    """A Recent / Favorites row above the file list.

    Mounted when the dialog mounts rather than composed through the library's
    _header_area hook, which only exists from textual-fspicker 0.5.0.
    """

    def __init__(self, *args, places=None, kind: str = "config", **kwargs):
        super().__init__(*args, **kwargs)
        self._places = places
        self._places_kind = kind

    async def on_mount(self) -> None:
        if self._places is None:
            return
        try:
            dialog = self.query_one("Dialog")
            navigation = self.query_one(DirectoryNavigation)
        except NoMatches:
            return
        anchor = navigation if navigation.parent is dialog else navigation.parent
        row = Horizontal(
            Select([], prompt="Recent files", id="picker-recent", compact=True),
            Select([], prompt="Favorites", id="picker-favorites", compact=True),
            Button("☆ Folder", id="picker-fav-folder", compact=True),
            Button("☆ File", id="picker-fav-file", compact=True),
            id="picker-places",
        )
        await dialog.mount(row, before=anchor)
        self._refresh_places()

    # -- what the row shows --------------------------------------------------

    def _current_folder(self) -> Path:
        return Path(self.query_one(DirectoryNavigation).location)

    def _named_file(self) -> Path | None:
        try:
            name = self.query_one("InputBar Input", Input).value.strip()
        except NoMatches:
            return None
        if not name:
            return None
        path = Path(name)
        return path if path.is_absolute() else self._current_folder() / path

    def _refresh_places(self) -> None:
        try:
            recent = self.query_one("#picker-recent", Select)
            favorites = self.query_one("#picker-favorites", Select)
        except NoMatches:
            return
        recent_paths = self._places.recent(self._places_kind)
        favorite_paths = self._places.favorites()
        recent.set_options([(_place_label(p), p) for p in recent_paths])
        favorites.set_options([(_place_label(p), p) for p in favorite_paths])
        recent.disabled = not recent_paths
        favorites.disabled = not favorite_paths
        self._refresh_star_buttons()

    def _refresh_star_buttons(self) -> None:
        try:
            folder_button = self.query_one("#picker-fav-folder", Button)
            file_button = self.query_one("#picker-fav-file", Button)
        except NoMatches:
            return
        folder_fav = self._places.is_favorite(self._current_folder())
        folder_button.label = "★ Folder" if folder_fav else "☆ Folder"
        folder_button.tooltip = ("Remove this folder from favorites" if folder_fav
                                 else "Add this folder to favorites")
        file = self._named_file()
        file_fav = file is not None and self._places.is_favorite(file)
        file_button.label = "★ File" if file_fav else "☆ File"
        file_button.tooltip = ("Remove this file from favorites" if file_fav
                               else "Add the file named below to favorites")
        file_button.disabled = file is None or not file.is_file()


    # -- using it -------------------------------------------------------------

    # Handlers here are named on_* rather than declared with @on(...): Textual
    # only collects @on handlers from widget and screen classes, and this is a
    # plain mixin, so decorated handlers were silently never called. Named
    # handlers are found on every class in the MRO.

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id not in ("picker-recent", "picker-favorites"):
            return
        event.stop()
        value = event.value
        if not isinstance(value, str) or not value:
            return  # the blank entry (Select.BLANK in Textual 4, Select.NULL later)
        event.select.clear()  # so the same entry can be picked again
        self.go_to(Path(value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-fav-folder":
            event.stop()
            self._places.toggle_favorite(self._current_folder())
            self._refresh_places()
        elif event.button.id == "picker-fav-file":
            event.stop()
            file = self._named_file()
            if file is not None and file.is_file():
                self._places.toggle_favorite(file)
                self._refresh_places()

    def on_directory_navigation_changed(self, event) -> None:
        self._refresh_star_buttons()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_star_buttons()

    def go_to(self, path: Path) -> None:
        """Show a folder, or pick a file: opening dialogs open it straight away,
        saving dialogs go to its folder and fill in its name."""
        navigation = self.query_one(DirectoryNavigation)
        if path.is_dir():
            navigation.location = path
            return
        if isinstance(self, FileOpen) and path.is_file():
            self.dismiss(path)
            return
        navigation.location = path.parent
        try:
            self.query_one("InputBar Input", Input).value = path.name
        except NoMatches:
            pass



class CompactFileOpen(_Places, _CompactInputBar, FileOpen):
    pass


class CompactFileSave(_Places, _CompactInputBar, FileSave):
    pass
