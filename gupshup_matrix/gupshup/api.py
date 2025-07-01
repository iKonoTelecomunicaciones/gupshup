import asyncio
import json
import logging
from typing import Dict, Optional

from aiohttp import ClientConnectorError, ClientSession, ContentTypeError, FormData
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
        self.template_url = config["gupshup.template_url"]
        self.get_template_url = config["gupshup.get_template_url"]
        self.app_name = config["gupshup.app_name"]
        self.sender = config["gupshup.sender"]
        self.http = ClientSession(loop=loop)

    def process_message_context(
        self, message: Dict, additional_data: Optional[Dict] = None
    ) -> str:
        """
        Format the message to be sent to Gupshup.

        Parameters
        ----------
        message: dict
            The dict with the message that will be sent to Gupshup.
        additional_data: dict
            Contains the id of the message that the user is replying to.

        Returns
        ----------
        str
            The formatted message.
        """
        if additional_data and additional_data.get("context"):
            message["context"] = additional_data.get("context")

        return json.dumps(message)

    async def send_message(
        self,
        data: Dict,
        body: Optional[str] = None,
        msgtype: Optional[str] = None,
        media: Optional[str] = None,
        file_name: Optional[str] = "",
        additional_data: Optional[Dict] = {},
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
        additional_data: Optional[dict]
            Contains the id of the message that the user is replying to.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        headers = data.pop("headers")

        # If the message is a interactive message, the additional_data is a dict with the quick
        # replies or lists, otherwise additional_data has an id of a message that
        # the user is replying to
        if msgtype == "m.interactive_message":
            data["message"] = json.dumps(additional_data)
        else:
            if body and msgtype == MessageType.TEXT:
                message_dict = {"type": "text", "text": body}

            if media:
                if msgtype == MessageType.IMAGE:
                    message_dict = {"type": "image", "originalUrl": media, "previewUrl": media}

                elif msgtype == MessageType.VIDEO:
                    message_dict = {"type": "video", "url": media}

                elif msgtype == MessageType.AUDIO:
                    message_dict = {"type": "audio", "url": media}

                elif msgtype == MessageType.FILE:
                    message_dict = {"type": "file", "url": media, "filename": file_name}

                if body:
                    message_dict["caption"] = body

            data["message"] = self.process_message_context(message_dict, additional_data)

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
        gupshup_app: DBGupshupApplication
             The gupshup application that will be used to send the read event.
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
        self, data: Dict, data_location: Dict, additional_data: Optional[Dict] = {}
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
        headers = data.pop("headers")

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
            resp = await self.http.post(self.base_url, data=data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(e)
            return {"status": 400, "message": e}

        if resp.status not in (200, 201, 202):
            self.log.error(f"Error sending location message: {resp}")
            return {"status": resp.status, "message": "Error sending location message"}

        response_data = json.loads(await resp.text())
        return {"status": resp.status, "messageId": response_data.get("messageId")}

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
        data: dict
            The necessary data to send the reaction
        """
        headers = data.pop("headers")
        data["message"] = json.dumps({"msgId": message_id, "type": type, "emoji": emoji})

        resp = await self.http.post(self.base_url, data=data, headers=headers)
        response_data = json.loads(await resp.text())
        return response_data

    async def get_body_of_template(
        self,
        app_id: str,
        template_id: str,
        variables: list,
        headers: dict,
        form_data: FormData,
    ) -> dict:
        """
        Get the template data from Gupshup.

        Parameters
        ----------
        app_id: str
            The id of the Gupshup application.
        template_id: str
            The id of the template that will be sent to the user.
        variables: list
            The variables that will be used in the template.
        headers: dict
            The headers to be used in the request.
        form_data: FormData | None
            The form data to be used in the request, if any.

        Returns
        -------
        data: dict
            The data of the template with the variables.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        url = self.get_template_url.format(appId=app_id, templateId=template_id)
        data = await self.http.get(url, headers=headers)

        if data.status not in (200, 201, 202):
            self.log.error(
                f"Error getting template {template_id}: {data.status} - {await data.text()}"
            )
            return {}

        response = await data.json()
        template_gupshup_data = response.get("template")

        form_data.add_field(
            "template",
            json.dumps(
                {
                    "id": template_id,
                    "params": variables,
                }
            ),
        )

        media_type = template_gupshup_data.get("templateType").lower()
        meta_data = json.loads(template_gupshup_data.get("containerMeta", "{}"))
        if media_type in ["image", "document", "video"]:
            form_data.add_field(
                "message",
                json.dumps(
                    {
                        "type": media_type,
                        media_type: {
                            "link": meta_data.get("mediaUrl"),
                        },
                    }
                ),
            )

    async def send_template(
        self, app_id: str, data: dict, template_id: str, variables: list
    ) -> dict:
        """
        Send a template to a user.

        Parameters
        ----------
        app_id: str
            The id of the Gupshup application.
        data: dict
            The data with Gupshup needed to send the message, it contains the headers, the channel,
            the source, the destination and the app name.
        template_id: str
            The id of the template that will be sent to the user.
        variables: list
            The variables that will be used in the template.

        Returns
        -------
        response_data: dict
            The response of the request to Gupshup.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        headers = data.pop("headers")
        form_data = FormData()
        for key, value in data.items():
            form_data.add_field(key, str(value))

        await self.get_body_of_template(
            app_id=app_id,
            template_id=template_id,
            variables=variables,
            headers=headers,
            form_data=form_data,
        )

        try:
            resp = await self.http.post(self.template_url, data=form_data, headers=headers)
        except ClientConnectorError as e:
            self.log.error(
                f"Error sending the template {template_id} to the user {data['destination']}: {e}"
            )
            return

        try:
            response_data = await resp.json()
        except (ValueError, ContentTypeError):
            response_read = await resp.read()
            response_data = json.loads(response_read)

        return resp.status, response_data
