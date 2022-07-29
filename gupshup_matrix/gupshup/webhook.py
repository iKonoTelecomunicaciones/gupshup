import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from .. import portal as po
from .. import user as u
from ..db.gupshup_application import GupshupApplication as DBGupshupApplication
from .data import (
    ChatInfo,
    GupshupApplication,
    GupshupEventType,
    GupshupMessageEvent,
    GupshupStatusEvent,
)


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
        """It takes a dictionary of data, and a class, and returns a tuple of the class and an error

        Parameters
        ----------
        data : Dict
            The data that was sent to the server.
        type_class : Any
            The class that will be used to deserialize the data.

        Returns
        -------
            The return value is a tuple of the deserialized class and an error.

        """
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
        """It receives a request from Gupshup, checks if the app is valid,
        and then calls the appropriate function to handle the event
        """
        data = dict(**await request.json())
        self.log.debug(f"The event arrives {data}")

        if not data.get("app") in await DBGupshupApplication.get_all_gs_apps():
            self.log.warning(
                f"Ignoring event because the gs_app [{data.get('app')}] is not registered."
            )
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
        """It takes a GupshupApplication object and a phone number as input and
        returns a chat ID as output

        Parameters
        ----------
        gs_app : GupshupApplication
            The Gupshup Application ID.
        number : str
            The phone number of the user.

        Returns
        -------
            A string

        """
        return f"{gs_app}-{number}"

    async def message_event(self, data: GupshupMessageEvent) -> web.Response:
        """It validates the incoming request, fetches the portal associated with the sender,
        and then passes the message to the portal for handling
        """
        self.log.debug(f"Received Gupshup message event: {data}")
        data, err = await self._validate_request(data, GupshupMessageEvent)
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal: po.Portal = await po.Portal.get_by_chat_id(
            self.generate_chat_id(gs_app=data.app, number=data.payload.sender.phone)
        )
        user: u.User = await u.User.get_by_gs_app(data.app)
        info = ChatInfo.deserialize(data.__dict__)
        info.sender = data.payload.sender
        await portal.handle_gupshup_message(user, info, data)
        return web.Response(status=204)

    async def status_event(self, data: GupshupStatusEvent) -> web.Response:
        """It receives a Gupshup status event, validates it, and then passes it to the portal to handle"""
        self.log.debug(f"Received Gupshup status event: {data}")
        data, err = await self._validate_request(data, GupshupStatusEvent)
        if err is not None:
            self.log.error(f"Error handling incoming message: {err}")
        portal: po.Portal = await po.Portal.get_by_chat_id(
            self.generate_chat_id(gs_app=data.app, number=data.payload.destination)
        )
        await portal.handle_gupshup_status(data.payload)
        return web.Response(status=204)
