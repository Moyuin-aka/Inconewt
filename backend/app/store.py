from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from .models import WorldSnapshot


DEFAULT_WORLD_ID = "default"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorldStore:
    """多访客世界快照与槽位存档；旧单世界表会原样改名保留。"""

    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._migrate()

    def _table_columns(self, table: str) -> set[str]:
        return {str(row[1]) for row in self.connection.execute(f"PRAGMA table_info({table})")}

    def _table_exists(self, table: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone() is not None

    def _preserve_legacy_table(self, table: str) -> None:
        suffix = "legacy"
        index = 1
        while self._table_exists(f"{table}_{suffix}"):
            index += 1
            suffix = f"legacy_{index}"
        self.connection.execute(f"ALTER TABLE {table} RENAME TO {table}_{suffix}")

    def _migrate(self) -> None:
        with self._lock:
            if self._table_exists("world_state") and "world_id" not in self._table_columns("world_state"):
                self._preserve_legacy_table("world_state")
            if self._table_exists("saves") and "world_id" not in self._table_columns("saves"):
                self._preserve_legacy_table("saves")

            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS world_state (
                    world_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    started_at TEXT
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS saves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    world_id TEXT NOT NULL,
                    slot INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('auto', 'manual')),
                    created_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(world_id, kind, slot),
                    FOREIGN KEY(world_id) REFERENCES world_state(world_id) ON DELETE CASCADE
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_usage (
                    world_id TEXT NOT NULL,
                    day_key TEXT NOT NULL,
                    calls INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(world_id, day_key),
                    FOREIGN KEY(world_id) REFERENCES world_state(world_id) ON DELETE CASCADE
                )
                """
            )
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_world_last_seen ON world_state(last_seen_at)")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_saves_world ON saves(world_id, kind, slot)")
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.commit()

    def world_exists(self, world_id: str) -> bool:
        with self._lock:
            return self.connection.execute(
                "SELECT 1 FROM world_state WHERE world_id = ?", (world_id,)
            ).fetchone() is not None

    def create_world(self, world_id: str, world: WorldSnapshot, *, started: bool = False) -> None:
        now = utc_now()
        frozen = "1970-01-01T00:00:00+00:00"
        with self._lock:
            self.connection.execute(
                "INSERT INTO world_state (world_id, payload, created_at, last_seen_at, started_at) VALUES (?, ?, ?, ?, ?)",
                (world_id, world.model_dump_json(), now, frozen, now if started else None),
            )
            self.connection.commit()

    def load_current(self, world_id: str = DEFAULT_WORLD_ID) -> WorldSnapshot | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM world_state WHERE world_id = ?", (world_id,)
            ).fetchone()
        return WorldSnapshot.model_validate_json(row[0]) if row else None

    def save_current(self, world: WorldSnapshot, world_id: str = DEFAULT_WORLD_ID) -> None:
        now = utc_now()
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO world_state (world_id, payload, created_at, last_seen_at, started_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(world_id) DO UPDATE SET payload = excluded.payload
                """,
                (world_id, world.model_dump_json(), now, "1970-01-01T00:00:00+00:00", now),
            )
            self.connection.commit()

    def mark_started(self, world_id: str) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE world_state SET started_at = COALESCE(started_at, ?) WHERE world_id = ?",
                (utc_now(), world_id),
            )
            self.connection.commit()

    def touch_world(self, world_id: str, at: str | None = None) -> None:
        with self._lock:
            self.connection.execute(
                "UPDATE world_state SET last_seen_at = ? WHERE world_id = ?", (at or utc_now(), world_id)
            )
            self.connection.commit()

    def world_metadata(self, world_id: str) -> dict[str, str | bool] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT created_at, last_seen_at, started_at, payload FROM world_state WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        if not row:
            return None
        world = WorldSnapshot.model_validate_json(row["payload"])
        return {
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "started": row["started_at"] is not None,
            "player_name": world.player.name,
            "updated_at": world.updated_at,
        }

    def active_world_ids(self, active_seconds: int = 300, now: datetime | None = None) -> list[str]:
        threshold = (now or datetime.now(timezone.utc)) - timedelta(seconds=active_seconds)
        with self._lock:
            rows = self.connection.execute(
                "SELECT world_id FROM world_state WHERE last_seen_at >= ? ORDER BY last_seen_at DESC",
                (threshold.isoformat(),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def create_save(
        self,
        world: WorldSnapshot,
        slot: int = 1,
        kind: str = "manual",
        world_id: str = DEFAULT_WORLD_ID,
    ) -> int:
        if kind not in {"auto", "manual"} or (kind == "manual" and slot not in {1, 2, 3}) or (kind == "auto" and slot != 0):
            raise ValueError("无效的存档槽位")
        created_at = utc_now()
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO saves (world_id, slot, kind, created_at, schema_version, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(world_id, kind, slot) DO UPDATE SET
                    created_at = excluded.created_at,
                    schema_version = excluded.schema_version,
                    payload = excluded.payload
                """,
                (world_id, slot, kind, created_at, world.schema_version, world.model_dump_json()),
            )
            row = self.connection.execute(
                "SELECT id FROM saves WHERE world_id = ? AND kind = ? AND slot = ?",
                (world_id, kind, slot),
            ).fetchone()
            self.connection.commit()
        return int(row[0])

    def list_saves(self, world_id: str = DEFAULT_WORLD_ID) -> list[dict[str, int | str]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT id, slot, kind, created_at, schema_version, payload FROM saves WHERE world_id = ? ORDER BY kind, slot",
                (world_id,),
            ).fetchall()
        result: list[dict[str, int | str]] = []
        for row in rows:
            world = WorldSnapshot.model_validate_json(row["payload"])
            result.append({
                "id": int(row["id"]), "slot": int(row["slot"]), "kind": str(row["kind"]),
                "created_at": str(row["created_at"]), "schema_version": int(row["schema_version"]),
                "day": world.day, "minute": world.minute, "tick_index": world.tick_index,
            })
        return result

    def load_save(
        self, slot: int = 1, kind: str = "manual", world_id: str = DEFAULT_WORLD_ID
    ) -> WorldSnapshot | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM saves WHERE world_id = ? AND kind = ? AND slot = ?",
                (world_id, kind, slot),
            ).fetchone()
        return WorldSnapshot.model_validate(json.loads(row[0])) if row else None

    def load_latest_save(self, world_id: str = DEFAULT_WORLD_ID) -> WorldSnapshot | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT payload FROM saves WHERE world_id = ? ORDER BY created_at DESC LIMIT 1", (world_id,)
            ).fetchone()
        return WorldSnapshot.model_validate(json.loads(row[0])) if row else None

    def consume_ai_call(self, world_id: str, daily_limit: int, day_key: str | None = None) -> bool:
        if daily_limit <= 0:
            return False
        key = day_key or datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self.connection.execute(
                "SELECT calls FROM ai_usage WHERE world_id = ? AND day_key = ?", (world_id, key)
            ).fetchone()
            calls = int(row[0]) if row else 0
            if calls >= daily_limit:
                return False
            self.connection.execute(
                """
                INSERT INTO ai_usage (world_id, day_key, calls) VALUES (?, ?, 1)
                ON CONFLICT(world_id, day_key) DO UPDATE SET calls = calls + 1
                """,
                (world_id, key),
            )
            self.connection.commit()
        return True

    def ai_calls(self, world_id: str, day_key: str | None = None) -> int:
        key = day_key or datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            row = self.connection.execute(
                "SELECT calls FROM ai_usage WHERE world_id = ? AND day_key = ?", (world_id, key)
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_world(self, world_id: str) -> None:
        with self._lock:
            self.connection.execute("DELETE FROM world_state WHERE world_id = ?", (world_id,))
            self.connection.commit()

    def cleanup_stale(self, days: int = 30, now: datetime | None = None) -> int:
        threshold = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        with self._lock:
            cursor = self.connection.execute(
                """
                DELETE FROM world_state
                WHERE (started_at IS NOT NULL AND last_seen_at < ?)
                   OR (started_at IS NULL AND created_at < ?)
                """,
                (threshold.isoformat(), threshold.isoformat()),
            )
            self.connection.commit()
        return int(cursor.rowcount)

    def close(self) -> None:
        self.connection.close()
