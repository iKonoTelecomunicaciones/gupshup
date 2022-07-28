import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from .. import portal as po
from ..config import Config
from ..db.gupshup_application import GupshupApplication as DBGupshupApplication
from .data import GupshupApplication, GupshupEventType, GupshupMessageEvent, GupshupStatusEvent


class GupshupHandler:
    log: logging.Logger = logging.getLogger("gupshup.in")
    app: web.Application

    def __init__(self, loop: asyncio.AbstractEventLoop = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self.app = web.Application(loop=self.loop)
        self.app.router.add_route("POST", "/receive", self.receive)

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
        if not data.get("app") in await DBGupshupApplication.get_all_gs_apps():
            self.log.debug(f"App name invalid.")
            return web.Response(status=406)

        if data.get("type") == GupshupEventType.MESSAGE:
            return await self.message_event(data)
        elif data.get("type") == GupshupEventType.MESSAGE_EVENT:
            return await self.status_event(data)
        elif data.get("type") == GupshupEventType.USER_EVENT:
            # Ej: sandbox-start, opted-in, opted-out
            return web.Response(status=204)

        else:
            self.log.debug(f"Integration type not supported.")
            return web.Response(status=406)

    def generate_chat_id(self, gs_app: GupshupApplication, number: str) -> str:
        return f"{gs_app}-{number}"

    async def message_event(self, data: Dict) -> web.Response:
        self.log.debug(f"Received Gupshup message event: {data}")
        data, err = await self._validate_request(data, GupshupMessageEvent)
        data: GupshupMessageEvent = data
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal: po.Portal = await po.Portal.get_by_chat_id(
            self.generate_chat_id(gs_app=data.app, number=data.payload.sender.phone)
        )
        await portal.handle_gupshup_message(data)
        return web.Response(status=204)

    async def status_event(self, data: Dict) -> web.Response:
        self.log.debug(f"Received Gupshup status event: {data}")
        data, err = await self._validate_request(data, GupshupStatusEvent)
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal: po.Portal = await po.Portal.get_by_chat_id(data.payload.destination)
        await portal.handle_gupshup_status(data.payload)
        return web.Response(status=204)
