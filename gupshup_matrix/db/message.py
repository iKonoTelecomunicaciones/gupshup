from typing import TYPE_CHECKING, Iterable, Optional

from mautrix.types import EventID, RoomID
from mautrix.util.db import Base
from sqlalchemy import Column, String, and_

if TYPE_CHECKING:
    from ..gupshup import GupshupMessageID, GupshupUserID


class Message(Base):
    __tablename__ = "message"

    mxid: EventID = Column(String(255))
    mx_room: RoomID = Column(String(255))
    gs_receiver: "GupshupUserID" = Column(String(127), primary_key=True)
    gsid: "GupshupMessageID" = Column(String(127), primary_key=True)

    @classmethod
    def get_all_by_gsid(
        cls, gsid: "GupshupMessageID", gs_receiver: "GupshupUserID"
    ) -> Iterable["Message"]:
        return cls._select_all(cls.c.gsid == gsid, cls.c.gs_receiver == gs_receiver)

    @classmethod
    def get_by_gsid(
        cls, gsid: "GupshupMessageID", gs_receiver: "GupshupUserID"
    ) -> Optional["Message"]:
        return cls._select_one_or_none(and_(cls.c.gsid == gsid, cls.c.gs_receiver == gs_receiver))

    @classmethod
    def get_by_mxid(cls, mxid: EventID, mx_room: RoomID) -> Optional["Message"]:
        return cls._select_one_or_none(and_(cls.c.mxid == mxid, cls.c.mx_room == mx_room))
