from mautrix.bridge import Bridge

from . import __version__
from .config import Config
from .context import Context
from .db import init as init_db
from .gupshup import GupshupClient, GupshupHandler
from .matrix import MatrixHandler
from .portal import init as init_portal
from .puppet import init as init_puppet
from .sqlstatestore import SQLStateStore
from .user import init as init_user


class GupshupBridge(Bridge):
    name = "gupshup-matrix"
    module = "gupshup_matrix"
    command = "python -m gupshup-matrix"
    description = "A Matrix-Gupshup relaybot bridge."
    version = __version__
    config_class = Config
    matrix_class = MatrixHandler
    state_store_class = SQLStateStore

    config: Config
    gupshup: GupshupHandler
    gupshup_client: GupshupClient

    def prepare_bridge(self) -> None:
        init_db(self.db)
        self.gupshup_client = GupshupClient(config=self.config, loop=self.loop)
        context = Context(az=self.az, config=self.config, gsc=self.gupshup_client, loop=self.loop)
        context.mx = self.matrix = MatrixHandler(self.az, self.config, self.loop)
        context.gs = self.gupshup = GupshupHandler(context)
        init_user(context)
        init_portal(context)
        init_puppet(context)
        self.az.app.add_subapp(self.config["gupshup.webhook_path"], self.gupshup.app)


GupshupBridge().run()
