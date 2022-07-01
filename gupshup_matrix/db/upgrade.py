from asyncpg import Connection
from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute("DROP TABLE alembic_version")
    await conn.execute(
    """CREATE TABLE IF NOT EXISTS portal (
        gsid     TEXT,
        mxid     TEXT
    )"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet DROP CONSTRAINT gsid"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD PRIMARY KEY  pk"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD name TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD username TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD photo_id TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD photo_mxc TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD name_set BOOLEAN NOT NULL DEFAULT false"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD avatar_set BOOLEAN NOT NULL DEFAULT false"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD is_registered BOOLEAN NOT NULL DEFAULT false"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD custom_mxid TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD access_token TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD next_batch TEXT"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS puppet ADD base_url TEXT"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS puppet (
        pk            BIGINT PRIMARY KEY,
        gsid          TEXT NOT NULL,
        name          TEXT,
        username      TEXT,
        photo_id      TEXT,
        photo_mxc     TEXT,
        name_set      BOOLEAN NOT NULL DEFAULT false,
        avatar_set    BOOLEAN NOT NULL DEFAULT false,
        is_registered BOOLEAN NOT NULL DEFAULT false,
        custom_mxid   TEXT,
        access_token  TEXT,
        next_batch    TEXT,
        base_url      TEXT
    )"""
    )
    await conn.execute(
        """ALTER TABLE IF EXISTS message ADD sender TEXT"""
    )
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS message (
        mxid        TEXT NOT NULL,
        gsid        TEXT NOT NULL,
        mx_room     TEXT NOT NULL,
        gs_receiver TEXT NOT NULL,
        sender      TEXT NOT NULL,
        PRIMARY KEY (gsid, gs_receiver),
        UNIQUE (mxid, mx_room)
    )"""
    )
