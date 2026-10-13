# Changelog

All notable changes to SerialTerminal. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Command history** in Send Command: Up and Down recall earlier commands,
  with their format, like a shell. The last 100 are kept in `settings.yml`.

## [0.3.1] - 2026-10-13

### Added

- **Settings screen** (`F2`): theme, and a color for each kind of log line -
  sent, received, system, errors and sequence replies - with live preview.
  Defaults come from the theme; choices are saved to `settings.yml`.
- **Verbose COM errors** setting. By default a serial-port problem is one
  short line (`Error: couldn't open COM4`); verbose adds the system's message
  and a hint. The detail always goes to `serialterminal.log`.
- **Recent files and favorites** in the import, export and record dialogs: a
  Recent files list, a Favorites list, and stars to add the current folder or
  the named file. Dialogs open in the folder of the last file used.
- **Auto-connect**: pressing a button or sending a command while disconnected
  connects with the current settings first.
- **Frame gap** setting in Settings (`auto`, 10 ms - 1 s), saved with the
  project.
- **Repeat marker**: buttons that resend on a timer show ↻ in the accent color
  (the label color while running). Settings picks ↻, `[R]` or Auto - `[R]` in
  the old Windows console and the Linux text console, which can't draw ↻.
- An icon (`assets/icon.png`, `assets/icon.ico`).

### Changed

- Changing the port or line settings while connected disconnects, instead of
  leaving the port open with settings that no longer match what's shown.
- The automatic frame gap is at least 30 ms (was 5 ms).
- Inputs, dropdowns, text areas and check boxes are tinted toward the text
  color, so they stand out from the panel they sit on. They were the panel's
  own color in every dialog - Settings, the button editor, the file dialogs.
- Settings scrolls on short terminals, with Close and Reset always visible.
- Settings sections are separated by lines with the titles in the accent color,
  and each option's description is one short line.
- The README is a one-page overview; the full reference moved to
  `docs/guide.md` and the developer notes to `docs/development.md`.
- Requires `textual >= 8.2` and `textual-fspicker >= 1.0.1`.

### Fixed

- **Messages split into several lines**: received bytes were cut into
  separate messages whenever a USB-serial adapter delivered them in bursts. The
  receive loop now reads before deciding a message has ended, and the gap
  covers adapter latency.
- **Connected could stay stuck after a port error**: the receive thread and
  the UI waited on each other, freezing the app for 2 s with Connected still
  shown (and Disconnect while data was arriving could do the same). Frames
  and losses are now handed over without waiting, a twice-a-second check
  resets the status if a loss is ever missed, and reconnecting after a loss
  always starts a fresh receive thread.
- A device that sends without ever pausing was never shown: one message
  grew until it stopped. Messages are now shown at 4 KB or half a second.
- **Unplugging the device** flooded `serialterminal.log` with a traceback per
  read attempt (~1000 a second) while the app still showed Connected. The
  connection now ends, the log says why once, and the next send reconnects.
- **Highlighted text in the log was invisible**: the theme's transparent
  selection foreground was drawn literally.
- Automatic sequence replies logged `[TX]` even when the port refused them.
- A setting that couldn't be saved (read-only folder, unreadable `project.yml`)
  failed silently and was lost at the next start; a notification now says so.
- "Stopped all repeating buttons" never appeared in the log on disconnect.
- **File dialogs crashed the app on Python 3.10/3.11 on Windows** when a drive
  letter was in an error state (an empty card reader, a dropped network drive).
  This was also why CI failed on those versions.

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

[0.3.1]: https://github.com/pegacha/SerialTerminal/releases/tag/v0.3.1
[0.3.0]: https://github.com/pegacha/SerialTerminal/releases/tag/v0.3.0
[0.2.0]: https://github.com/pegacha/SerialTerminal/releases/tag/v0.2.0
