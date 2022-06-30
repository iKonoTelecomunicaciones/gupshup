from typing import TYPE_CHECKING, Optional

from mautrix.types import RoomID
from mautrix.util.db import Base
from sqlalchemy import Column, String

if TYPE_CHECKING:
    from ..gupshup import GupshupUserID


class Portal(Base):
    __tablename__ = "portal"

    gsid: "GupshupUserID" = Column(String(127), primary_key=True)
    mxid: RoomID = Column(String(255), nullable=True)

    @classmethod
    def get_by_gsid(cls, gsid: "GupshupUserID") -> Optional["Portal"]:
        return cls._select_one_or_none(cls.c.gsid == gsid)

    @classmethod
    def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        return cls._select_one_or_none(cls.c.mxid == mxid)
