from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable

from aiohttp import web
from markdown import markdown
from mautrix.types import JSON, Format, MessageType, TextMessageEventContent, UserID

from gupshup_matrix.gupshup.data import ChatInfo

from .. import portal as po
from .. import puppet as pu
from .. import user as u
from ..db.gupshup_application import GupshupApplication
from ..gupshup.data import ChatInfo, GupshupMessageSender
from ..gupshup.interactive_message import InteractiveMessage
from ..util import normalize_number

logger = logging.getLogger()


class ProvisioningAPI:
    app: web.Application

    def __init__(self, shared_secret: str) -> None:
        self.app = web.Application()
        self.shared_secret = shared_secret
        self.app.router.add_options("/v1/register_app", self.login_options)
        self.app.router.add_options("/v1/update_app", self.login_options)
        self.app.router.add_options("/v1/template", self.login_options)
        self.app.router.add_options("/v1/interactive_message", self.login_options)
        self.app.router.add_post("/v1/register_app", self.register_app)
        self.app.router.add_patch("/v1/update_app", self.update_app)
        self.app.router.add_post("/v1/pm/{number}", self.start_pm)
        self.app.router.add_post("/v1/template", self.template)
        self.app.router.add_post("/v1/interactive_message", self.interactive_message)
        self.app.router.add_post("/v1/set_power_level", self.set_power_level)
        self.app.router.add_post("/v1/set_relay", self.set_relay)
        self.app.router.add_get("/v1/set_relay/{room_id}", self.validate_set_relay)

    @property
    def _acao_headers(self) -> dict[str, str]:
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS, PATCH",
        }

    @property
    def _headers(self) -> dict[str, str]:
        return {
            **self._acao_headers,
            "Content-Type": "application/json",
        }

    def _missing_key_error(self, err: KeyError) -> None:
        raise web.HTTPBadRequest(
            text=json.dumps({"error": f"Missing key {err}"}), headers=self._headers
        )

    async def login_options(self, _: web.Request) -> web.Response:
        return web.Response(status=200, headers=self._headers)

    async def _resolve_identifier(self, number: str) -> pu.Puppet:
        try:
            number = normalize_number(number).replace("+", "")
        except Exception as e:
            raise web.HTTPBadRequest(text=json.dumps({"error": str(e)}), headers=self._headers)

        puppet: pu.Puppet = await pu.Puppet.get_by_phone(number)

        return puppet

    def check_token(self, request: web.Request) -> Awaitable[u.User]:
        try:
            token = request.headers["Authorization"]
            token = token[len("Bearer ") :]
        except KeyError:
            raise web.HTTPBadRequest(
                text='{"error": "Missing Authorization header"}', headers=self._headers
            )
        except IndexError:
            raise web.HTTPBadRequest(
                text='{"error": "Malformed Authorization header"}', headers=self._headers
            )
        if token != self.shared_secret:
            raise web.HTTPForbidden(text='{"error": "Invalid token"}', headers=self._headers)
        try:
            user_id = request.query["user_id"]
        except KeyError:
            raise web.HTTPBadRequest(
                text='{"error": "Missing user_id query param"}', headers=self._headers
            )

        return u.User.get_by_mxid(UserID(user_id))

    async def register_app(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request)

        try:
            gs_app_name = data["gs_app_name"]
            gs_app_phone = data["gs_app_phone"]
            api_key = data["api_key"]
            app_id = data["app_id"]
        except KeyError as e:
            raise self._missing_key_error(e)
        if not gs_app_name:
            return web.json_response(
                data={"error": "gs_app_name not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )
        elif not gs_app_phone:
            return web.json_response(
                data={"error": "gs_app_phone not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )
        elif not api_key:
            return web.json_response(
                data={"error": "api_key not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )
        elif not app_id:
            return web.json_response(
                data={"error": "app_id not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )

        try:
            if await GupshupApplication.get_by_admin_user(admin_user=user.mxid):
                return web.json_response(
                    data={"error": "You already have a registered gs_app"},
                    status=422,
                    headers=self._acao_headers,
                )

            if await GupshupApplication.get_by_number(number=gs_app_phone):
                return web.json_response(
                    data={"error": f"This gs_app {gs_app_name} is already registered"},
                    status=422,
                    headers=self._acao_headers,
                )

            await GupshupApplication.insert(
                name=gs_app_name,
                admin_user=user.mxid,
                app_id=app_id,
                api_key=api_key,
                phone_number=gs_app_phone,
            )
            user.gs_app = gs_app_name
            user.phone = gs_app_phone
            await user.update()

        except Exception as e:
            return web.json_response(
                data={"error": e},
                status=422,
                headers=self._acao_headers,
            )

        return web.json_response(data={"detail": "Gupshup application has been created"})

    async def start_pm(self, request: web.Request) -> web.Response:
        user = await self.check_token(request)
        puppet = await self._resolve_identifier(request.match_info["number"])

        portal = await po.Portal.get_by_chat_id(
            chat_id=f"{user.gs_app}-{puppet.phone}", create=True
        )

        if portal.mxid:
            await portal.main_intent.invite_user(portal.mxid, user.mxid)
            just_created = False
        else:
            chat_info = {
                "app": f"{user.gs_app}-{puppet.phone}",
            }
            info = ChatInfo.deserialize(chat_info)
            chat_customer = {"phone": puppet.phone, "name": puppet.name or puppet.custom_mxid}
            customer = GupshupMessageSender.deserialize(chat_customer)
            info.sender = customer
            await portal.create_matrix_room(user, info)
            just_created = True
        return web.json_response(
            {
                "room_id": portal.mxid,
                "just_created": just_created,
                "chat_id": portal.chat_id,
                "other_user": {
                    "mxid": puppet.mxid,
                    "displayname": puppet.name,
                },
            },
            headers=self._acao_headers,
            status=201 if just_created else 200,
        )

    def replace_variables(self, template_message: str, variables: list) -> str:
        """
        Replace the variables in the template message with the values

        Parameters
        ----------
        template_message: str
            The template message that contains the variables
        variables: list
            The values of the variables

        Returns
        -------
        str
            The template message with the variables replaced
        """

        # Do a function that replaces the variables in the template message, asking if the template
        # message contain the next pattern: {{n}} and replace it by {n}
        message_pattern = re.compile(r"{{(\d+)}}")
        message = ""

        if re.findall(message_pattern, template_message):
            message = re.sub(message_pattern, r"{}", template_message)
        else:
            message = template_message

        # Replace the variables in the template message
        message = message.format(*variables)

        return message

    async def template(self, request: web.Request) -> web.Response:
        """Send a template message to a room

        Parameters
        ----------
        request: web.Request
            The request that contains the data of the template message and the user.

        Returns
        -------
            A dict with the status code a message and the id of the generated event.
        """
        user, data = await self._get_user(request)

        try:
            room_id = data["room_id"]
            template_message = data["template_message"]
            template_variables = data.get("variables") or []
            template_id = data.get("template_id")

        except KeyError as e:
            raise self._missing_key_error(e)

        if not room_id:
            return web.json_response(
                data={"error": "room_id not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )
        elif not template_message:
            return web.json_response(
                data={"error": "template_message not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )

        if template_variables:
            try:
                template_message = self.replace_variables(template_message, template_variables)
            except IndexError:
                return web.json_response(
                    data={"detail": "Not enough variables provided for the message template"},
                    status=400,
                    headers=self._acao_headers,
                )

        msg = TextMessageEventContent(body=template_message, msgtype=MessageType.TEXT)
        msg.trim_reply_fallback()

        portal: po.Portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return web.json_response(
                data={"error": f"Failed to get room {room_id}"},
                status=400,
                headers=self._acao_headers,
            )

        if template_id:
            msg_event_id = await portal.handle_matrix_template(
                sender=user,
                template_id=template_id,
                variables=template_variables,
            )
        else:
            msg_event_id = await portal.az.intent.send_message(portal.mxid, msg)
            await portal.handle_matrix_message(
                sender=user,
                message=msg,
                event_id=msg_event_id,
            )

        return web.json_response(
            data={"detail": "Template has been sent", "event_id": msg_event_id}
        )

    async def interactive_message(self, request: web.Request) -> web.Response:
        """
        QuickReplay:

        ```
        {
            "room_id": "!foo:foo.com",
            "interactive_message": {
                "type": "quick_reply",
                "content": {
                    "type": "text",
                    "header": "Hello, This is the header.\n\n",
                    "text": "Please select one of the following options",
                    "caption": "",
                    "filename": null,
                    "url": null
                },
                "options": [
                    {"type": "text", "title": "I agree", "description": null, "postbackText": null},
                    {"type": "text", "title": "No Accept", "description": null, "postbackText": null}
                ]
            }
        }
        ```


        ListReplay:

        ```
        {
            "room_id": "!foo:foo.com",
            "interactive_message": {
                "type": "list",
                "title": "Main title",
                "body": "Hello World",
                "msgid": "!foo:foo.com",
                "globalButtons": [{"type": "text", "title": "Open"}],
                "items": [
                    {
                        "title": "Section title",
                        "subtitle": "SubSection title",
                        "options": [
                            {
                                "type": "text",
                                "title": "Option 1",
                                "description": null,
                                "postbackText": "1"
                            },
                            {
                                "type": "text",
                                "title": "Option 2",
                                "description": null,
                                "postbackText": "2"
                            },
                            {
                                "type": "text",
                                "title": "Option 3",
                                "description": null,
                                "postbackText": "3"
                            },
                            {
                                "type": "text",
                                "title": "Option 4",
                                "description": null,
                                "postbackText": "4"
                            }
                        ]
                    }
                ]
            }
        }
        ```
        """
        user, data = await self._get_user(request)

        try:
            room_id = data["room_id"]
            interactive_message = data["interactive_message"]
        except KeyError as e:
            raise self._missing_key_error(e)

        if not room_id:
            return web.json_response(
                data={"error": "room_id not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )
        elif not interactive_message:
            return web.json_response(
                data={"error": "interactive_message not entered", "state": "missing-field"},
                status=400,
                headers=self._acao_headers,
            )

        interactive_message = InteractiveMessage.deserialize(interactive_message)

        msg = TextMessageEventContent(
            body=interactive_message.message,
            msgtype=MessageType.TEXT,
            formatted_body=markdown(interactive_message.message.replace("\n", "<br>")),
            format=Format.HTML,
        )

        msg.trim_reply_fallback()

        portal = await po.Portal.get_by_mxid(room_id)

        if not portal:
            return web.json_response(
                data={"error": f"Failed to get room {room_id}"},
                status=400,
                headers=self._acao_headers,
            )
        msg_event_id = await portal.az.intent.send_message(
            portal.mxid, msg
        )  # only be visible to the agent
        await portal.handle_matrix_message(
            sender=user,
            message=msg,
            event_id=msg_event_id,
            additional_data=interactive_message.serialize(),
        )

        return web.json_response(data={"detail_1": interactive_message.message})

    async def _get_user(self, request: web.Request, read_body: bool = True) -> tuple[u.User, JSON]:
        user = await self.check_token(request)

        if read_body:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                raise web.HTTPBadRequest(text='{"error": "Malformed JSON"}', headers=self._headers)
        else:
            data = None
        return user, data

    async def update_app(self, request: web.Request) -> dict:
        """
        Update the gupshup application

        Parameters
        ----------
        request: web.Request
            The request that contains the data of the app and the user.

        Returns
        -------
        JSON
            The response of the request with a success message or an error message
        """

        # Obtain the data from the request
        logger.debug("Updating gupshup_app")
        user, data = await self._get_user(request)

        if not data:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "data": None,
                            "message": f"The request does not have data",
                        }
                    }
                ),
                headers=self._headers,
            )

        # Separate the data from the request
        api_key = data.get("api_key", None)

        if not api_key:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "data": None,
                            "message": "The request does not have api_key",
                        }
                    }
                ),
                headers=self._headers,
            )

        # Check if the gupshup_app is registered
        gupshup_app: GupshupApplication = await GupshupApplication.get_by_admin_user(
            admin_user=user.mxid
        )

        if not gupshup_app:
            return web.HTTPUnprocessableEntity(
                text=json.dumps(
                    {
                        "detail": {
                            "data": None,
                            "message": f"""The gupshup application with user {user.mxid}
                                        is not registered""",
                        }
                    }
                ),
                headers=self._headers,
            )

        # Update the gupshup_app with the send values
        logger.debug(f"Update gupshup_app {gupshup_app.app_id} with user {user.mxid}")
        await gupshup_app.update_by_admin_user(mxid=user.mxid, api_key=api_key)

        return web.HTTPOk(
            text=json.dumps(
                {
                    "detail": {
                        "data": None,
                        "message": f"The gupshup_app {gupshup_app.app_id} has been updated",
                    }
                }
            ),
            headers=self._headers,
        )

    async def set_power_level(self, request: web.Request) -> web.Response:
        """
        Set the power level of a user in a room
        Parameters
        ----------
        request: web.Request
            The request that contains the data with the following fields:
                - power_level: int
                    The desired power level to set for the user.
                - room_id: str
                    The ID of the room where the power level should be set.
        Returns
        -------
        JSON
            The response of the request with a success message or an error message
        """
        user, data = await self._get_user(request)

        if not data:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "message": f"The request does not have data",
                        }
                    }
                ),
                headers=self._headers,
            )

        if not user:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "message": f"The request does not have the user",
                        }
                    }
                ),
                headers=self._headers,
            )

        try:
            power_level = data["power_level"]
            room_id = data["room_id"]
        except KeyError as e:
            raise self._missing_key_error(e)

        logger.debug(
            f"Set power level for room {room_id} and user {user.mxid} with power level {power_level}"
        )

        if power_level is None or power_level < 0 or not room_id:
            return web.json_response(
                data={
                    "detail": {"message": "The user_id or power_level or room_id was not provided"}
                },
                status=400,
                headers=self._acao_headers,
            )

        # Get the portal by room_id
        portal: po.Portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return web.json_response(
                data={"detail": {"message": f"Failed to get portal {room_id}"}},
                status=400,
                headers=self._acao_headers,
            )
        # Get the power level of the room
        try:
            power_levels = await portal.main_intent.get_power_levels(room_id)
        except Exception as e:
            logger.error(f"Error getting the power level: {e}")
            return web.json_response(
                data={
                    "detail": {
                        "message": f"Failed to get power level for room {room_id}. Error:{e}"
                    }
                },
                status=400,
                headers=self._acao_headers,
            )

        # Change the power level of the user
        power_levels.set_user_level(user.mxid, power_level)

        # Update the power level of the user in the room
        try:
            await portal.main_intent.set_power_levels(
                room_id=room_id,
                content=power_levels,
            )
        except Exception as e:
            logger.error(f"Error setting the power level for portal {room_id}. Error: {e}")
            return web.json_response(
                data={
                    "detail": {
                        "message": f"Failed to set power level for user {user.mxid} in portal {room_id}. Error:{e}"
                    }
                },
                status=400,
                headers=self._acao_headers,
            )

        logger.debug(f"Set power level for user {user.mxid} in portal {room_id}")
        return web.json_response(
            data={
                "detail": {
                    "message": f"Set power level for user {user.mxid} in portal {room_id} with power level {power_level} was successful"
                }
            },
            status=200,
            headers=self._acao_headers,
        )

    async def set_relay(self, request: web.Request) -> web.Response:
        """
        Set the relay of a user in a room
        Parameters
        ----------
        request: web.Request
            The request that contains the data of the company_app and the user.
        Returns
        -------
        JSON
            The response of the request with a success message or an error message
        """
        user, data = await self._get_user(request)

        if not data:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "message": f"The request does not have data",
                        }
                    }
                ),
                headers=self._headers,
            )

        if not user:
            return web.HTTPBadRequest(
                text=json.dumps(
                    {
                        "detail": {
                            "message": f"The request does not have the user",
                        }
                    }
                ),
                headers=self._headers,
            )

        try:
            room_id = data["room_id"]
        except KeyError as e:
            raise self._missing_key_error(e)

        logger.debug(f"Set relay for room {room_id}")
        if not room_id:
            logger.error("The room_id was not provided")
            return web.json_response(
                data={"detail": {"message": "The room_id was not provided"}},
                status=400,
                headers=self._acao_headers,
            )

        # Get the portal by room_id
        portal: po.Portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            logger.error(f"Portal {room_id} not found")
            return web.json_response(
                data={"detail": {"message": f"Failed to get portal {room_id}"}},
                status=400,
                headers=self._acao_headers,
            )

        # Set the relay of the puppet
        try:
            await portal.set_relay_user(user)
        except Exception as e:
            logger.error(f"Error setting the relay for portal {room_id}. Error: {e}")
            return web.json_response(
                data={
                    "detail": {
                        "message": f"Failed to set relay for user {user.mxid} in portal {room_id}. Error:{e}"
                    }
                },
                status=400,
                headers=self._acao_headers,
            )

        logger.debug(f"Set relay for user {portal.mxid} in portal {room_id}")
        return web.json_response(
            data={
                "detail": {
                    "message": f"Set relay for user {portal.mxid} in portal {room_id} was successful"
                }
            },
            status=200,
            headers=self._acao_headers,
        )

    async def validate_set_relay(self, request: web.Request) -> web.Response:
        """
        Validate if a specific room has a relay user set.
        Parameters
        ----------
        request: web.Request
            The request that contains the room_id in the path.
        Returns
        -------
        JSON
            The response of the request with a success message or an error message
        """
        logger.debug("Validate set relay")

        user, _ = await self._get_user(request, read_body=False)

        try:
            room_id = request.match_info["room_id"]
        except KeyError:
            return web.json_response(
                data={"detail": {"message": "The room_id was not provided in the path"}},
                status=400,
                headers=self._acao_headers,
            )

        # Get the portal by room_id
        portal: po.Portal = await po.Portal.get_by_mxid(room_id)

        if not portal:
            logger.error(f"Portal {room_id} not found")
            return web.json_response(
                data={
                    "detail": {
                        "message": f"Failed to get portal %(room_id)s",
                        "data": {"room_id": room_id},
                    },
                },
                status=400,
                headers=self._acao_headers,
            )

        if not portal.relay_user_id or portal.relay_user_id != user.mxid:
            logger.debug(f"Portal {room_id} does not have a relay user set")
            return web.json_response(
                data={
                    "detail": {
                        "message": f"Portal %(room_id)s does not have a relay user set for user %(user_id)s",
                        "data": {"room_id": room_id, "user_id": user.mxid},
                    },
                },
                status=400,
                headers=self._acao_headers,
            )

        return web.json_response(
            data={
                "detail": {
                    "message": f"Portal %(room_id)s has relay user %(relay_user_id)s set",
                    "data": {"room_id": room_id, "relay_user_id": user.mxid},
                },
            },
            status=200,
            headers=self._acao_headers,
        )