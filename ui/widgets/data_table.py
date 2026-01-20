from textual.widgets import DataTable
from typing import List
from models.shelf_data import Shelf
from config.settings import SHELF_COUNT, POSITIONS_PER_SHELF

class ShelfDataTable(DataTable):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.shelves: List[Shelf] = [Shelf(i) for i in range(SHELF_COUNT)]
        self.row_keys = []
        self.border_title = "Stock"  
    
    def setup_columns(self):
        self.cursor_type = "row"
        self.add_column("Shelf", width=8, key="shelf_name")
        self.add_column("Avail", width=6, key="avail_status")
        
        for i in range(POSITIONS_PER_SHELF):
            self.add_column(f"{i}", width=4, key=str(i))
    
    def populate_rows(self):
        for shelf in self.shelves:
            row_data = [row.display_value for row in shelf.rows]
            row_key = self.add_row(shelf.label, shelf.status, *row_data)
            self.row_keys.append(row_key)
    
    def update_shelf(self, shelf_idx: int, shelf: Shelf):
        if shelf_idx >= len(self.row_keys):
            return
        
        row_key = self.row_keys[shelf_idx]
        self.update_cell(row_key, "shelf_name", shelf.label)
        self.update_cell(row_key, "avail_status", shelf.status)
        
        for col_idx, row in enumerate(shelf.rows):
            self.update_cell(row_key, str(col_idx), row.display_value)
