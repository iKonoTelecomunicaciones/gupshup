import asyncio
from typing import Optional

from mautrix.appservice import AppService
from mautrix.bridge import BaseMatrixHandler
from mautrix.types import Event, MessageEvent, RoomID, StateEvent, UserID

# DON'T REMOVE COMMAND FROM THIS IMPORT, BRIDGE COMMANDS CAN FAIL
from . import commands
from . import portal as po
from . import puppet as pu
from . import user as u
from .config import Config


class MatrixHandler(BaseMatrixHandler):
    def __init__(
        self, az: AppService, config: Config, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> None:
        super(MatrixHandler, self).__init__(az, config, loop=loop)

    async def get_user(self, user_id: UserID) -> "u.User":
        return u.User.get(user_id)

    async def get_portal(self, room_id: RoomID) -> "po.Portal":
        return po.Portal.get_by_mxid(room_id)

    async def get_puppet(self, user_id: UserID) -> "pu.Puppet":
        return pu.Puppet.get_by_mxid(user_id)

    @staticmethod
    async def allow_bridging_message(user: "u.User", portal: "po.Portal") -> bool:
        return user.is_whitelisted

    def filter_matrix_event(self, evt: Event) -> bool:
        if not isinstance(evt, (MessageEvent, StateEvent)):
            return True
        return (
            evt.sender == self.az.bot_mxid or pu.Puppet.get_gsid_from_mxid(evt.sender) is not None
        )
