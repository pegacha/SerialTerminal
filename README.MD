# SerialTerminal

A terminal UI for talking to serial devices: send and receive in ASCII, hex,
decimal and binary, drive the device from your own buttons, and answer incoming
frames automatically. Built for embedded work where a plain serial monitor
isn't enough. Runs on Windows, macOS and Linux.

![SerialTerminal: serial settings, the four-notation log, Send Command and the button sidebar](docs/screenshots/main.svg)

## Features

* **Four-notation log** - every frame in ASCII, HEX, Decimal and Binary tabs,
  with control characters named (`<CR>`, `<ACK>`); filter, pause and record.
* **Buttons** - saved commands with an editor modelled on Docklight's; optional
  checksum, line ending, repeat (marked ↻) and auto-send on a matching frame.
* **Sequences** - pattern-matched automatic replies, with `??` wildcards.
* **Checksums** - sum8, xor8, lrc8, CRC-16/MODBUS, CRC-16/CCITT.
* **Docklight import** - `.ptp` projects become buttons and sequences.
* **Send Command** with live validation and shell-style history (Up / Down).
* **Control characters** by name (`<CR>`, `<STX>`...) and by shortcut
  (`Ctrl+Enter` = CR, `Ctrl+Shift+Enter` = LF, others assignable in Settings).
* **Auto-connect** on send; port loss is detected and reported.
* **Settings** (`F2`) - theme, timestamps, log colors, frame gap, verbose errors.

![The button editor](docs/screenshots/button-editor.svg)

## Install

All you need is Python 3.10 or newer - no git. pip downloads the release from
GitHub and installs it.

Windows:

```bash
py -m pip install https://github.com/pegacha/SerialTerminal/archive/refs/tags/v0.4.0.zip
```

```bash
py -m serialterminal
```

macOS and Linux: the same with `python3` instead of `py`. On Linux, join the
`dialout` group to open ports (see [Platform notes](docs/guide.md#platform-notes)).

The `serialterminal` command works too once pip's scripts folder is on your PATH;
the app offers to add it on first launch. Later versions install themselves:
the app checks for new releases (see [Updates](#updates)). From a copy of the
source, `pip install .` installs that copy.

## Quick start

1. Start it - no config needed; `project.yml` is written when you connect or
   quit. Add buttons with **+ New** (`Ctrl+N`), or import a config or Docklight
   `.ptp` (`Ctrl+T`, or drag it onto the window).
2. Pick the port and line settings at the top.
3. Type in **Send Command** or press a button - it connects as needed.

## Shortcuts

| Key | Action |
| --- | ------ |
| `Ctrl+N` | New button (right-click a button to edit it) |
| `Ctrl+F` | Filter the log |
| `Ctrl+B` | Pause / resume the log |
| `Ctrl+S` | Record the session to a file |
| `Ctrl+W` | Clear the log |
| `Ctrl+T` / `Ctrl+E` | Import / export a config (`.yml`, Docklight `.ptp`) |
| `Ctrl+O` / `Ctrl+L` | Edit / reload `project.yml` |
| `F2` | Settings |
| `F3` | Show / hide recent projects (left; hidden at start) |
| `F4` | Show / hide the control buttons (right) |
| `Ctrl+Q` | Quit |

## Updates

At start, at most once a day, SerialTerminal asks GitHub for the latest
release; if it's newer, it offers to install it and restart. Nothing is sent
but that request. Turn it off, or check now, in Settings (`F2`).

## Files

* `project.yml` - serial settings, buttons and sequences. Holds your device's
  commands, so it's git-ignored.
* `settings.yml` - this machine's preferences (theme, colors, recent files).
* `serialterminal.log` - diagnostics; record traffic with `Ctrl+S` instead.

## More

* [Guide](docs/guide.md) - the interface in detail, config reference,
  sequences, checksums, platform notes, troubleshooting.
* [Development](docs/development.md) - tests, project layout, known gaps.
* [Changelog](CHANGELOG.md)

## License

MIT - see [LICENSE](LICENSE).
