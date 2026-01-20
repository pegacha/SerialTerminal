from dataclasses import dataclass
from config.settings import FRAME_SIZE, FRAME_START, FRAME_END

@dataclass
class Frame:
    pos_level: int
    command: int
    arg1: int
    arg2: int
    
    @classmethod
    def from_bytes(cls, data: bytes) -> 'Frame':
        if not cls.validate(data):
            raise ValueError("Invalid frame")
        return cls(
            pos_level=data[1],
            command=data[2],
            arg1=data[3],
            arg2=data[4]
        )
    
    @staticmethod
    def validate(data: bytes) -> bool:
        return (len(data) == FRAME_SIZE and 
                data[0] == FRAME_START and 
                data[5] == FRAME_END)
    
    def to_bytes(self) -> bytes:
        return bytes([
            FRAME_START,
            self.pos_level,
            self.command,
            self.arg1,
            self.arg2,
            FRAME_END
        ])
