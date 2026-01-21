# SerialTerminal

SerialTerminal is a Textual-based TUI (terminal user interface) application for interacting with serial devices. It provides a rich, keyboard-driven interface for connecting to serial ports, sending and receiving data in multiple formats, and automating responses using configurable sequences.

The application is designed for developers, embedded engineers, and anyone who frequently works with serial protocols and wants more flexibility than a basic serial monitor.

---

## Features

* Interactive TUI built with [Textual]
* Serial port discovery and connection management
* Send data in multiple formats:

  * ASCII
  * Hexadecimal
  * Decimal
  * Binary
* Real-time receive log with formatted output
* Quick-send input field
* Configurable buttons (`buttons.yml`)
* Automatic receive/response sequences (`sequences.yml`)
* Optional delayed responses for matched sequences
* Repeating buttons for periodic transmission
* Keyboard shortcuts for common actions

---

## Requirements

* Python 3.9 or newer
* A supported serial device

Python dependencies:

* textual >= 0.47.0
* pyserial >= 3.5
* pyyaml >= 6.0.3

---

## Installation

### Using pip (recommended)

```bash
pip install SerialTerminal
```

After installation, the application can be launched with:

```bash
serialterminal
```

### Windows PATH note

On Windows, if `serialterminal` is not recognized after installation, ensure that the Python *Scripts* directory is on your PATH:

```powershell
python -m site --user-base
```

Add the `Scripts` subdirectory of the printed path to your PATH environment variable, then restart your terminal.

As an alternative, you can always run:

```powershell
python -m serialterminal
```

---

## Usage

### Connecting to a serial device

1. Launch the application
2. Select a serial port from the dropdown
3. Choose baud rate, parity, data bits, and stop bits
4. Press **Connect**

Connection settings are saved automatically.

---

### Sending data

* Use the **Quick Send** input to type commands
* Select the desired format (ASCII, hex, decimal, binary)
* Press Enter or use configured control buttons

---

### Control buttons (`buttons.yml`)

Control buttons are defined in `buttons.yml` and can:

* Send predefined messages
* Override send format
* Repeat at a fixed interval

Buttons can be reloaded at runtime using:

```
Ctrl+B
```

---

### Sequences (`sequences.yml`)

Sequences allow the application to automatically respond to received data.

Each sequence can define:

* Match pattern
* Response data
* Optional delay
* Optional log comment

Sequences can be reloaded at runtime using:

```
Ctrl+S
```


## Keyboard Shortcuts

| Shortcut | Action           |
| -------- | ---------------- |
| Ctrl+Q   | Quit application |
| Ctrl+W   | Clear log        |
| Ctrl+B   | Reload buttons   |
| Ctrl+S   | Reload sequences |


## Configuration Files

* `settings.yml` – persistent application and serial settings
* `buttons.yml` – dynamic control button definitions
* `sequences.yml` – receive/response automation rules

If `settings.yml` does not exist, it will be created on first launch with defaults.




## Development

Clone the repository and install in editable mode:

```bash
pip install -e .
```

Run locally:

```bash
serialterminal
```


