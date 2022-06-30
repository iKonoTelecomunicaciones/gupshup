from asyncio import AbstractEventLoop
from typing import TYPE_CHECKING, Optional, Tuple

from mautrix.appservice import AppService

from .config import Config

if TYPE_CHECKING:
    from .gupshup import GupshupClient, GupshupHandler
    from .matrix import MatrixHandler


class Context:
    az: AppService
    config: Config
    gsc: "GupshupClient"
    loop: AbstractEventLoop
    mx: Optional["MatrixHandler"]
    gs: Optional["GupshupHandler"]

    def __init__(
        self, az: AppService, config: Config, gsc: "GupshupClient", loop: AbstractEventLoop
    ) -> None:
        self.az = az
        self.config = config
        self.gsc = gsc
        self.loop = loop
        self.mx = None
        self.gs = None

    @property
    def core(self) -> Tuple[AppService, Config, AbstractEventLoop]:
        return self.az, self.config, self.loop
