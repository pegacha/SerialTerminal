import threading
import time
from typing import Callable, Optional
from serial_comm.connection import SerialConnection
from serial_comm.protocol import Protocol
from models.frame import Frame
from config.settings import PING_INTERVAL_SECONDS, FRAME_SIZE, Commands, PosLevel

class SerialReceiver:
    def __init__(self, connection: SerialConnection):
        self.connection = connection
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        self.on_ack: Optional[Callable] = None
        self.on_ping_response: Optional[Callable] = None
        self.on_version: Optional[Callable[[str, str], None]] = None
        self.on_shelf_bitmask: Optional[Callable[[int], None]] = None
        self.on_distance_data: Optional[Callable[[int], None]] = None
        self.on_frame_received: Optional[Callable[[bytes], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _receive_loop(self):
        ping_counter = 0
        
        while self.running and self.connection.connected:
            self._process_incoming()
            
            ping_counter += 1
            if ping_counter >= int(PING_INTERVAL_SECONDS * 10):
                self._send_ping()
                ping_counter = 0
            
            time.sleep(0.1)
    
    def _process_incoming(self):
        try:
            while self.connection.bytes_available >= FRAME_SIZE:
                frame_bytes = self.connection.read(FRAME_SIZE)
                
                if self.on_frame_received:
                    self.on_frame_received(frame_bytes)
                
                try:
                    frame = Frame.from_bytes(frame_bytes)
                    self._handle_frame(frame)
                except ValueError:
                    if self.on_error:
                        self.on_error("Invalid frame received")
        
        except Exception as e:
            if self.on_error:
                self.on_error(f"Error processing: {e}")
    
    def _handle_frame(self, frame: Frame):
        if frame.pos_level != PosLevel.SLAVE_TO_MASTER:
            return
        
        if frame.command == Commands.ACK:
            if self.on_ack:
                self.on_ack()
        
        elif frame.command == Commands.PING:
            if self.on_ping_response:
                self.on_ping_response()
        
        elif frame.command == Commands.GET_VERSION:
            if self.on_version:
                sw_ver, hw_ver = Protocol.parse_version(frame)
                self.on_version(sw_ver, hw_ver)
        
        elif frame.command == Commands.GET_REPORT:
            if self.on_distance_data:
                distance = Protocol.parse_distance(frame)
                self.on_distance_data(distance)
    
    def _send_ping(self):
        try:
            ping_frame = Protocol.create_ping()
            self.connection.write(ping_frame.to_bytes())
        except Exception as e:
            if self.on_error:
                self.on_error(f"Error sending ping: {e}")
