import asyncio
import json
import logging
import re

from aiohttp import ClientConnectorError, ClientSession, ContentTypeError, FormData
from mautrix.types import MessageType

from gupshup_matrix.gupshup.interactive_message import TemplateMessage

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
        self, message: dict, additional_data: dict | None = None
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

    def get_message_body(self, container_meta: dict, variables: list) -> str:
        """
        Get the message body from the container meta and variables.

        Parameters
        ----------
        container_meta: dict
            The container meta data from the Gupshup template.
        variables: list
            The variables that will be used in the template.

        Returns
        -------
        str
            The message body with the variables replaced.
        """
        if not container_meta or not container_meta.get("data"):
            return ""

        message_data = container_meta.get("data", "")

        if not variables or len(variables) == 0:
            return message_data

        # Get the variables of the template message, each variable is in the format {{name}} or
        # {{1}}
        message_variables = re.findall(r"{{[a-z0-9_]+}}", message_data)
        total_message_variables = len(message_variables)
        message = re.sub(r"{{[a-z0-9_]+}}", "{}", message_data)

        # If the template has variables, replace the variable and add it to the message
        try:
            message_data = message.format(*variables[:total_message_variables])
        except KeyError:
            pass

        return message_data

    def parse_template_components(self, template_gupshup_data: dict, variables: list) -> list[dict]:
        """
        Parse the components of the template and return a list of components.

        This is used to use our own template format, that is a list of components, instead of the
        Gupshup template format, this template format is like
        [
            {
                "type": "HEADER",
                "format": "TEXT",
                "text": "some text",
                "example": {"header_handle": ["https://example.com/image.jpg"]}
            },
            {
                "type": "BODY",
                "text": "some text with {{1}} variable",
                "example": {
                    "body_text_named_params": [
                        {
                            "param_name": "nombre",
                            "example": "John Doe"
                        }
                    ]
                }
            },
            {
                "type": "FOOTER",
                "text": "some footer text",
            },
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "quick_reply", "text": "{{2}}"},
                    {"type": "url", "text": "{{3}}", "url": "https://example.com"}
                ]
            }
        ]
        """
        if not template_gupshup_data:
            self.log.error("No template data found to parse with the template format")
            return []

        components = []
        try:
            container_meta = json.loads(template_gupshup_data.get("containerMeta"))
        except json.JSONDecodeError as e:
            self.log.error(f"Error decoding JSON from template data: {e}")
            return []

        if not container_meta:
            self.log.error("No containerMeta found in the template data")
            return []

        if container_meta.get("mediaUrl"):
            components.append({
                "type": "HEADER",
                "format": template_gupshup_data.get("templateType"),
                "example": {
                    "header_handle": [container_meta.get("mediaUrl")]
                }
            })

        if container_meta.get("header"):
            components.append({
                "type": "HEADER",
                "format": "TEXT",
                "text": container_meta.get("header"),
            })

        if container_meta.get("data"):
            message_data = self.get_message_body(container_meta, variables)

            components.append({
                "type": "BODY",
                "text": message_data,
            })

        if container_meta.get("footer"):
            components.append({
                "type": "FOOTER",
                "text": container_meta.get("footer"),
            })

        if container_meta.get("buttons"):
            components.append({
                "type": "BUTTONS",
                "buttons": container_meta.get("buttons", [])
            })

        if not components or len(components) == 0:
            self.log.error("No components found in the template data")
            return []

        return components

    async def send_message(
        self,
        data: dict,
        body: str | None = None,
        msgtype: str | None = None,
        media: str | None = None,
        file_name: str | None = None,
        additional_data: dict | None = None,
    ) -> dict[str, str]:
        """
        Send a message to a user.

        Parameters
        ----------
        data: dict
            The data with Gupshup needed to send the message, it contains the headers, the channel,
            the source, the destination and the app name.
        body: str | None
            The text of the message or the name of the file if the message is a file.
        msgtype: str | None
            The type of the message, it can be a text message, a file, an image, a video, etc.
        media: str | None
            The url of the media if the message is a file, an image, a video, etc.
        additional_data: dict | None
            Contains the id of the message that the user is replying to.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        if additional_data is None:
            additional_data = {}
        if file_name is None:
            file_name = ""

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
        self, data: dict, data_location: dict, additional_data: dict | None = None
    ) -> dict[str, str]:
        """
        Send a location to a user.

        Parameters
        ----------
        data : dict
            The data with Gupshup needed to send the message, it contains the headers, the channel,
            the source, the destination and the app name.

        data_location : dict
            Contains the location that will be sent to the user.

        additional_data : dict | None
            Contains the id of the message that the user is replying to, it is used only for
            replies.
        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        if additional_data is None:
            additional_data = {}

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
    ) -> list[dict]:
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
            return []

        response = await data.json()
        template_gupshup_data = response.get("template")

        if template_gupshup_data:
            template_data = self.parse_template_components(template_gupshup_data, variables)
            self.log.debug(f"Parsed template data with {len(template_data)} components")

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

        return template_data

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
        response_status: int
            The status code of the response.
        template_message: TemplateEvent
            The message that was sent to matrix.

        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        """
        headers = data.pop("headers")
        form_data = FormData()

        for key, value in data.items():
            form_data.add_field(key, str(value))

        template_data = await self.get_body_of_template(
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

        templateMessage = TemplateMessage(
            msgtype="m.template_message",
            template_message=template_data

        )

        return resp.status, response_data, templateMessage
