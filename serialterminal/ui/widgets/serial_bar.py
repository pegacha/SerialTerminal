from textual.app import ComposeResult
from textual.widgets import Button, Select, Static
from textual.containers import Vertical, Horizontal


class SerialBar(Vertical):
    """Serial port configuration bar.

    Compact (one-row) widgets throughout: the app is driven with the mouse,
    and the default three-row boxes left the log a third of the screen.
    The line-setting options name themselves ("No parity", "8 bits"):
    there is no room for labels, and a bare "None 8 1" row gave no hint
    which selector was which. The stored values are unchanged.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = "serial-bar"
        self.border_title = "Serial Config"

    def compose(self) -> ComposeResult:
        with Horizontal(id="serial-row-top"):
            yield Select(
                options=[("No port", "none")],
                value="none",
                id="serial-port-select",
                allow_blank=False,
                compact=True,
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
                compact=True,
            )

            yield Static("● Disconnected", id="serial-status", classes="status-disconnected")

        with Horizontal(id="serial-row-bottom"):
            yield Select(
                options=[
                    ("No parity", "N"),
                    ("Even", "E"),
                    ("Odd", "O"),
                    ("Mark", "M"),
                    ("Space", "S"),
                ],
                value="N",
                id="serial-parity",
                allow_blank=False,
                compact=True,
            )

            yield Select(
                options=[
                    ("5 bits", "5"),
                    ("6 bits", "6"),
                    ("7 bits", "7"),
                    ("8 bits", "8"),
                ],
                value="8",
                id="serial-bits",
                allow_blank=False,
                compact=True,
            )

            yield Select(
                options=[
                    ("1 stop", "1"),
                    ("1.5 stop", "1.5"),
                    ("2 stop", "2"),
                ],
                value="1",
                id="serial-stop-bits",
                allow_blank=False,
                compact=True,
            )

            yield Button("Connect", id="serial-connect", classes="serial-button", compact=True)
            yield Button("Disconnect", id="serial-disconnect", classes="serial-button",
                         disabled=True, compact=True)
            yield Button("Refresh", id="refresh-ports", classes="serial-button", compact=True)
