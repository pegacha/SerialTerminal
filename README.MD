# SerialTerminal

A Textual-based TUI for talking to serial devices. Connect to a port, send and
receive in ASCII / hex / decimal / binary, drive the device from configurable
buttons, and auto-respond to incoming frames with pattern-matched sequences.

Built for embedded work where a plain serial monitor isn't enough — protocol
bring-up, poll/response emulation, and replaying captured exchanges.

---

## Requirements

* Python 3.10 or newer (the code uses PEP 604 `X | Y` annotations)
* `textual >= 4.0`, `pyserial >= 3.5`, `pyyaml >= 6.0.3`, `textual-fspicker >= 0.2.0`
  (the suite is run against exactly these minimums as well as the latest)

## Installing

```bash
pip install .
```

Then launch it with either:

```bash
serialterminal
```

```bash
python -m serialterminal
```

### PATH

If `serialterminal` is not recognised after installing, the folder pip put it
in is not on your PATH. pip can't fix that itself (packages can't run code at
install time), so the app offers on its first launch:

```
The `serialterminal` command is installed in C:\...\Python314\Scripts,
but that folder is not on your PATH, so typing `serialterminal` won't find it.
Add it to your user PATH now? [y/N]
```

Answering `y` adds the folder to your **user** PATH (no admin rights needed),
keeping existing `%VAR%` entries intact. Open a new terminal afterwards. The
question is asked once; the answer is remembered in
`%LOCALAPPDATA%\SerialTerminal\state.yml`. It isn't asked inside a virtual
environment, where activation manages PATH. On Linux and macOS it prints the
`export` line for your shell profile instead of editing it.

To do it any time, without the prompt:

```bash
python -m serialterminal --add-to-path
```

`python -m serialterminal` always works, PATH or not. `--version` prints the
installed version, which is also shown in the title bar.

---

## Interface

| Area | What it does |
| ---- | ------------ |
| **Serial Config** | Port, baud, parity, data bits, stop bits, connect/disconnect, rescan ports |
| **Log** | Four tabs — ASCII, HEX, Decimal, Binary — showing the same traffic in each notation, with filter, pause and recording |
| **Send Command** | One-off send: format, line ending, checksum, and live validation of what you type |
| **Control Buttons** | Buttons from `project.yml`, optionally repeating, with their own checksum and line ending |

Every frame is written to all four tabs with one shared timestamp, prefixed
`[TX]`, `[RX]`, `[Error]` or `[Sequence]`. The ASCII tab names control
characters (`<STX>`, `<ACK>`, ...) and keeps line terminators visible, so you
can see whether a device sent `<CR><LF>`, `<LF>` or `<CR>`; a new line starts
after each one.

Controls are one row tall and meant for the mouse, so most of the screen goes
to the log. To make everything bigger or smaller, zoom the terminal itself
(`Ctrl` + `+`/`-` or `Ctrl` + mouse wheel in Windows Terminal); the app has
no font size of its own.

**Layout.** At 100 columns or more, control buttons sit in a sidebar to the
right of the log, so they never take rows from it. Narrower than that, a
sidebar would leave the log too thin for a hex frame, so the buttons move under
the log instead, capped at about a third of the height. Either way the panel
scrolls when there are more buttons than fit. Labels longer than about 25
characters are shortened with `…`; hover a button to see it in full. Under 30
rows the title line and spacing give way to log rows.

**Send Command.** The input is checked as you type against the selected
format: a red border and a reason (`'G' is not a hex digit`) mean it would not
send. A failed send keeps your text, including a write the port refused (an
unplugged adapter); only a successful one clears the box, and `[TX]` is logged
only for bytes that actually went out. The format, line ending and checksum you
pick are saved in `project.yml`.

**Filter** (`Ctrl+F`). Shows only log entries containing the text,
case-insensitive. Each tab matches its own notation, so `41 42` finds a frame
on the HEX tab and `AB` finds it on the ASCII tab. Timestamps are not searched;
the direction tag is, so `[RX]` shows only received frames. The status line under the log
gives the match count for the current tab. `Esc` or `Ctrl+F` again closes the
filter and brings everything back.

**Pause** (`Ctrl+B`). Freezes the view so you can scroll and read while traffic
keeps arriving. Nothing is lost: entries are still recorded (and captured, if
recording) and appear when you resume. The status line counts what arrived
meanwhile. Each tab keeps its last 20,000 entries for filtering and resuming.

**Record** (`Ctrl+S`). Asks for a file (default `session-YYYYMMDD-HHMMSS.log`)
and appends every log entry to it until you press `Ctrl+S` again or quit. An
existing file is appended to, never overwritten. Timestamps match the screen.
Lines look like:

