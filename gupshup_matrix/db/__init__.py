from mautrix.util.async_db import Database

from .gupshup_application import GupshupApplication
from .message import Message
from .portal import Portal
from .puppet import Puppet
from .upgrade import upgrade_table
from .user import User


def init(db: Database) -> None:
    for table in (Puppet, Portal, User, Message, GupshupApplication):
        table.db = db


__all__ = ["upgrade_table", "Puppet", "Portal", "Message", "GupshupApplication", "init"]
