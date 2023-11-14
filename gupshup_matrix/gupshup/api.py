import asyncio
import json
import logging
from typing import Dict, Optional

from aiohttp import ClientConnectorError, ClientSession
from mautrix.types import MessageType

from ..config import Config
from ..db import GupshupApplication as DBGupshupApplication
from .data import GupshupMessageID


class GupshupClient:
    log: logging.Logger = logging.getLogger("gupshup.out")
    http: ClientSession

    def __init__(self, config: Config, loop: asyncio.AbstractEventLoop) -> None:
        self.base_url = config["gupshup.base_url"]
        self.read_url = config["gupshup.read_url"]
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

    async def mark_read(self, message_id: GupshupMessageID, gupshup_app: DBGupshupApplication):
        """
        Send a request to gupshup to mark the message as read.

        Parameters
        ----------
        message_id : str
            The id of the message.
        header: dict
            The header to send to Gupshup.
        app_id: GupshupAccountID
            The id of the Gupshup account.

        Exceptions
        ----------
        ValueError:
            If the read event was not sent.
        """
        if not gupshup_app:
            self.log.error("No gupshup_app, ignoring read")
            return

        # Set the headers to send the read event to Gupshup
        header = {
            "apikey": gupshup_app.api_key,
            "Content-Type": "application/json",
        }

        self.log.debug(f"Marking message {message_id} as read")
        # Set the url to send the read event to Gupshup
        mark_read_url = self.read_url.format(appId=gupshup_app.app_id, msgId=message_id)

        # Send the read event to the Gupshup
        response = await self.http.put(url=mark_read_url, headers=header)

        if response.status not in (200, 202):
            self.log.error(f"Trying to mark the message {message_id} as read failed: {response}")
            raise ValueError("Try to mark the message as read failed")
        else:
            self.log.debug(f"Message {message_id} marked as read")

    async def send_location(
        self,
        data: dict,
        data_location: dict,
    ) -> Dict[str, str]:
        """
        Send a location to a user.

        Parameters
        ----------
        data : dict
            The data with Gupshup needed to send the message, it contains the headers, the channel,
            the source, the destination and the app name.

        data_location : dict
            Contains the location that will be sent to the user.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        headers = data.get("headers")
        data.pop("headers")
        # Get the latitude and longitude from the geo_uri
        location = data_location.get("geo_uri").split(":")[1].split(";")[0]
        latitude = location.split(",")[0]
        longitude = location.split(",")[1]

        data["message"] = json.dumps(
            {
                "type": "location",
                "latitude": latitude,
                "longitude": longitude,
                "name": "User Location",
                "address": location,
            }
        )
        self.log.debug(f"Sending location message: {data}")
        try:
            resp = await self.http.post(self.base_url, data=data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(e)
            return {"status": 400, "message": e}

        if resp.status not in (200, 201, 202):
            self.log.error(f"Error sending location message: {resp}")
            return {"status": resp.status, "message": "Error sending location message"}

        response_data = json.loads(await resp.text())
        return {"status": resp.status, "messageId": response_data.get("messageId")}
