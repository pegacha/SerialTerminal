from datetime import datetime

def format_frame(frame: bytes) -> str:
    """Format a frame as space-separated uppercase hex bytes."""
    return " ".join(f"{byte:02X}" for byte in frame)

def timestamp() -> str:
    """Get current timestamp in HH:MM:SS format."""
    return datetime.now().strftime("%H:%M:%S")

def format_log_message(message: str) -> str:
    """Format a log message with timestamp."""
    return f"[{timestamp()}] {message}"
