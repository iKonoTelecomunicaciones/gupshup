from typing import TYPE_CHECKING, Dict, Optional

from mautrix.bridge import CustomPuppetMixin
from mautrix.types import UserID
from mautrix.util.simple_template import SimpleTemplate

from .config import Config
from .db import Puppet as DBPuppet
from .gupshup import GupshupUserID

if TYPE_CHECKING:
    from .context import Context

try:
    import phonenumbers
except ImportError:
    phonenumbers = None

import logging

config: Config


class Puppet(CustomPuppetMixin):
    log: logging.Logger = logging.getLogger("mau.puppet")
    hs_domain: str
    gsid_template: SimpleTemplate[int] = SimpleTemplate("{number}", "number", type=int)
    mxid_template: SimpleTemplate[str]
    displayname_template: SimpleTemplate[str]

    by_gsid: Dict[GupshupUserID, "Puppet"] = {}

    gsid: GupshupUserID
    _formatted_number: Optional[str]

    _db_instance: Optional[DBPuppet]

    def __init__(
        self,
        gsid: GupshupUserID,
        is_registered: bool = False,
        db_instance: Optional[DBPuppet] = None,
    ) -> None:
        super().__init__()
        self.gsid = gsid
        self.is_registered = is_registered
        self._formatted_number = None
        self._db_instance = db_instance
        self.intent = self.az.intent.user(self.mxid)
        self.log = self.log.getChild(self.gsid)
        self.by_gsid[self.gsid] = self

    @property
    def phone_number(self) -> int:
        return self.gsid_template.parse(self.gsid)

    @property
    def formatted_phone_number(self) -> str:
        if not self._formatted_number and self.phone_number:
            parsed = phonenumbers.parse(f"+{self.phone_number}")
            fmt = phonenumbers.PhoneNumberFormat.INTERNATIONAL
            self._formatted_number = phonenumbers.format_number(parsed, fmt)
        return self._formatted_number

    @property
    def mxid(self) -> UserID:
        return UserID(self.mxid_template.format_full(str(self.phone_number)))

    @property
    def displayname(self) -> str:
        return self.displayname_template.format_full(str(self.formatted_phone_number))

    @property
    def db_instance(self) -> DBPuppet:
        if not self._db_instance:
            self._db_instance = DBPuppet(gsid=self.gsid, matrix_registered=self.is_registered)
        return self._db_instance

    @classmethod
    def from_db(cls, db_puppet: DBPuppet) -> "Puppet":
        return cls(
            gsid=db_puppet.gsid, is_registered=db_puppet.matrix_registered, db_instance=db_puppet
        )

    def save(self) -> None:
        self.db_instance.edit(matrix_registered=self.is_registered)

    async def get_displayname(self) -> str:
        return await self.intent.get_displayname(str(self.mxid))

    async def update_displayname(self, displayname: Optional[str] = None) -> None:
        displayname = (
            self.displayname_template.format_full(str(displayname))
            if displayname
            else str(self.gsid)
        )
        await self.intent.set_displayname(displayname)

    @classmethod
    def get_by_gsid(cls, gsid: GupshupUserID, create: bool = True) -> Optional["Puppet"]:
        try:
            return cls.by_gsid[gsid]
        except KeyError:
            pass

        db_puppet = DBPuppet.get_by_gsid(gsid)
        if db_puppet:
            return cls.from_db(db_puppet)

        if create:
            puppet = cls(gsid)
            puppet.db_instance.insert()
            return puppet

        return None

    @classmethod
    def get_by_mxid(cls, mxid: UserID, create: bool = True) -> Optional["Puppet"]:
        gsid = cls.get_gsid_from_mxid(mxid)
        if gsid:
            return cls.get_by_gsid(gsid, create)

        return None

    @classmethod
    def get_gsid_from_mxid(cls, mxid: UserID) -> Optional[GupshupUserID]:
        parsed = cls.mxid_template.parse(mxid)
        if parsed:
            return GupshupUserID(cls.gsid_template.format_full(parsed))
        return None

    @classmethod
    def get_mxid_from_gsid(cls, gsid: GupshupUserID) -> UserID:
        return UserID(cls.mxid_template.format_full(str(cls.gsid_template.parse(gsid))))


def init(context: "Context") -> None:
    global config
    Puppet.az, config, Puppet.loop = context.core
    Puppet.mx = context.mx
    Puppet.hs_domain = config["homeserver"]["domain"]
    Puppet.mxid_template = SimpleTemplate(
        config["bridge.username_template"],
        "userid",
        prefix="@",
        suffix=f":{Puppet.hs_domain}",
        type=str,
    )
    Puppet.displayname_template = SimpleTemplate(
        config["bridge.displayname_template"], "displayname", type=str
    )
