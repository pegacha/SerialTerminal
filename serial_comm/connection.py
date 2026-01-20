import serial
import serial.tools.list_ports
from typing import Optional


class SerialConnection:
    """Wrapper for serial port connection."""
    
    def __init__(self):
        self.connection: Optional[serial.Serial] = None
        self.connected = False
    
    @staticmethod
    def list_ports():
        """List available serial ports."""
        ports = serial.tools.list_ports.comports()
        return [(port.device, port.device) for port in ports]
    
    def connect(self, port: str, baud_rate: int = 9600):
        """Connect to a serial port."""
        try:
            print(f"SerialConnection: Connecting to {port} at {baud_rate} baud")
            
            # CRITICAL: timeout must be small (non-blocking) for receiver to work
            self.connection = serial.Serial(
                port=port,
                baudrate=baud_rate,
                timeout=0.1,  # 100ms timeout - don't block forever!
                write_timeout=1.0,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            
            self.connected = True
            print(f"SerialConnection: Connected successfully")
            print(f"SerialConnection: Settings - {self.connection}")
            return True
            
        except Exception as e:
            print(f"SerialConnection: Failed to connect: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from serial port."""
        if self.connection and self.connection.is_open:
            print("SerialConnection: Disconnecting...")
            self.connection.close()
        self.connected = False
        self.connection = None
        print("SerialConnection: Disconnected")
    
    def read(self, size: int = 1024) -> bytes:
        """
        Read available data from serial port.
        
        THIS IS THE CRITICAL METHOD FOR RX!
        
        Args:
            size: Maximum number of bytes to read
        
        Returns:
            Bytes read from serial port, or empty bytes if nothing available
        """
        if not self.connected or not self.connection:
            return b''
        
        try:
            # Check how many bytes are waiting
            waiting = self.connection.in_waiting
            
            if waiting > 0:
                # Read all available bytes (up to 'size')
                bytes_to_read = min(waiting, size)
                data = self.connection.read(bytes_to_read)
                print(f"SerialConnection.read(): Read {len(data)} bytes: {data}")
                return data
            
            # No data available
            return b''
            
        except Exception as e:
            print(f"SerialConnection.read(): Error: {e}")
            import traceback
            traceback.print_exc()
            return b''
    
    def write(self, data: bytes) -> int:
        """Write data to serial port."""
        if not self.connected or not self.connection:
            print("SerialConnection.write(): Not connected")
            return 0
        
        try:
            print(f"SerialConnection.write(): Writing {len(data)} bytes: {data}")
            written = self.connection.write(data)
            self.connection.flush()  # Ensure data is sent immediately
            print(f"SerialConnection.write(): Wrote {written} bytes")
            return written
            
        except Exception as e:
            print(f"SerialConnection.write(): Error: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def flush_input(self):
        """Flush input buffer."""
        if self.connected and self.connection:
            self.connection.reset_input_buffer()
            print("SerialConnection: Input buffer flushed")
    
    def flush_output(self):
        """Flush output buffer."""
        if self.connected and self.connection:
            self.connection.reset_output_buffer()
            print("SerialConnection: Output buffer flushed")