import asyncio
import json
import logging
from typing import Dict, Optional

from aiohttp import ClientConnectorError, ClientSession
from mautrix.types import MessageType

from ..config import Config


class GupshupClient:
    log: logging.Logger = logging.getLogger("gupshup.out")
    http: ClientSession

    def __init__(self, config: Config, loop: asyncio.AbstractEventLoop) -> None:
        self.base_url = config["gupshup.base_url"]
        self.reaction_url = config["gupshup.reaction_url"]
        self.app_name = config["gupshup.app_name"]
        self.sender = config["gupshup.sender"]
        self.http = ClientSession(loop=loop)

    async def send_message(
        self,
        data: dict,
        body: Optional[str] = None,
        msgtype: Optional[str] = None,
        media: Optional[str] = None,
        is_gupshup_template: bool = False,
        additional_data: Optional[dict] = None,
    ) -> Dict[str, str]:
        headers = data.get("headers")
        data.pop("headers")

        if body and msgtype is None and not is_gupshup_template:
            data["message"] = json.dumps({"isHSM": "false", "type": "text", "text": body})
        elif additional_data:
            data["message"] = json.dumps(additional_data)
        else:
            data["message"] = json.dumps({"isHSM": "true", "type": "text", "text": body})

        if media:
            if msgtype == MessageType.IMAGE:
                data["message"] = json.dumps(
                    {"type": "image", "originalUrl": media, "previewUrl": media}
                )
            elif msgtype == MessageType.VIDEO:
                data["message"] = json.dumps({"type": "video", "url": media})
            elif msgtype == MessageType.AUDIO:
                data["message"] = json.dumps({"type": "audio", "url": media})
            elif msgtype == MessageType.FILE:
                data["message"] = json.dumps({"type": "file", "url": media, "filename": body})

        self.log.debug(f"Sending message {data}")

        try:
            resp = await self.http.post(self.base_url, data=data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(e)

        response_data = json.loads(await resp.text())
        return response_data

    async def send_reaction(self, message_id: str, emoji: str, type: str, data: dict):
        """
        Send a reaction to whatsapp

        Parameters
        ----------
        message_id: str
            The message ID of the reaction event
        emoji: str
            The emoji that was reacted with
        type: str
            The type of the reaction event
        """
        headers = data.get("headers")
        data.pop("headers")
        data["message"] = json.dumps({"msgId": message_id, "type": type, "emoji": emoji})

        self.log.critical(f"Sending reaction {data}")
        resp = await self.http.post(self.reaction_url, data=data, headers=headers)
        self.log.critical(f"Response from gupshup: status: {resp.status}: {resp}")
        response_data = json.loads(await resp.text())
        return response_data
