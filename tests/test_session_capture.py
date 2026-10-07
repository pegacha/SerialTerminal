"""Session capture file format and lifecycle."""

from datetime import datetime

from serialterminal.utils.session_capture import SessionCapture, format_capture_line

WHEN = datetime(2026, 10, 6, 14, 3, 22, 123456)


class TestLineFormat:
    def test_bytes_get_hex_and_printable_columns(self):
        line = format_capture_line(WHEN, "rx", b"AB\r\n")
        assert line == "2026-10-06 14:03:22.123 RX   41 42 0D 0A  |AB..|"

    def test_text_entries_keep_their_label(self):
        assert format_capture_line(WHEN, "error", "boom").endswith("ERR  boom")
        assert format_capture_line(WHEN, "", "hello").endswith("INFO hello")


class TestLifecycle:
    def test_writes_between_start_and_stop(self, tmp_path):
        cap = SessionCapture()
        cap.start(tmp_path / "s.log")
        cap.write(WHEN, "tx", b"\x01")
        cap.stop()
        cap.write(WHEN, "tx", b"\x02")  # after stop: ignored, not an error
        text = (tmp_path / "s.log").read_text(encoding="utf-8")
        assert "TX   01" in text
        assert "02  |" not in text
        assert text.startswith("# capture started")
        assert "# capture stopped" in text

    def test_appends_instead_of_overwriting(self, tmp_path):
        path = tmp_path / "s.log"
        path.write_text("earlier session\n", encoding="utf-8")
        cap = SessionCapture()
        cap.start(path)
        cap.stop()
        assert path.read_text(encoding="utf-8").startswith("earlier session\n")

    def test_entries_reach_disk_before_stop(self, tmp_path):
        """Line-buffered, so a crash mid-session loses nothing already shown."""
        cap = SessionCapture()
        cap.start(tmp_path / "s.log")
        cap.write(WHEN, "rx", b"\x41")
        assert "RX   41" in (tmp_path / "s.log").read_text(encoding="utf-8")
        cap.stop()

    def test_creates_missing_directories(self, tmp_path):
        cap = SessionCapture()
        cap.start(tmp_path / "a" / "b" / "s.log")
        assert cap.active
        cap.stop()
        assert not cap.active
