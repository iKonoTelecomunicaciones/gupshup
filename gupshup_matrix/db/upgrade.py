from asyncpg import Connection
from mautrix.util.async_db import UpgradeTable

upgrade_table = UpgradeTable()


@upgrade_table.register(description="Initial revision")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE portal (
        chat_id         TEXT PRIMARY KEY,
        phone           TEXT,
        mxid            TEXT,
        relay_user_id   TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE puppet (
        phone         TEXT PRIMARY KEY,
        name          TEXT,
        is_registered BOOLEAN NOT NULL DEFAULT false,
        custom_mxid   TEXT,
        access_token  TEXT,
        next_batch    TEXT,
        base_url      TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE "user" (
            mxid        TEXT PRIMARY KEY,
            phone       TEXT,
            gs_app      TEXT,
            notice_room TEXT
        )"""
    )
    await conn.execute(
        """CREATE TABLE message (
        mxid        TEXT NOT NULL,
        mx_room     TEXT NOT NULL,
        sender      TEXT NOT NULL,
        gsid        TEXT NOT NULL,
        gs_app      TEXT NOT NULL,
        PRIMARY KEY (mxid),
        UNIQUE (mxid, mx_room, gsid)
    )"""
    )
    await conn.execute(
        """CREATE TABLE gupshup_application (
        name            TEXT PRIMARY KEY,
        admin_user      TEXT,
        app_id          TEXT,
        api_key         TEXT,
        phone_number    TEXT
    )"""
    )
    await conn.execute(
        """CREATE TABLE reaction (
        event_mxid          VARCHAR(255) PRIMARY KEY,
        room_id             VARCHAR(255) NOT NULL,
        sender              VARCHAR(255) NOT NULL,
        gs_message_id     TEXT NOT NULL,
        reaction            VARCHAR(255),
        created_at          TIMESTAMP WITH TIME ZONE NOT NULL,
        UNIQUE (event_mxid, room_id)
        )"""
    )
    # The names of gupshup applications are unique to your platform.
    await conn.execute(
        "ALTER TABLE message ADD CONSTRAINT FK_gs_app FOREIGN KEY (gs_app) references gupshup_application (name)"
    )
    await conn.execute(
        """ALTER TABLE reaction ADD CONSTRAINT FK_message_gsid
        FOREIGN KEY (gs_message_id) references message (gsid)
        ON DELETE CASCADE"""
    )


@upgrade_table.register(description="Add field encrypted to portal table")
async def upgrade_v2(conn: Connection) -> None:
    await conn.execute("ALTER TABLE portal ADD COLUMN encrypted BOOLEAN DEFAULT false")
