from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree


class DirectoryTreeApp(App):
    def compose(self) -> ComposeResult:
        yield DirectoryTree("./")

