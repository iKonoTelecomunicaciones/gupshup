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
        self.cloud_url = config["gupshup.cloud_url"]
        self.is_cloud = config["gupshup.is_cloud"]
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
        additional_data: Optional[dict] = {},
    ) -> Dict[str, str]:
        """
        Send a message to a user.

        Parameters
        ----------
        data: dict
            The data with Gupshup needed to send the message, it contains the headers, the channel,
            the source, the destination and the app name.
        body: Optional[str]
            The text of the message or the name of the file if the message is a file.
        msgtype: Optional[str]
            The type of the message, it can be a text message, a file, an image, a video, etc.
        media: Optional[str]
            The url of the media if the message is a file, an image, a video, etc.
        is_gupshup_template: bool
            If the message is a Gupshup template or not.
        additional_data: Optional[dict]
            Contains the id of the message that the user is replying to.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        headers = data.get("headers")
        data.pop("headers")

        if body and msgtype is None and not is_gupshup_template:
            data["message"] = json.dumps(
                {
                    "isHSM": "false",
                    "type": "text",
                    "text": body,
                    "context": additional_data.get("context", {}),
                }
            )
        # If the message is a interactive message, the additional_data is a dict with the quick
        # replies or lists, otherwise additional_data has an id of a message that
        # the user is replying to
        elif msgtype == "m.interactive_message":
            data["message"] = json.dumps(additional_data)
        else:
            data["message"] = json.dumps(
                {
                    "isHSM": "true",
                    "type": "text",
                    "text": body,
                    "context": additional_data.get("context", {}),
                }
            )

        if media:
            if msgtype == MessageType.IMAGE:
                data["message"] = json.dumps(
                    {
                        "type": "image",
                        "originalUrl": media,
                        "previewUrl": media,
                        "context": additional_data.get("context", {}),
                    }
                )
            elif msgtype == MessageType.VIDEO:
                data["message"] = json.dumps(
                    {"type": "video", "url": media, "context": additional_data.get("context", {})}
                )
            elif msgtype == MessageType.AUDIO:
                data["message"] = json.dumps(
                    {"type": "audio", "url": media, "context": additional_data.get("context", {})}
                )
            elif msgtype == MessageType.FILE:
                data["message"] = json.dumps(
                    {
                        "type": "file",
                        "url": media,
                        "filename": body,
                        "context": additional_data.get("context", {}),
                    }
                )

        self.log.debug(f"Sending message {data}")

        try:
            if additional_data.get("context", {}) and self.is_cloud:
                resp = await self.http.post(self.cloud_url, data=data, headers=headers)
            else:
                resp = await self.http.post(self.base_url, data=data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(e)

        response_data = json.loads(await resp.text())
        return response_data

    async def send_location(
        self, data: dict, data_location: dict, additional_data: Optional[dict] = {}
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

        additional_data : Optional[dict]
            Contains the id of the message that the user is replying to, it is used only for
            replies.
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
                "context": additional_data.get("context", {}),
            }
        )
        self.log.debug(f"Sending location message: {data}")
        try:
            if additional_data and self.is_cloud:
                resp = await self.http.post(self.cloud_url, data=data, headers=headers)
            else:
                resp = await self.http.post(self.base_url, data=data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(e)
            return {"status": 400, "message": e}

        if resp.status not in (200, 201, 202):
            self.log.error(f"Error sending location message: {resp}")
            return {"status": resp.status, "message": "Error sending location message"}

        response_data = json.loads(await resp.text())
        return {"status": resp.status, "messageId": response_data.get("messageId")}
