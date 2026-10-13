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


def tail(text: str, width: int = ENTRY_WIDTH) -> str:
    """`text` cut from the left to fit: the end of a path says the most."""
    return text if len(text) <= width else "…" + text[-(width - 1):]


def entry(path: str) -> Content:
    """The file name, with its folder dimmed on one line below."""
    p = Path(path)
    return Content.assemble(tail(p.name), "\n", (tail(str(p.parent)), "dim"))


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
            yield OptionList(id="recent-list", compact=True)
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
        options = self.query_one("#recent-list", OptionList)
        options.clear_options()
        options.add_options([Option(entry(path), id=path) for path in paths])
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
