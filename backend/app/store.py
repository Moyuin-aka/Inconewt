from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import WorldSnapshot


class WorldStore:
    """SQLite 只保存世界快照；MVP 阶段刻意避免过度拆表。"""

    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS world_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS saves (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self.connection.commit()

    def load_current(self) -> WorldSnapshot | None:
        row = self.connection.execute("SELECT payload FROM world_state WHERE id = 1").fetchone()
        return WorldSnapshot.model_validate_json(row[0]) if row else None

    def save_current(self, world: WorldSnapshot) -> None:
        payload = world.model_dump_json()
        self.connection.execute(
            "INSERT INTO world_state (id, payload) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
            (payload,),
        )
        self.connection.commit()

    def create_save(self, world: WorldSnapshot) -> int:
        cursor = self.connection.execute(
            "INSERT INTO saves (created_at, payload) VALUES (?, ?)",
            (world.updated_at, world.model_dump_json()),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def load_latest_save(self) -> WorldSnapshot | None:
        row = self.connection.execute("SELECT payload FROM saves ORDER BY id DESC LIMIT 1").fetchone()
        return WorldSnapshot.model_validate(json.loads(row[0])) if row else None

    def close(self) -> None:
        self.connection.close()
