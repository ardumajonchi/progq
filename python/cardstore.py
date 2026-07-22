# SPDX-FileCopyrightText: Copyright (C) Programma Q Emulator contributors
#
# SPDX-License-Identifier: MPL-2.0
"""Program card persistence on top of the arduino:dbstorage_sqlstore Brick. Every query that
carries a user-supplied value (a card title) goes through `execute_sql` with bound parameters --
never string-formatted into a WHERE clause -- since SQLStore's `read`/`update`/`delete` take a raw
SQL condition string with no parameter binding of their own.
"""

from __future__ import annotations

from arduino.app_bricks.dbstorage_sqlstore import SQLStore

from engine.cards import ProgramCard

_TABLE = "cards"
_COLUMNS = {
    "title": "TEXT PRIMARY KEY",
    "capacity": "INTEGER",
    "labels": "TEXT",
    "instructions": "TEXT",
}


class CardStore:
    def __init__(self, db_name: str) -> None:
        self.db = SQLStore(db_name)
        self.db.start()
        self.db.create_table(_TABLE, _COLUMNS)

    def list_titles(self) -> list[str]:
        rows = self.db.execute_sql(f"SELECT title FROM {_TABLE} ORDER BY title")
        return [row["title"] for row in (rows or [])]

    def load(self, title: str) -> ProgramCard | None:
        rows = self.db.execute_sql(f"SELECT * FROM {_TABLE} WHERE title = ?", (title,))
        if not rows:
            return None
        return ProgramCard.from_record(rows[0])

    def save(self, card: ProgramCard) -> None:
        record = card.to_record()
        self.db.execute_sql(f"DELETE FROM {_TABLE} WHERE title = ?", (card.title,))
        self.db.execute_sql(
            f"INSERT INTO {_TABLE} (title, capacity, labels, instructions) VALUES (?, ?, ?, ?)",
            (record["title"], record["capacity"], record["labels"], record["instructions"]),
        )

    def delete(self, title: str) -> None:
        self.db.execute_sql(f"DELETE FROM {_TABLE} WHERE title = ?", (title,))

    def stop(self) -> None:
        self.db.stop()
