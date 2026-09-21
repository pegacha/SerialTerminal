"""Shared fixtures.

The app writes project.yml and settings.yml on mount and on unmount, so every
test that constructs a TUIApp runs inside a throwaway directory. Without this a
test run silently rewrites the developer's own config - which is exactly what
happened while these bugs were first being diagnosed.
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run the test in an empty directory, leaving the real config alone."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def write_config(isolated_cwd):
    """Write a project.yml into the isolated directory."""

    def _write(config: dict, name: str = "project.yml") -> Path:
        path = isolated_cwd / name
        path.write_text(yaml.dump(config), encoding="utf-8")
        return path

    return _write


@pytest.fixture
def make_app(isolated_cwd):
    """Build a TUIApp inside the isolated directory.

    Imported lazily so the chdir is already in place: TUIApp reads its config
    in __init__.
    """

    def _make():
        from ui.app import TUIApp

        return TUIApp()

    return _make


MINIMAL_CONFIG = {
    "serial": {
        "port": "none",
        "baud_rate": 9600,
        "parity": "N",
        "data_bits": "8",
        "stop_bits": "1",
    },
    "buttons": [
        {"id": "btn-ping", "label": "Ping", "message": "PING", "format": "ascii"},
        {
            "id": "btn-poll",
            "label": "Poll",
            "message": "AA BB",
            "format": "hex",
            "repeat": 500,
        },
    ],
    "sequences": [
        {
            "name": "ACK",
            "receive": {"data": "06", "format": "hex"},
            "send": {"data": "06", "format": "hex"},
        }
    ],
}
