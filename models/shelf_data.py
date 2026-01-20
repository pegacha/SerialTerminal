from dataclasses import dataclass, field
from typing import List
from config.settings import POSITIONS_PER_SHELF, ITEM_THICKNESS_MM

@dataclass
class ShelfRow:
    distance_mm: int
    
    @property
    def stock_count(self) -> int | None:
        if self.distance_mm == 0 or self.distance_mm >= 0xFFFE:
            return None
        return self.distance_mm // ITEM_THICKNESS_MM
    
    @property
    def display_value(self) -> str:
        count = self.stock_count
        if count is None:
            return "[dim]░[/dim]"
        else:
            return f"[yellow]{count}[/yellow]"
        

@dataclass
class Shelf:
    index: int
    available: bool = False
    rows: List[ShelfRow] = field(default_factory=lambda: [ShelfRow(0) for _ in range(POSITIONS_PER_SHELF)])
    
    @property
    def label(self) -> str:
        num = self.index + 1
        if self.available:
            return f"{num:02d}"
        return f"[dim]{num:02d}[/dim]"
    
    @property
    def status(self) -> str:
        return "[green]█[/green]" if self.available else "[dim]  [/dim]"