```
2026-10-06 16:07:23.286 TX   01 03 00 00 00 0A C5 CD  |........|
2026-10-06 16:07:23.544 RX   50 4F 4E 47 0D 0A  |PONG..|
```

### Keyboard shortcuts

| Shortcut | Action |
| -------- | ------ |
| `Ctrl+Q` | Quit (saves config and settings) |
| `Ctrl+W` | Clear the log |
| `Ctrl+O` | Open `project.yml` in `$VISUAL`/`$EDITOR` (Notepad on Windows), then reload |
| `Ctrl+L` | Reload `project.yml` |
| `Ctrl+I` | Import config (`.yml`, `.yaml`, or Docklight `.ptp`) |
| `Ctrl+E` | Export current config to a `.yml` file |
| `Ctrl+F` | Filter the log; `Esc` closes |
| `Ctrl+B` | Pause / resume the log view |
| `Ctrl+S` | Start / stop recording the session to a file |
| `Ctrl+R` | Reload `styles.tcss` (not shown in the footer) |

`Ctrl+W` and `Ctrl+E` don't work while a text box has focus, because the box
uses them for delete-word and end-of-line. Click elsewhere or press `Tab`
first. See Known gaps.

---

## Configuration

Two files, with different jobs:

* **`project.yml`** — the working config: serial settings, quick-send options, buttons, sequences.
  Shareable; this is what `Ctrl+I` / `Ctrl+E` move around.
* **`settings.yml`** — per-machine preferences (theme, last imported path).
  Not committed; copy `settings.example.yml` to start. Created with defaults on
  first launch if missing.

The theme lives in `settings.yml` only, so exporting a project doesn't carry your
colour scheme to whoever opens it. A `ui.theme` left in an older `project.yml` is
still honoured once, then dropped on the next save.

`project.yml` is rewritten on connect and on exit, so hand-edits to the `serial`
section are overwritten by whatever the widgets currently show.

**Mistakes in `project.yml` are reported, not fatal.** Problems appear as
`[Error]` lines in the log at startup and on every reload:

* If the file can't be read at all (a YAML syntax error, or a top level that
  isn't a mapping), the app starts with an empty config and **will not save over
  the file**, so a typo never costs you its contents. Fix it (`Ctrl+O`) and
  reload (`Ctrl+L`).
* A button entry that isn't a mapping is skipped. A missing, duplicate or
  illegal `id` (ids are letters, digits, `-` and `_`, not starting with a
  digit) is replaced on screen with a legal unique one; your file keeps what you
  wrote. A `repeat` that isn't a number makes the button one-shot.
* A malformed sequence is skipped and the rest still load.

### Serial

```yaml
serial:
  port: COM4          # or /dev/ttyUSB0; `none` means nothing selected
  baud_rate: 9600
  parity: N           # N, E, O, M, S
  data_bits: '8'      # 5, 6, 7, 8   (quoted - these are strings)
  stop_bits: '1'      # 1, 1.5, 2
```

All five fields are restored on launch. If a saved port is gone (adapter
unplugged) the log says so rather than connecting to something else.

### Quick send

Written from the Send Command bar on exit and on connect; restored on launch.

```yaml
quick_send:
  format: hex            # ascii | hex | decimal | binary
  line_ending: none      # none | cr | lf | crlf
  checksum: crc16_modbus # see Checksums and line endings
```

### Buttons

```yaml
buttons:
  - id: ping             # required, must be unique - it becomes the widget id
    label: Ping          # button text
    message: 'PING'
    format: ascii        # ascii | hex | decimal | binary
    line_ending: crlf    # optional, default none
    checksum: none       # optional, default none
    tooltip: Send a ping  # optional
    repeat: 1000         # optional: ms between repeats; omit or 0 for one-shot
```

Use `line_ending` rather than writing `\r\n` into `message`. Inside single
quotes YAML keeps backslashes literally, so `'PING\r\n'` sends a
backslash, an `r`, a backslash and an `n`. Buttons use only their own
`checksum` and `line_ending`, never the Send Command bar's.

A button with `repeat` greater than 0 toggles: first press starts the interval
and highlights the button, second press stops it. Repeats also stop on
disconnect and on config reload.

### Sequences

Sequences watch received frames and answer automatically.

```yaml
sequences:
  - name: ACK Response     # required
    active: true           # optional, default true
    delay: 0               # optional, ms to wait before replying
    comment: ACK received  # optional, logged when the pattern matches
    receive:
      data: '06'
      format: hex          # hex | ascii | decimal | binary
    send:
      data: '06'
      format: hex
      checksum: none       # optional, as for buttons
      line_ending: none    # optional, as for buttons
```

