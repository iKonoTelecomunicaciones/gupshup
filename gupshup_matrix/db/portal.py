from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional

import asyncpg
from attr import dataclass
from mautrix.types import RoomID
from mautrix.util.async_db import Database

if TYPE_CHECKING:
    from ..gupshup import GupshupUserID

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Portal:
    db: ClassVar[Database] = fake_db

    gsid: "GupshupUserID"
    mxid: RoomID | None

    @property
    def _values(self):
        return (
            self.gsid,
            self.mxid,
        )

    async def insert(self) -> None:
        q = "INSERT INTO portal (gsid, mxid) VALUES ($1, $2)"
        await self.db.execute(q, *self._values)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Portal:
        return cls(**row)

    @classmethod
    async def get_by_gsid(cls, gsid: "GupshupUserID") -> Optional["Portal"]:
        q = "SELECT gsid, mxid FROM portal WHERE gsid=$1"
        row = await cls.db.fetchrow(q, gsid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        q = "SELECT gsid, mxid FROM portal WHERE mxid=$1"
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_with_room(cls) -> list[Portal]:
        q = "SELECT gsid, mxid FROM portal WHERE mxid IS NOT NULL"
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
