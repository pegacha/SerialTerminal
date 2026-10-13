"""The strip a collapsed side panel leaves behind.

Its arrow and its name written downwards, one letter per row, so a hidden
panel still says it's there. A click anywhere on it posts SideStrip.Toggle.
Where a panel sits under the log rather than beside it (a narrow window),
styles.tcss shows the name across one row instead.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.message import Message
from textual.widgets import Static


class SideStrip(Vertical):
    class Toggle(Message):
        def __init__(self, strip: "SideStrip"):
            super().__init__()
            self.strip = strip

        @property
        def control(self) -> "SideStrip":
            return self.strip

    def __init__(self, label: str, arrow: str, *, tooltip: str | None = None, **kwargs):
        super().__init__(classes="side-strip", **kwargs)
        self.label = label
        self.arrow = arrow
        self.tooltip = tooltip

    def compose(self) -> ComposeResult:
        yield Static(self.arrow, classes="strip-arrow")
        # Content: literal text, never markup.
        yield Static(Content("\n".join(self.label)), classes="strip-vertical")
        yield Static(Content(f"{self.arrow} {self.label}"), classes="strip-horizontal")

    def on_click(self, event) -> None:
        event.stop()
        self.post_message(self.Toggle(self))
