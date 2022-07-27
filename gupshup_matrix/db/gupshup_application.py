from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

import asyncpg
from attr import dataclass
from mautrix.types import RoomID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class GupshupApplication:
    db: ClassVar[Database] = fake_db

    name: str
    app_id: str | None
    phone_number: RoomID | None

    @property
    def _values(self):
        return (
            self.name,
            self.app_id,
            self.phone_number,
        )

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> GupshupApplication:
        return cls(**row)

    @classmethod
    async def insert(cls, name: str, app_id: str, phone_number: str) -> None:
        q = "INSERT INTO gupshup_application (name, app_id, phone_number) VALUES ($1, $2, $3)"
        await cls.db.execute(q, name, app_id, phone_number)

    @classmethod
    async def update(cls, name: str, app_id: str, phone_number: str) -> None:
        q = "UPDATE gupshup_application SET name=$1, app_id=$2, phone_number=$3 WHERE name=$1"
        await cls.db.execute(q, name, app_id, phone_number)

    @classmethod
    async def get_by_name(cls, name: str) -> Optional["GupshupApplication"]:
        q = "SELECT name, app_id, phone_number FROM gupshup_application WHERE name=$1"
        row = await cls.db.fetchrow(q, name)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_number(cls, number: str) -> Optional["GupshupApplication"]:
        q = "SELECT name, app_id, phone_number FROM gupshup_application WHERE phone_number=$1"
        row = await cls.db.fetchrow(q, number)
        if not row:
            return None
        return cls._from_row(row)
