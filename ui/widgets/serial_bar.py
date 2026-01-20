from textual.app import ComposeResult
from textual.widgets import Button, Select
from textual.containers import Vertical, Horizontal


class SerialBar(Vertical):
    """Serial port configuration bar."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "serial-bar"
        self.border_title = "Serial Config"

    def compose(self) -> ComposeResult:
        with Horizontal(id="serial-row-top"):
            yield Select(
                options=[("None", "none")],
                value="none",
                id="serial-port-select",
                allow_blank=False
            )

            yield Select(
                options=[
                    ("110", "110"),
                    ("300", "300"),
                    ("600", "600"),
                    ("1200", "1200"),
                    ("2400", "2400"),
                    ("4800", "4800"),
                    ("9600", "9600"),
                    ("14400", "14400"),
                    ("19200", "19200"),
                    ("28800", "28800"),
                    ("38400", "38400"),
                    ("56000", "56000"),
                    ("57600", "57600"),
                    ("115200", "115200"),
                    ("230400", "230400"),
                ],
                value="9600",
                id="serial-baud",
                allow_blank=False,
            )

        with Horizontal(id="serial-row-bottom"):
            yield Select(
                options=[
                    ("None", "N"),
                    ("Even", "E"),
                    ("Odd", "O"),
                    ("Mark", "M"),
                    ("Space", "S"),
                ],
                value="N",
                id="serial-parity",
                allow_blank=False
            )

            yield Select(
                options=[
                    ("5", "5"),
                    ("6", "6"),
                    ("7", "7"),
                    ("8", "8"),
                ],
                value="8",
                id="serial-bits",
                allow_blank=False
            )

            yield Select(
                options=[
                    ("1", "1"),
                    ("1.5", "1.5"),
                    ("2", "2"),
                ],
                value="1",
                id="serial-stop-bits",
                allow_blank=False
            )

            yield Select(
                options=[
                    ("None", "none"),
                    ("Ignore", "ignore"),
                    ("Replace", "replace"),
                ],
                value="none",
                id="serial-error-char",
                allow_blank=False
            )

            yield Button("Connect", id="serial-connect", classes="serial-button")
            yield Button("Disc.", id="serial-disconnect", classes="serial-button", disabled=True)
            yield Button("Refresh", id="refresh-ports", classes="serial-button")
