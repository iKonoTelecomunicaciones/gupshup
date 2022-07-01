from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import asyncpg
from attr import dataclass
from mautrix.util.async_db import Database

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Puppet:
    db: ClassVar[Database] = fake_db

    gsid: str
    matrix_registered: bool | None

    @property
    def _values(self):
        return (self.gsid, self.matrix_registered)

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Puppet:
        return cls(**row)

    async def insert(self) -> None:
        q = "INSERT INTO puppet (gsid, matrix_registered VALUES ($1, $2)"
        await self.db.execute(q, *self._values)

    @classmethod
    async def get_by_gsid(cls, gsid: int) -> Puppet | None:
        q = "SELECT gsid, matrix_registered FROM puppet WHERE gsid=$1"
        row = await cls.db.fetchrow(q, gsid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_with_custom_mxid(cls) -> list[Puppet]:
        q = "SELECT gsid, matrix_registered FROM puppet WHERE gsid IS NOT NULL"
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
