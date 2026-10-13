# Development

Editable install with the test dependencies:

```bash
pip install -e ".[dev]"
```

```bash
python -m serialterminal
```

## Tests

```bash
python -m pytest
```

No serial hardware needed: the suite drives a fake connection and Textual's
headless pilot. Tests run in a temp directory, so a run never touches your own
`project.yml`. CI runs them on Python 3.10-3.14 on Windows, macOS and Linux,
and separately builds a wheel and installs it into a clean environment.

`Ctrl+R` reloads `serialterminal/ui/styles.tcss` in place. For Textual's own
file watcher and dev console, install the dev tools (not a project dependency):

```bash
pip install textual-dev
```

```bash
textual run --dev serialterminal.ui.app:TUIApp
```

## Layout

```
serialterminal/
  __main__.py                    entry point (console script and python -m)
  path_setup.py                  first-launch PATH offer, --add-to-path
  ui/app.py                      App: bindings, config, serial and send/receive glue
  ui/widgets/                    serial bar, log panel, quick send, control buttons
  ui/widgets/button_editor.py    the button editor
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

## Known gaps

* The Docklight importer assumes the field layout of the `.ptp` files it was
  written against, and its tests are characterization tests built from that
  same assumption rather than from a real Docklight export.
* `Ctrl+W` (clear) and `Ctrl+E` (export) are shadowed while a text box has
  focus, because Textual's `Input` binds them to delete-word and end-of-line.
* At 80×24 the log gets about ten rows and the button panel one row of
  buttons (it scrolls). 100×30 or larger is comfortable.
