from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

from mautrix.bridge import BaseUser
from mautrix.types import UserID

from . import puppet as pu
from .config import Config

if TYPE_CHECKING:
    from .__main__ import GupshupBridge

class User(BaseUser):
    by_mxid: Dict[UserID, "User"] = {}
    config: Config
    is_whitelisted: bool
    is_admin: bool

    def __init__(self, mxid: UserID) -> None:
        super().__init__()
        self.mxid = mxid
        self.by_mxid[self.mxid] = self
        self.command_status = None
        (
            self.relay_whitelisted,
            self.is_whitelisted,
            self.is_admin,
            self.permission_level,
        ) = self.config.get_permissions(mxid)
        self.log = self.log.getChild(self.mxid)

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop

    async def get_puppet(self) -> pu.Puppet | None:
        if not self.mxid:
            return None
        return await pu.Puppet.get_by_mxid(self.mxid)

    @classmethod
    def get_by_mxid(cls, mxid: UserID) -> Optional["User"]:
        if pu.Puppet.get_gsid_from_mxid(mxid) is not None or mxid == cls.az.bot_mxid:
            return None
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            return cls(mxid)
