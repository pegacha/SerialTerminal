import serial
import serial.tools.list_ports
from typing import Optional, List, Tuple

class SerialConnection:
    def __init__(self):
        self.connection: Optional[serial.Serial] = None
        self.connected = False
    
    @staticmethod
    def list_ports() -> List[Tuple[str, str]]:
        ports = serial.tools.list_ports.comports()
        return [(port.device, port.device) for port in ports]
    
    def connect(self, port: str, baud_rate: int) -> None:
        self.connection = serial.Serial(port, baud_rate, timeout=1)
        self.connected = True
    
    def disconnect(self) -> None:
        if self.connection and self.connection.is_open:
            self.connection.close()
        self.connected = False
    
    def write(self, data: bytes) -> None:
        if self.connected and self.connection:
            self.connection.reset_input_buffer()
            self.connection.write(data)
    
    def read(self, size: int) -> bytes:
        if self.connected and self.connection:
            return self.connection.read(size)
        return b''
    
    @property
    def bytes_available(self) -> int:
        if self.connected and self.connection:
            return self.connection.in_waiting
        return 0
