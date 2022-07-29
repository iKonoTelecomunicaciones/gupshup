from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from attr import dataclass
from mautrix.types import RoomID, UserID
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class User:
    db: ClassVar[Database] = fake_db

    mxid: UserID
    phone: str | None
    notice_room: RoomID | None

    async def insert(self) -> None:
        q = 'INSERT INTO "user" (mxid, phone, notice_room) VALUES ($1, $2, $3)'
        await self.db.execute(q, self.mxid, self.phone, self.notice_room)

    async def update(self) -> None:
        q = 'UPDATE "user" SET phone=$1, notice_room=$2 WHERE mxid=$3'
        await self.db.execute(q, self.phone, self.notice_room, self.mxid)

    @classmethod
    async def get_by_mxid(cls, mxid: UserID) -> User | None:
        q = 'SELECT mxid, phone, notice_room FROM "user" WHERE mxid=$1'
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def get_by_phone(cls, phone: str) -> User | None:
        q = 'SELECT mxid, phone, notice_room FROM "user" WHERE phone=$1'
        row = await cls.db.fetchrow(q, phone)
        if not row:
            return None
        return cls(**row)

    @classmethod
    async def all_logged_in(cls) -> list[User]:
        q = 'SELECT mxid, phone, notice_room FROM "user" WHERE phone IS NOT NULL'
        rows = await cls.db.fetch(q)
        return [cls(**row) for row in rows]
