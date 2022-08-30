from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, Optional, cast

from mautrix.appservice import AppService
from mautrix.bridge import BaseUser, async_getter_lock
from mautrix.types import RoomID, UserID

from . import portal as po
from . import puppet as pu
from .config import Config
from .db.user import User as DBUser

if TYPE_CHECKING:
    from .__main__ import GupshupBridge


class User(DBUser, BaseUser):
    by_mxid: Dict[UserID, "User"] = {}
    by_phone: Dict[str, "User"] = {}
    by_gs_app: Dict[str, "User"] = {}

    config: Config
    az: AppService
    loop: asyncio.AbstractEventLoop
    bridge: "GupshupBridge"

    relay_whitelisted: bool
    is_admin: bool
    permission_level: str

    _sync_lock: asyncio.Lock
    _notice_room_lock: asyncio.Lock
    _connected: bool

    def __init__(
        self,
        mxid: UserID,
        phone: str | None = None,
        gs_app: str | None = None,
        notice_room: RoomID | None = None,
    ) -> None:
        super().__init__(mxid=mxid, phone=phone, gs_app=gs_app, notice_room=notice_room)
        BaseUser.__init__(self)
        self._notice_room_lock = asyncio.Lock()
        self._sync_lock = asyncio.Lock()
        self._connected = False
        perms = self.config.get_permissions(mxid)
        self.relay_whitelisted, self.is_whitelisted, self.is_admin, self.permission_level = perms

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.bridge = bridge
        cls.config = bridge.config
        cls.az = bridge.az
        cls.loop = bridge.loop

    async def get_portal_with(self, puppet: pu.Puppet, create: bool = True) -> po.Portal | None:
        return await po.Portal.get_by_chat_id(puppet.phone, create=create)

    async def is_logged_in(self) -> bool:
        return bool(self.phone)

    async def get_puppet(self) -> pu.Puppet | None:
        if not self.mxid:
            return None
        return await pu.Puppet.get_by_mxid(self.mxid)

    def _add_to_cache(self) -> None:
        self.by_mxid[self.mxid] = self
        if self.phone:
            self.by_phone[self.phone] = self
        if self.gs_app:
            self.by_gs_app[self.gs_app] = self

    @classmethod
    async def get_by_mxid(cls, mxid: UserID, create: bool = True) -> Optional["User"]:
        if pu.Puppet.get_id_from_mxid(mxid):
            return None
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        user = cast(cls, await super().get_by_mxid(mxid))
        if user is not None:
            user._add_to_cache()
            return user

        if create:
            user = cls(mxid)
            await user.insert()
            user._add_to_cache()
            return user

        return None

    @classmethod
    @async_getter_lock
    async def get_by_phone(cls, phone: UserID) -> Optional["User"]:
        try:
            return cls.by_phone[phone]
        except KeyError:
            pass

        user = cast(cls, await super().get_by_phone(phone))
        if user is not None:
            user._add_to_cache()
            return user

        return None

    @classmethod
    @async_getter_lock
    async def get_by_gs_app(cls, gs_app: UserID) -> Optional["User"]:
        try:
            return cls.by_gs_app[gs_app]
        except KeyError:
            pass

        user = cast(cls, await super().get_by_gs_app(gs_app))
        if user is not None:
            user._add_to_cache()
            return user

        return None
