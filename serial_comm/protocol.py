from models.frame import Frame
from config.settings import Commands, PosLevel

class Protocol:
    @staticmethod
    def create_ping() -> Frame:
        return Frame(
            pos_level=PosLevel.MASTER_TO_SLAVE,
            command=Commands.PING,
            arg1=0x00,
            arg2=0x00
        )
    
    @staticmethod
    def create_get_version() -> Frame:
        return Frame(
            pos_level=PosLevel.MASTER_TO_SLAVE,
            command=Commands.GET_VERSION,
            arg1=0x00,
            arg2=0x00
        )
    
    @staticmethod
    def create_get_report() -> Frame:
        return Frame(
            pos_level=PosLevel.MASTER_TO_SLAVE,
            command=Commands.GET_REPORT,
            arg1=0x00,
            arg2=0x00
        )
    
    @staticmethod
    def parse_version(frame: Frame) -> tuple[str, str]:
        sw_val = frame.arg1
        sw_major = sw_val // 10
        sw_minor = sw_val % 10
        sw_version = f"v{sw_major}.{sw_minor}"
        
        if 32 <= frame.arg2 <= 126:
            hw_version = chr(frame.arg2)
        else:
            hw_version = f"0x{frame.arg2:02X}"
        
        return sw_version, hw_version
    
    @staticmethod
    def parse_shelf_bitmask(frame: Frame) -> int:
        return (frame.arg1 << 8) | frame.arg2
    
    @staticmethod
    def parse_distance(frame: Frame) -> int:
        return (frame.arg1 << 8) | frame.arg2
