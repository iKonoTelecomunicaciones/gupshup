from asyncpg import Connection
from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
    """CREATE TABLE portal (
        gsid     TEXT,
        mxid     TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE puppet (
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
