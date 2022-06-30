from typing import TYPE_CHECKING, Dict, Optional

from mautrix.bridge import BaseUser
from mautrix.types import UserID

from . import puppet as pu
from .config import Config

if TYPE_CHECKING:
    from .context import Context

config: Config


class User(BaseUser):
    by_mxid: Dict[UserID, "User"] = {}

    is_whitelisted: bool
    is_admin: bool

    def __init__(self, mxid: UserID) -> None:
        super().__init__()
        self.mxid = mxid
        self.by_mxid[self.mxid] = self
        self.command_status = None
        self.is_whitelisted, self.is_admin = config.get_permissions(self.mxid)
        self.log = self.log.getChild(self.mxid)

    @classmethod
    def get(cls, mxid: UserID) -> Optional["User"]:
        if pu.Puppet.get_gsid_from_mxid(mxid) is not None or mxid == cls.az.bot_mxid:
            return None
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            return cls(mxid)


def init(context: "Context") -> None:
    global config
    User.az, config, User.loop = context.core
