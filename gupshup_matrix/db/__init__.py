from mautrix.bridge.db import RoomState, UserProfile
from sqlalchemy.engine.base import Engine

from .message import Message
from .portal import Portal
from .puppet import Puppet


def init(db_engine: Engine) -> None:
    for table in (UserProfile, RoomState, Puppet, Portal, Message):
        table.db = db_engine
        table.t = table.__table__
        table.c = table.t.c
        table.column_names = table.c.keys()
