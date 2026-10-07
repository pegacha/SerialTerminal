"""textual-fspicker's file dialogs, with compact controls.

The library builds its input bar from Textual's default three-row Button,
Input and Select. These subclasses switch them to one-row compact mode to
match the rest of the app. Subclasses rather than CSS: compact is a widget
property, and copying its internal styles would break with Textual updates.
"""

from textual.widgets import Button, Input, Select
from textual_fspicker import FileOpen, FileSave


class _CompactInputBar:
    def on_mount(self) -> None:
        # Textual calls every on_mount along the MRO, so the library's own
        # mount handling still runs.
        for widget in self.query("InputBar > *"):
            if isinstance(widget, (Button, Input, Select)):
                widget.compact = True


class CompactFileOpen(_CompactInputBar, FileOpen):
    pass


class CompactFileSave(_CompactInputBar, FileSave):
    pass
