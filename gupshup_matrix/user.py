from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional

from mautrix.appservice import AppService
from mautrix.bridge import BaseUser
from mautrix.types import UserID

from . import portal as po
from . import puppet as pu
from .config import Config

if TYPE_CHECKING:
    from .__main__ import GupshupBridge


class User(BaseUser):
    by_mxid: Dict[UserID, "User"] = {}
    by_number: Dict[str, "User"] = {}
    config: Config
    az: AppService
    loop: asyncio.AbstractEventLoop
    bridge: "GupshupBridge"

    relay_whitelisted: bool
    is_admin: bool
    permission_level: str

    _is_logged_in: bool

    def __init__(
        self,
        mxid: UserID,
    ) -> None:
        self.mxid = mxid
        self.number = pu.Puppet.get_number_from_mxid(mxid)
        BaseUser.__init__(self)
        perms = self.config.get_permissions(mxid)
        self.relay_whitelisted, self.is_whitelisted, self.is_admin, self.permission_level = perms
        self._is_logged_in = True

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop

    async def get_portal_with(self, puppet: pu.Puppet, create: bool = True) -> po.Portal | None:
        return await po.Portal.get_by_chat_id(puppet.number, create=create)

    async def is_logged_in(self) -> bool:
        return True

    async def get_puppet(self) -> pu.Puppet | None:
        if not self.mxid:
            return None
        return await pu.Puppet.get_by_mxid(self.mxid)

    @classmethod
    async def get_by_mxid(cls, mxid: UserID) -> Optional["User"]:
        if await pu.Puppet.get_by_mxid(mxid) is not None or mxid == cls.az.bot_mxid:
            return None
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            return cls(mxid=mxid)

    @classmethod
    async def get_by_number(cls, number: UserID) -> Optional["User"]:
        if await pu.Puppet.get_by_number(number) is not None:
            return None
        try:
            return cls.by_number[number]
        except KeyError:
            return cls(number=number)
