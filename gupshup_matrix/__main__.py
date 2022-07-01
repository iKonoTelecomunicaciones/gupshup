from mautrix.bridge import Bridge
from mautrix.types import RoomID, UserID

from . import __version__
from .config import Config
from .context import Context
from .db import init as init_db
from .db import upgrade_table
from .gupshup import GupshupClient, GupshupHandler
from .matrix import MatrixHandler
from .portal import Portal
from .puppet import Puppet
from .user import User


class GupshupBridge(Bridge):
    name = "gupshup-matrix"
    module = "gupshup_matrix"
    command = "python -m gupshup-matrix"
    description = "A Matrix-Gupshup relaybot bridge."
    repo_url = "https://github.com/bramenn/gupshup"
    version = __version__
    config_class = Config
    matrix_class = MatrixHandler
    upgrade_table = upgrade_table

    config: Config
    gupshup: GupshupHandler
    gupshup_client: GupshupClient

    def preinit(self) -> None:
        super().preinit()

    def prepare_db(self) -> None:
        super().prepare_db()
        init_db(self.db)

    def prepare_bridge(self) -> None:
        super().prepare_bridge()
        self.gupshup_client = GupshupClient(config=self.config, loop=self.loop)
        self.az.app.add_subapp(self.config["gupshup.webhook_path"], self.gupshup.app)
        context = Context(az=self.az, config=self.config, gsc=self.gupshup_client, loop=self.loop)
        context.mx = self.matrix = MatrixHandler(self.az, self.config, self.loop)
        context.gs = self.gupshup = GupshupHandler(context)

    async def start(self) -> None:
        self.add_startup_actions(Puppet.init_cls(self))
        Portal.init_cls(self)
        await super().start()

    def prepare_stop(self) -> None:
        self.log.debug("Stopping puppet syncers")
        for puppet in Puppet.by_custom_mxid.values():
            puppet.stop()

    async def get_portal(self, room_id: RoomID) -> Portal:
        return await Portal.get_by_mxid(room_id)

    async def get_puppet(self, user_id: UserID, create: bool = False) -> Puppet:
        return await Puppet.get_by_mxid(user_id, create=create)

    async def get_double_puppet(self, user_id: UserID) -> Puppet:
        return await Puppet.get_by_custom_mxid(user_id)

    def is_bridge_ghost(self, user_id: UserID) -> bool:
        return bool(Puppet.get_id_from_mxid(user_id))


GupshupBridge().run()
