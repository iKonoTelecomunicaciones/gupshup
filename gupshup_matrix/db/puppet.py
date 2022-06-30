from typing import TYPE_CHECKING, Optional

from mautrix.util.db import Base
from sqlalchemy import Boolean, Column, String
from sqlalchemy.sql import expression

if TYPE_CHECKING:
    from ..gupshup import GupshupUserID


class Puppet(Base):
    __tablename__ = "puppet"

    gsid: "GupshupUserID" = Column(String(127), primary_key=True)
    matrix_registered: bool = Column(Boolean, nullable=False, server_default=expression.false())

    @classmethod
    def get_by_gsid(cls, gsid: "GupshupUserID") -> Optional["Puppet"]:
        return cls._select_one_or_none(cls.c.gsid == gsid)
