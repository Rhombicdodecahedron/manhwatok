"""A row-cursor table with heading rows between its groups: the cursor steps over them."""

from __future__ import annotations

from textual.coordinate import Coordinate
from textual.widgets import DataTable


class HeadedTable(DataTable):
    """Rows whose key starts with `HEADING` are group labels. Up/down step over them, and
    `skip_headings` moves a cursor left on one to the nearest row that isn't."""

    HEADING = "heading:"

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        self.skip_headings(1)

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        self.skip_headings(-1)

    def row_key_at(self, row: int) -> str | None:
        return self.coordinate_to_cell_key(Coordinate(row, 0)).row_key.value

    def is_heading(self, row: int) -> bool:
        return (self.row_key_at(row) or "").startswith(self.HEADING)

    def skip_headings(self, step: int) -> None:
        """Move on from a heading in the direction of travel, or back the other way when there
        is nothing that way — a heading is a label, never a selection."""
        for way in (step, -step):
            row = self.cursor_row
            while 0 <= row < self.row_count and self.is_heading(row):
                row += way
            if 0 <= row < self.row_count:
                self.move_cursor(row=row)
                return

    @property
    def current_key(self) -> str | None:
        """The highlighted row's key, or None on a heading (or an empty table)."""
        if not self.row_count or self.is_heading(self.cursor_row):
            return None
        return self.row_key_at(self.cursor_row)
