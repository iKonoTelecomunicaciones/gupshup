from mautrix.util.async_db import Database

from .message import Message
from .portal import Portal
from .puppet import Puppet
from .upgrade import upgrade_table


def init(db: Database) -> None:
    for table in (Puppet, Portal, Message):
        table.db = db


__all__ = ["upgrade_table", "Puppet", "Portal", "Message", "init"]
