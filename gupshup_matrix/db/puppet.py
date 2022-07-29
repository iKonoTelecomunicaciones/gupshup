from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import asyncpg
from attr import dataclass
from mautrix.types import SyncToken, UserID
from mautrix.util.async_db import Database
from yarl import URL

fake_db = Database.create("") if TYPE_CHECKING else None


@dataclass
class Puppet:
    db: ClassVar[Database] = fake_db

    phone: str
    name: str | None

    is_registered: bool

    custom_mxid: UserID | None
    access_token: str | None
    next_batch: SyncToken | None
    base_url: URL | None

    @property
    def _values(self):
        return (
            self.phone,
            self.name,
            self.is_registered,
            self.custom_mxid,
            self.access_token,
            self.next_batch,
            str(self.base_url) if self.base_url else None,
        )

    @classmethod
    def _from_row(cls, row: asyncpg.Record) -> Puppet:
        return cls(**row)

    async def insert(self) -> None:
        q = (
            "INSERT INTO puppet (phone, name, is_registered, custom_mxid, access_token, "
            "next_batch, base_url) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)"
        )
        await self.db.execute(q, *self._values)

    async def update(self) -> None:
        q = (
            "UPDATE puppet SET phone=$1, name=$2, is_registered=$3, custom_mxid=$4, "
            "access_token=$5, next_batch=$6, base_url=$7  WHERE phone=$1"
        )
        await self.db.execute(q, *self._values)

    @classmethod
    async def get_by_pk(cls, phone: str) -> Puppet | None:
        q = (
            "SELECT  phone, name, is_registered, custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE phone=$1"
        )
        row = await cls.db.fetchrow(q, phone)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_phone(cls, phone: str) -> Puppet | None:
        q = (
            "SELECT  phone, name, is_registered, custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE phone=$1"
        )
        row = await cls.db.fetchrow(q, phone)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def get_by_custom_mxid(cls, mxid: UserID) -> Puppet | None:
        q = (
            "SELECT  phone, name, is_registered, custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE custom_mxid=$1"
        )
        row = await cls.db.fetchrow(q, mxid)
        if not row:
            return None
        return cls._from_row(row)

    @classmethod
    async def all_with_custom_mxid(cls) -> list[Puppet]:
        q = (
            "SELECT  phone, name, is_registered, custom_mxid, access_token, next_batch, base_url "
            "FROM puppet WHERE custom_mxid IS NOT NULL"
        )
        rows = await cls.db.fetch(q)
        return [cls._from_row(row) for row in rows]
