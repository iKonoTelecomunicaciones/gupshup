from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Iterable, Optional

import asyncpg
from attr import dataclass
from mautrix.types import EventID, RoomID, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Message:
    db: ClassVar[Database] = fake_db

    mxid: EventID
    mx_room: RoomID
    sender: UserID
    gsid: str
    gs_app: str

    @property
    def _values(self):
        return (
            self.mxid,
            self.mx_room,
            self.sender,
            self.gsid,
            self.gs_app,
        )

    async def insert(self) -> None:
        q = "INSERT INTO message (mxid, mx_room, sender, gsid, gs_app) VALUES ($1, $2, $3, $4, $5)"
        await self.db.execute(q, *self._values)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Optional["Message"]:
        return cls(**row)

    @classmethod
    async def delete_all(cls, room_id: RoomID) -> None:
        await cls.db.execute("DELETE FROM message WHERE mx_room=$1", room_id)

    @classmethod
    async def get_all_by_gsid(cls, gsid: str) -> Iterable["Message"]:
        q = "SELECT mxid, mx_room, sender, gsid, gs_app FROM message WHERE gsid=$1"
        rows = await cls.db.fetch(q, gsid)
        if not rows:
            return None
        return [cls._from_row(row) for row in rows]

    @classmethod
    async def get_by_gsid(cls, gsid: str) -> Optional["Message"]:
        q = "SELECT mxid, mx_room, sender, gsid, gs_app FROM message WHERE gsid=$1"
        row = await cls.db.fetchrow(q, gsid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Optional["Message"]:
        q = "SELECT mxid, mx_room, sender, gsid, gs_app FROM message WHERE mxid=$1 AND mx_room=$2"
        row = await cls.db.fetchrow(q, mxid, mx_room)
        if not row:
            return None
        return cls._from_row(row)
