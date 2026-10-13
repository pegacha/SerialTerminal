"""Recently used project files, in a sidebar on the left of the window.

Collapsed (the default) it is a thin strip reading "Recent projects"
downwards, so it takes almost nothing from the log; expanded it lists the
project files (configs) imported or exported, most recent first - the file
dialogs' Recent files, kept in settings.yml. Picking one imports it, as
Ctrl+T would.
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.message import Message
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option

from serialterminal.ui.widgets.side_strip import SideStrip

KIND = "config"  # Places' kind for project files

# Columns for an entry in the expanded panel (32 wide, less border and padding).
ENTRY_WIDTH = 27

# Hovering an entry that doesn't fit scrolls it: HOLD_STEPS at the start,
# one column per step to the end, HOLD_STEPS there, then over again.
SCROLL_STEP_SECONDS = 0.12
HOLD_STEPS = 8


def tail(text: str, width: int = ENTRY_WIDTH) -> str:
    """`text` cut from the left to fit: the end of a path says the most."""
    return text if len(text) <= width else "…" + text[-(width - 1):]


def window(text: str, step: int | None, width: int = ENTRY_WIDTH) -> str:
    """What fits of `text`: its tail at rest (step None), else the part shown
    `step` steps into a scroll."""
    overflow = len(text) - width
    if overflow <= 0:
        return text
    if step is None:
        return tail(text, width)
    position = step % (overflow + 2 * HOLD_STEPS)
    offset = min(max(position - HOLD_STEPS, 0), overflow)
    return text[offset:offset + width]


def entry(path: str, step: int | None = None) -> Content:
    """The file name, with its folder dimmed on one line below."""
    p = Path(path)
    return Content.assemble(window(p.name, step), "\n", (window(str(p.parent), step), "dim"))


def overflows(path: str) -> bool:
    p = Path(path)
    return max(len(p.name), len(str(p.parent))) > ENTRY_WIDTH


class RecentList(OptionList):
    """The entries; the one under the mouse scrolls if it doesn't fit."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.paths: list[str] = []
        self.scrolling: int | None = None  # index of the entry scrolling
        self.step = 0

    def on_mount(self) -> None:
        self._timer = self.set_interval(SCROLL_STEP_SECONDS, self._advance, pause=True)

    def set_paths(self, paths: list[str]) -> None:
        self._scroll(None)
        self.paths = paths
        self.clear_options()
        self.add_options([Option(entry(path), id=path) for path in paths])

    def on_mouse_move(self, event) -> None:
        # The entry under the mouse, read as OptionList itself reads it. Not
        # its _mouse_hovering_over: that is set by a handler that runs after
        # this one, so the first move onto an entry was missed.
        self._scroll(event.style.meta.get("option"))

    def on_leave(self, _event) -> None:
        self._scroll(None)

    def _scroll(self, index: int | None) -> None:
        if index is not None and not (0 <= index < len(self.paths)
                                      and overflows(self.paths[index])):
            index = None  # fits already: nothing to scroll
        if index == self.scrolling:
            return
        if self.scrolling is not None and self.scrolling < len(self.paths):
            self.replace_option_prompt_at_index(self.scrolling, entry(self.paths[self.scrolling]))
        self.scrolling, self.step = index, 0
        if index is None:
            self._timer.pause()
        else:
            self.replace_option_prompt_at_index(index, entry(self.paths[index], 0))
            self._timer.resume()

    def _advance(self) -> None:
        if self.scrolling is None:
            return
        self.step += 1
        self.replace_option_prompt_at_index(self.scrolling,
                                            entry(self.paths[self.scrolling], self.step))


class RecentFiles(Vertical):
    """Collapsible list of recent project files. Picking one posts RecentFiles.Open."""

    class Open(Message):
        def __init__(self, path: Path):
            super().__init__()
            self.path = path

    def __init__(self, places, **kwargs):
        super().__init__(id="recent-files", **kwargs)
        self.places = places
        self.expanded = False

    def compose(self) -> ComposeResult:
        yield SideStrip("Recent projects", "»", id="recent-strip",
                        tooltip="Recent projects (F3)")
        with Vertical(id="recent-body"):
            with Horizontal(id="recent-header"):
                yield Label("Recent projects", id="recent-title")
                yield Button("«", id="recent-toggle", compact=True,
                             tooltip="Hide recent projects (F3)")
            yield RecentList(id="recent-list", compact=True)
            yield Static("None yet - import or export a project (Ctrl+T, Ctrl+E)",
                         id="recent-empty")

    def on_mount(self) -> None:
        self._show(False)

    def toggle(self) -> None:
        self._show(not self.expanded)

    def _show(self, expanded: bool) -> None:
        self.expanded = expanded
        self.set_class(expanded, "-expanded")
        if expanded:
            self.refresh_list()

    def refresh_list(self) -> None:
        """Re-read the recent files; files that no longer exist are left out."""
        paths = self.places.recent(KIND)
        options = self.query_one("#recent-list", RecentList)
        options.set_paths(paths)
        options.display = bool(paths)
        self.query_one("#recent-empty").display = not paths

    def on_side_strip_toggle(self, event: SideStrip.Toggle) -> None:
        event.stop()
        self.toggle()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "recent-toggle":
            event.stop()
            self.toggle()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.post_message(self.Open(Path(event.option.id)))
