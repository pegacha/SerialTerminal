# Changelog

All notable changes to SerialTerminal. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-10-07

### Added

- **Button editor**, modelled on Docklight's sequence definition: name,
  sequence with an edit mode that converts between ASCII, HEX, Decimal and
  Binary (control characters shown as `<CR>`, `<LF>`, ... in ASCII) and a byte
  position indicator, then Repeat, Checksum, Line ending and Auto-send tabs and
  a documentation box (the button's tooltip). Delete / OK / Cancel / Apply /
  Help. Changes are written straight to `project.yml`.
- Open it with **+ New** or `Ctrl+N`, by **right-clicking** a button, or with
  **Edit** mode (click a button to edit it) for terminals that keep the right
  mouse button to themselves.
- **Auto-send**: a button can also answer automatically when a matching frame
  is received (`??` wildcard, optional delay), using its own checksum and line
  ending - Docklight's receive-sequence answer.
- macOS in CI, alongside Windows and Linux.
- Platform-specific hints when a port won't open: the `dialout` group on
  Linux, `/dev/cu.*` on macOS, port-in-use on Windows.

### Changed

- **Import is `Ctrl+T`.** Terminals send Ctrl+I and Tab as the same byte, so on
  macOS and Linux `Ctrl+I` moved focus instead; it still works as an alias
  where the terminal can tell them apart.
- Editing a button no longer stops other buttons' repeats (a full reload,
  `Ctrl+L`, still does).
- On macOS the first-launch state lives in `~/Library/Application Support`.

### Fixed

- Docklight `.ptp` files with accented labels failed to import on macOS and
  Linux: they're in the Windows ANSI code page, and are now decoded as such.
- Config files are read and written as UTF-8 on every platform instead of the
  platform's default encoding.

## [0.2.0] - 2026-10-07

First tagged release.

### Added

- **Checksums and line endings** for quick send, buttons and sequence
  responses: SUM-8, XOR-8, LRC-8, CRC-16/MODBUS, CRC-16/CCITT-FALSE; none, CR,
  LF or CRLF (ASCII frames only).
- **Live input validation** in Send Command against the selected format, with
  the reason shown (`'G' is not a hex digit`).
- **Log filter** (`Ctrl+F`), **pause** (`Ctrl+B`) without losing traffic, and
  **session recording** (`Ctrl+S`) to an append-only file whose timestamps match
  the screen. A status line shows REC / PAUSED / filter match count.
- **Button sidebar** at 100+ columns, so the log gets the full height; stacks
  under the log on narrower terminals. Short terminals (< 30 rows) trade
  spacing for log rows.
- First-launch offer to put the `serialterminal` command on the user PATH
  (Windows; asked once, never in a venv), and `--add-to-path` to do it on demand.
- `--version`; the version is also shown in the title bar.
- Docklight `.ptp` import (`Ctrl+I`).
- `project.example.yml`, a working starting config (text commands, Modbus RTU
  with CRC, a repeating poll, auto-replies).
- MIT licence.
- Test suite (no hardware needed) and CI on Windows and Linux,
  Python 3.10-3.14, plus a clean-environment wheel install check.

### Changed

- Installable package: everything lives under `serialterminal/`, and
  `pip install .` gives a working `serialterminal` command and
  `python -m serialterminal`.
- One unified `project.yml` (serial, quick send, buttons, sequences);
  per-machine preferences such as the theme live in `settings.yml`.
- The ASCII tab keeps line terminators visible (`<CR><LF>`, `<LF>`, `<CR>`)
  instead of turning them all into line breaks, and no longer adds a blank line
  after every terminated frame.
- Selectors name themselves: "No parity", "8 bits", "1 stop", "No checksum".
- Footer labels shortened and reordered so filter, pause and record fit.
- Requires `textual >= 4.0` and `textual-fspicker >= 0.2.0`.
- `project.yml` is no longer tracked: it holds device-specific commands and is
  rewritten by the app. Copy `project.example.yml` to start.

### Fixed

- **A YAML typo in `project.yml` no longer wipes the file on exit.** An
  unreadable file is reported and left untouched until fixed.
- Malformed button entries (not a mapping, duplicate or illegal ids, a
  non-numeric `repeat`) no longer crash the app at startup or on reload; they
  are repaired or skipped and reported.
- Parity, data bits and stop bits are restored on launch (they were saved but
  came back as 8N1).
- A write the port refuses (unplugged adapter) is reported as a failure: no
  false `[TX]`, and the quick-send text is kept.
- The last frame received before a disconnect is no longer dropped.
- ASCII sequence patterns match regex metacharacters literally
  (`PRICE $1.00`); one malformed sequence no longer discards the rest; an empty
  receive pattern no longer matches every frame.
- Refresh keeps the selected port; repeating buttons stop on config reload.
- Log memory is bounded (the widget's own line buffer grew forever), and the
  filter match count updates live.
- Recording releases its file even if the final write fails.
- Every log tab no longer reserves an empty scrollbar row.

[0.3.0]: https://github.com/pegacha/SerialTerminal/releases/tag/v0.3.0
[0.2.0]: https://github.com/pegacha/SerialTerminal/releases/tag/v0.2.0
