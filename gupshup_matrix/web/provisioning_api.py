from __future__ import annotations

import json
import logging
from typing import Awaitable

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

    async def template(self, request: web.Request) -> web.Response:
        user, data = await self._get_user(request)

        try:
            room_id = data["room_id"]
            template_message = data["template_message"]

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

        msg = TextMessageEventContent(body=template_message, msgtype=MessageType.TEXT)
        msg.trim_reply_fallback()

        portal: po.Portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return web.json_response(
                data={"error": f"Failed to get room {room_id}"},
                status=400,
                headers=self._acao_headers,
            )

        msg_event_id = await portal.az.intent.send_message(portal.mxid, msg)

        await portal.handle_matrix_message(
            sender=user,
            message=msg,
            event_id=msg_event_id,
            is_gupshup_template=True,
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
