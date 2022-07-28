import asyncio
import json
import logging
from typing import Dict, Optional

from aiohttp import ClientConnectorError, ClientSession
from mautrix.types import MessageType

from ..config import Config
from .data import GupshupUserID


class GupshupClient:
    log: logging.Logger = logging.getLogger("gupshup.out")
    http: ClientSession

    def __init__(self, config: Config, loop: asyncio.AbstractEventLoop) -> None:
        self.base_url = config["gupshup.base_url"]
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
