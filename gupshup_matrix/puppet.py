from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator, AsyncIterable, Awaitable, Dict, Optional, cast

from mautrix.appservice import IntentAPI
from mautrix.bridge import BasePuppet, async_getter_lock
from mautrix.types import SyncToken, UserID
from mautrix.util.simple_template import SimpleTemplate
from yarl import URL

from . import portal as p
from .config import Config
from .db import Puppet as DBPuppet
from .gupshup.data import ChatInfo, GupshupMessageSender

try:
    import phonenumbers
except ImportError:
    phonenumbers = None

if TYPE_CHECKING:
    from .__main__ import GupshupBridge


class Puppet(DBPuppet, BasePuppet):
    by_phone: Dict[str, "Puppet"] = {}
    by_custom_mxid: dict[UserID, Puppet] = {}
    hs_domain: str
    mxid_template: SimpleTemplate[str]

    config: Config

    default_mxid_intent: IntentAPI
    default_mxid: UserID

    def __init__(
        self,
        phone: str | None,
        name: str | None = None,
        is_registered: bool = False,
        custom_mxid: UserID | None = None,
        access_token: str | None = None,
        next_batch: SyncToken | None = None,
        base_url: URL | None = None,
    ) -> None:
        super().__init__(
            phone=phone,
            name=name,
            is_registered=is_registered,
            custom_mxid=custom_mxid,
            access_token=access_token,
            next_batch=next_batch,
            base_url=base_url,
        )

        self.log = self.log.getChild(self.phone)

        self.default_mxid = self.get_mxid_from_phone(self.phone)
        self.custom_mxid = self.default_mxid
        self.default_mxid_intent = self.az.intent.user(self.default_mxid)

        self.intent = self._fresh_intent()

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> AsyncIterable[Awaitable[None]]:
        cls.config = bridge.config
        cls.loop = bridge.loop
        cls.mx = bridge.matrix
        cls.az = bridge.az
        cls.hs_domain = cls.config["homeserver.domain"]
        cls.mxid_template = SimpleTemplate(
            cls.config["bridge.username_template"],
            "userid",
            prefix="@",
            suffix=f":{cls.hs_domain}",
        )
        cls.sync_with_custom_puppets = cls.config["bridge.sync_with_custom_puppets"]

        cls.login_device_name = "Gupshup Bridge"
        return (puppet.try_start() async for puppet in cls.all_with_custom_mxid())

    def intent_for(self, portal: p.Portal) -> IntentAPI:
        if portal.phone == self.phone:
            return self.default_mxid_intent
        return self.intent

    def _add_to_cache(self) -> None:
        if self.phone:
            self.by_phone[self.phone] = self
        if self.custom_mxid:
            self.by_custom_mxid[self.custom_mxid] = self

    @property
    def mxid(self) -> UserID:
        return UserID(self.mxid_template.format_full(self.phone))

    async def save(self) -> None:
        await self.update()

    async def update_info(self, info: ChatInfo) -> None:
        update = False
        update = await self._update_name(info) or update
        if update:
            await self.update()

    @classmethod
    def _get_displayname(cls, info: ChatInfo) -> str:
        return cls.config["bridge.displayname_template"].format(
            displayname=info.sender.name, id=info.sender.name
        )

    async def _update_name(self, info: ChatInfo) -> bool:
        name = self._get_displayname(info)
        if name != self.name:
            self.name = name
            try:
                await self.default_mxid_intent.set_displayname(self.name)
                self.name_set = True
            except Exception:
                self.log.exception("Failed to update displayname")
                self.name_set = False
            return True
        return False

    @classmethod
    def get_mxid_from_phone(cls, phone: str) -> UserID:
        return UserID(cls.mxid_template.format_full(phone))

    async def get_displayname(self) -> str:
        return await self.intent.get_displayname(self.mxid)

    @classmethod
    @async_getter_lock
    async def get_by_phone(cls, phone: str, create: bool = True) -> Optional["Puppet"]:
        try:
            return cls.by_phone[phone]
        except KeyError:
            pass

        puppet = cast(cls, await super().get_by_phone(phone))
        if puppet is not None:
            puppet._add_to_cache()
            return puppet

        if create:
            puppet = cls(phone)
            await puppet.insert()
            puppet._add_to_cache()
            return puppet

        return None

    @classmethod
    def get_phone_from_mxid(cls, mxid: UserID) -> str | None:
        phone = cls.mxid_template.parse(mxid)
        if not phone:
            return None
        return phone

    @classmethod
    async def get_by_mxid(cls, mxid: UserID, create: bool = True) -> Optional["Puppet"]:
        phone = cls.get_phone_from_mxid(mxid)
        if phone:
            return await cls.get_by_phone(phone, create)
        return None

    @classmethod
    @async_getter_lock
    async def get_by_custom_mxid(cls, mxid: UserID) -> "Puppet" | None:
        try:
            return cls.by_custom_mxid[mxid]
        except KeyError:
            pass

        puppet = cast(cls, await super().get_by_custom_mxid(mxid))
        if puppet:
            puppet._add_to_cache()
            return puppet

        return None

    @classmethod
    def get_id_from_mxid(cls, mxid: UserID) -> int | None:
        return cls.mxid_template.parse(mxid)

    @classmethod
    def get_mxid_from_phone(cls, phone: str) -> UserID:
        return UserID(cls.mxid_template.format_full(phone))

    @classmethod
    async def all_with_custom_mxid(cls) -> AsyncGenerator["Puppet", None]:
        puppets = await super().all_with_custom_mxid()
        puppet: cls
        for index, puppet in enumerate(puppets):
            try:
                yield cls.by_phone[puppet.phone]
            except KeyError:
                puppet._add_to_cache()
                yield puppet
