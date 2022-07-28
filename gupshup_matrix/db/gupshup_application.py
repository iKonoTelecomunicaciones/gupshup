from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, List, Optional

import asyncpg
from attr import dataclass
from mautrix.types import RoomID, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class GupshupApplication:
    db: ClassVar[Database] = fake_db

    name: str
    admin_user: UserID
    app_id: str | None
    api_key: str | None
    phone_number: RoomID | None

    @property
    def _values(self):
        return (
            self.name,
            self.admin_user,
            self.app_id,
            self.api_key,
            self.phone_number,
        )

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> GupshupApplication:
        return cls(**row)

    @classmethod
    async def insert(
        cls, name: str, admin_user: str, app_id: str, api_key: str, phone_number: str
    ) -> None:
        q = "INSERT INTO gupshup_application (name, admin_user, app_id, api_key, phone_number) VALUES ($1, $2, $3, $4, $5)"
        await cls.db.execute(q, name, admin_user, app_id, api_key, phone_number)

    @classmethod
    async def update(
        cls, name: str, admin_user: str, app_id: str, api_key: str, phone_number: str
    ) -> None:
        q = "UPDATE gupshup_application SET name=$1, admin_user=$2, app_id=$3, api_key$=4, phone_number=$5 WHERE name=$1"
        await cls.db.execute(q, name, admin_user, app_id, api_key, phone_number)

    @classmethod
    async def get_by_name(cls, name: str) -> Optional["GupshupApplication"]:
        q = "SELECT name, admin_user, app_id, api_key, phone_number FROM gupshup_application WHERE name=$1"
        row = await cls.db.fetchrow(q, name)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_number(cls, number: str) -> Optional["GupshupApplication"]:
        q = "SELECT name, admin_user, app_id, api_key, phone_number FROM gupshup_application WHERE phone_number=$1"
        row = await cls.db.fetchrow(q, number)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_admin_user(cls, admin_user: str) -> Optional["GupshupApplication"]:
        q = "SELECT name, admin_user, app_id, api_key, phone_number FROM gupshup_application WHERE admin_user=$1"
        row = await cls.db.fetchrow(q, admin_user)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_all_gs_apps(cls) -> List[str]:
        q = "SELECT name, admin_user, app_id, api_key, phone_number FROM gupshup_application WHERE name IS NOT NULL"
        rows = await cls.db.fetch(q)
        if not rows:
            return []

        return [cls._from_row(gs_app).name for gs_app in rows]
