"""The "new version available" dialog.

Dismisses with "update", "skip" or None (later). From a source checkout it
offers no install, only the git command, since pip would update a different
copy from the one running.
"""

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

from serialterminal import __version__
from serialterminal.updater import Release


class UpdateScreen(ModalScreen):
    BINDINGS = [Binding("escape", "later", "later", show=False)]

    def __init__(self, release: Release, checkout: Path | None = None):
        super().__init__()
        self.release = release
        self.checkout = checkout

    def compose(self) -> ComposeResult:
        with Vertical(id="update"):
            yield Static(Content(f"SerialTerminal {self.release.version} is available - "
                                 f"you have {__version__}."), id="update-headline")
            with VerticalScroll(id="update-notes"):
                yield Markdown(self.release.notes or "_No release notes._")
            if self.checkout is not None:
                yield Static(Content(f"Running from a source checkout ({self.checkout}). "
                                     f"Update it with: git pull"), id="update-checkout")
            yield Static(Content(self.release.page), id="update-page")
            with Horizontal(id="update-buttons"):
                if self.checkout is None:
                    yield Button("Update and restart", id="update-now", variant="primary",
                                 compact=True)
                yield Button("Skip this version", id="update-skip", compact=True)
                yield Static(classes="update-spacer")
                yield Button("Later", id="update-later", compact=True)

    def on_mount(self) -> None:
        self.query_one("#update").border_title = "Update available"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss({"update-now": "update", "update-skip": "skip"}.get(event.button.id))

    def action_later(self) -> None:
        self.dismiss(None)
