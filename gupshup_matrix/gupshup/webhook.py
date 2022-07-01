import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from .. import portal as po
from ..config import Config
from .data import GupshupEventType, GupshupMessageEvent, GupshupStatusEvent


class GupshupHandler:
    log: logging.Logger = logging.getLogger("gupshup.in")
    app: web.Application

    def __init__(self, config: Config, loop: asyncio.AbstractEventLoop = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self.app = web.Application(loop=self.loop)
        self.app.router.add_route("POST", "/receive", self.receive)
        self.app_name = config["gupshup.app_name"]

    async def _validate_request(
        self, data: Dict, type_class: Any
    ) -> Tuple[Any, Optional[web.Response]]:
        cls = type_class.deserialize(data)
        err = None
        if cls.payload.type == "failed":
            err = {
                "destination": cls.payload.destination,
                "messageId": cls.payload.id,
                "error_code": cls.payload.body.code,
                "reason": cls.payload.body.reason,
            }
        return cls, err

    async def receive(self, request: web.Request) -> None:
        data = dict(**await request.json())
        if data.get("app") != self.app_name:
            self.log.debug(f"App name invalid.")
            return web.Response(status=406)
        elif data.get("type") == GupshupEventType.MESSAGE:
            return await self.message_event(data)
        elif data.get("type") == GupshupEventType.MESSAGE_EVENT:
            return await self.status_event(data)
        elif data.get("type") == GupshupEventType.USER_EVENT:
            # Ej: sandbox-start, opted-in, opted-out
            return web.Response(status=204)

        else:
            self.log.debug(f"Integration type not supported.")
            return web.Response(status=406)

    async def message_event(self, data: Dict) -> web.Response:
        self.log.debug(f"Received Gupshup message event: {data}")
        data, err = await self._validate_request(data, GupshupMessageEvent)
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal = po.Portal.get_by_gsid(data.payload.sender.phone)
        await portal.handle_gupshup_message(data)
        return web.Response(status=204)

    async def status_event(self, data: Dict) -> web.Response:
        self.log.debug(f"Received Gupshup status event: {data}")
        data, err = await self._validate_request(data, GupshupStatusEvent)
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal = po.Portal.get_by_gsid(data.payload.destination)
        await portal.handle_gupshup_status(data.payload)
        return web.Response(status=204)