The first matching active sequence wins; matching is a substring search, not a
whole-frame match.

**Wildcards.** `??` matches any single byte. How you write it depends on the
format:

| Format | Pattern | Matches |
| ------ | ------- | ------- |
| `hex` | `3A ?? 0D 0A` | one wildcard byte, space-separated tokens |
| `decimal` | `58 ?? 13 10` | same, in decimal |
| `binary` | `00111010 ???????? 00001101` | a full 8-bit `????????` group |
| `ascii` | `PRICE ??` | one wildcard character |

Everything that isn't a wildcard is matched literally, including regex
metacharacters — `PRICE $1.00` matches exactly that text.

A sequence that fails to parse is skipped on its own; the rest still load, and
the reload message reports how many were dropped. Details go to the log file.

### Checksums and line endings

The frame is built as: payload, then the checksum over the payload, then the
line ending. The checksum is appended as raw bytes. The line ending applies
to ASCII only: hex, decimal and binary frames go out exactly as written, so a
CRLF chosen for text never lands on a binary frame. The selector greys out to
show this.

| `checksum` | Algorithm | Bytes appended |
| ---------- | --------- | -------------- |
| `none` | — | none |
| `sum8` | 8-bit sum | 1 |
| `xor8` | XOR of all bytes | 1 |
| `lrc8` | Two's complement of the 8-bit sum | 1 |
| `crc16_modbus` | CRC-16/MODBUS (poly 0x8005 reflected, init 0xFFFF) | 2, low byte first |
| `crc16_ccitt` | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) | 2, high byte first |

An unknown `checksum` or `line_ending` in `project.yml` means nothing is sent
when the button or sequence fires. A button reports it on screen; a sequence
reports it in `serialterminal.log`.

### Importing from Docklight

`Ctrl+I` on a `.ptp` file converts Docklight send/receive definitions into
buttons and sequences. Docklight's `##` data markers become `??` wildcards.
The current `project.yml` is backed up to `project.backup.yml` first.

The parser assumes the field layout of the `.ptp` files it was written against
and does no bounds checking, so an unexpected file shape will report an error
rather than import partially.

---

## Troubleshooting

Diagnostics go to `serialterminal.log` (rotating, ~4 MB across 4 files) rather
than the screen, which the TUI owns. That file is about the app itself; to keep
the traffic, record a session with `Ctrl+S`. Tail it while reproducing:

```bash
tail -f serialterminal.log
```

Received bytes are framed by an inter-byte gap derived from the baud rate —
three character times, clamped to 5–200 ms. A device that pauses mid-frame at a
low baud rate may be split across log lines.

---

## Development

Editable install with the test dependencies:

```bash
pip install -e ".[dev]"
```

```bash
python -m serialterminal
```

### Tests

```bash
python -m pytest
```

No serial hardware needed: the suite drives a fake connection and Textual's
headless pilot. Tests run in a temp directory, so a run never touches your own
`project.yml`. CI runs them on 3.10-3.14, on Windows and Linux, and separately
builds a wheel and installs it into a clean environment.

`Ctrl+R` reloads `serialterminal/ui/styles.tcss` in place. For Textual's own
file watcher and dev console, install the dev tools (not a project dependency):

```bash
pip install textual-dev
```

```bash
textual run --dev serialterminal.ui.app:TUIApp
```

### Layout

```
serialterminal/
  __main__.py                    entry point (console script and python -m)
  ui/app.py                      App: bindings, config, serial and send/receive glue
  ui/widgets/                    serial bar, log panel, quick send, control buttons
  ui/styles.tcss                 styling
  serial_comm/connection.py      pyserial wrapper
  serial_comm/receiver.py        RX thread with baud-derived frame gap detection
  sequence_handler.py            pattern compilation and matching
  utils/payload.py               text -> bytes per notation; frame assembly
  utils/checksum.py              checksum algorithms
  utils/session_capture.py       Ctrl+S session recording
  utils/formatting.py            log line formatting per notation
  utils/docklight_interpreter.py .ptp import
tests/                           pytest suite, fake serial connection
```

### Known gaps

* The Docklight importer assumes the field layout of the `.ptp` files it was
  written against, and its tests are characterization tests built from that
  same assumption rather than from a real Docklight export.
* `Ctrl+W` (clear) and `Ctrl+E` (export) are shadowed while a text box has
  focus, because Textual's `Input` binds them to delete-word and end-of-line.
* At 80×24 the log gets about ten rows and the button panel one row of
  buttons (it scrolls). 100×30 or larger is comfortable.
* The quick-send box has no command history yet; a successful send clears it.
