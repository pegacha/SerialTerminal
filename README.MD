# SerialTerminal

A Textual-based TUI for talking to serial devices. Connect to a port, send and
receive in ASCII / hex / decimal / binary, drive the device from configurable
buttons, and auto-respond to incoming frames with pattern-matched sequences.

Built for embedded work where a plain serial monitor isn't enough — protocol
bring-up, poll/response emulation, and replaying captured exchanges.

---

## Requirements

* Python 3.10 or newer (the code uses PEP 604 `X | Y` annotations)
* `textual >= 0.47.0`, `pyserial >= 3.5`, `pyyaml >= 6.0.3`, `textual-fspicker >= 0.0.5`

## Running

Packaging is not currently usable — the wheel omits `main.py`, `sequence_handler.py`,
`ui/widgets/` and `ui/styles.tcss`, so the `serialterminal` console script cannot
import its entry point. Run from source until that is fixed:

```bash
pip install -r requirements.txt
python main.py
```

---

## Interface

| Area | What it does |
| ---- | ------------ |
| **Serial Config** | Port, baud, parity, data bits, stop bits, connect/disconnect, rescan ports |
| **Log** | Four tabs — ASCII, HEX, Decimal, Binary — showing the same traffic in each notation |
| **Send Command** | One-off send with a per-send format selector |
| **Control Buttons** | Buttons from `project.yml`, optionally repeating |

Every frame is written to all four tabs with one shared timestamp, prefixed
`[TX]`, `[RX]`, `[Error]` or `[Sequence]`.

### Keyboard shortcuts

| Shortcut | Action |
| -------- | ------ |
| `Ctrl+Q` | Quit (saves config and settings) |
| `Ctrl+W` | Clear the log |
| `Ctrl+O` | Open `project.yml` in `$VISUAL`/`$EDITOR` (Notepad on Windows), then reload |
| `Ctrl+L` | Reload `project.yml` |
| `Ctrl+I` | Import config (`.yml`, `.yaml`, or Docklight `.ptp`) |
| `Ctrl+E` | Export current config to a `.yml` file |
| `Ctrl+R` | Reload `styles.tcss` (not shown in the footer) |

---

## Configuration

Two files, with different jobs:

* **`project.yml`** — the working config: serial settings, buttons, sequences.
  Shareable; this is what `Ctrl+I` / `Ctrl+E` move around.
* **`settings.yml`** — per-machine preferences (theme, last imported path).
  Not committed; copy `settings.example.yml` to start. Created with defaults on
  first launch if missing.

The theme lives in `settings.yml` only, so exporting a project doesn't carry your
colour scheme to whoever opens it. A `ui.theme` left in an older `project.yml` is
still honoured once, then dropped on the next save.

`project.yml` is rewritten on connect and on exit, so hand-edits to the `serial`
section are overwritten by whatever the widgets currently show.

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

### Buttons

```yaml
buttons:
  - id: ping             # required, must be unique - it becomes the widget id
    label: Ping          # button text
    message: 'PING\r\n'
    format: ascii        # ascii | hex | decimal | binary
    tooltip: Send a ping  # optional
    repeat: 1000         # optional: ms between repeats; omit or 0 for one-shot
```

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
than the screen, which the TUI owns. Tail it while reproducing:

```bash
tail -f serialterminal.log
```

Received bytes are framed by an inter-byte gap derived from the baud rate —
three character times, clamped to 5–200 ms. A device that pauses mid-frame at a
low baud rate may be split across log lines.

---

## Development

```bash
pip install -r requirements.txt
python main.py
```

`Ctrl+R` reloads `ui/styles.tcss` in place. For Textual's own file watcher and
dev console, install the dev tools first (they are not a project dependency):

```bash
pip install textual-dev
```

```bash
textual run --dev ui.app:TUIApp
```

### Layout

```
main.py                        entry point
ui/app.py                      App: bindings, config, serial and send/receive glue
ui/widgets/                    serial bar, log panel, quick send, control buttons
ui/styles.tcss                 styling
serial_comm/connection.py      pyserial wrapper
serial_comm/receiver.py        RX thread with baud-derived frame gap detection
sequence_handler.py            pattern compilation and matching
utils/formatting.py            log line formatting per notation
utils/docklight_interpreter.py .ptp import
```

### Known gaps

* Packaging is broken; see **Running** above.
* No test suite and no CI.
* `buttons.yml` and `sequences.yml` are leftovers from the pre-`project.yml`
  layout. Nothing reads them.
