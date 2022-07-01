from asyncpg import Connection
from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE portal (
        gsid     TEXT,
        mxid     TEXT,
    )"""
    )
    await conn.execute(
        """CREATE TABLE puppet (
        gsid                   TEXT PRIMARY KEY,
        matrix_registered      BOOLEAN
    )"""
    )
    await conn.execute(
        """CREATE TABLE message (
        mxid     TEXT NOT NULL,
        mx_room  TEXT NOT NULL,
        item_id  TEXT,
        receiver BIGINT,
        sender   BIGINT NOT NULL,
        PRIMARY KEY (item_id, receiver),
        UNIQUE (mxid, mx_room)
    )"""
    )
