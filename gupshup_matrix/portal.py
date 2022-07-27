from __future__ import annotations

import asyncio
from html import escape
from string import Template
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from mautrix.appservice import AppService, IntentAPI
from mautrix.bridge import BasePortal
from mautrix.errors import MatrixError
from mautrix.types import (
    EventID,
    EventType,
    FileInfo,
    Format,
    MediaMessageEventContent,
    MessageEventContent,
    MessageType,
    PowerLevelStateEventContent,
    RoomID,
    TextMessageEventContent,
    UserID,
)

from . import puppet as p
from . import user as u
from .db import GupshupApplication as DBGupshupApplication
from .db import Message as DBMessage
from .db import Portal as DBPortal
from .formatter import matrix_to_whatsapp, whatsapp_reply_to_matrix, whatsapp_to_matrix
from .gupshup import (
    GupshupApplication,
    GupshupClient,
    GupshupMessageEvent,
    GupshupMessageID,
    GupshupMessageStatus,
    GupshupStatusEvent,
)

if TYPE_CHECKING:
    from .__main__ import GupshupBridge

StateBridge = EventType.find("m.bridge", EventType.Class.STATE)
StateHalfShotBridge = EventType.find("uk.half-shot.bridge", EventType.Class.STATE)

InviteList = Union[UserID, List[UserID]]


class Portal(DBPortal, BasePortal):
    by_mxid: Dict[RoomID, "Portal"] = {}
    by_chat_id: Dict[RoomID, "Portal"] = {}
    by_chat_id: Dict[str, "Portal"] = {}

    homeserver_address: str
    google_maps_url: str
    message_template: Template
    bridge_notices: bool
    federate_rooms: bool
    invite_users: List[UserID]
    initial_state: Dict[str, Dict[str, Any]]
    auto_change_room_name: bool
    error_codes: Dict[str, Dict[str, Any]]

    az: AppService
    private_chat_portal_meta: bool
    gsc: GupshupClient

    _main_intent: Optional[IntentAPI] | None
    _create_room_lock: asyncio.Lock

    def __init__(
        self,
        chat_id: str,
        number: Optional[str] = None,
        mxid: Optional[RoomID] = None,
        relay_user_id: UserID | None = None,
    ) -> None:
        super().__init__(chat_id, number, mxid, relay_user_id)
        BasePortal.__init__(self)
        self._create_room_lock = asyncio.Lock()
        self.log = self.log.getChild(self.chat_id or self.number)
        self._main_intent = None
        self._relay_user = None

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be postinit()ed before main_intent can be used")
        return self._main_intent

    @property
    def is_direct(self) -> bool:
        return self.number is not None

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        BasePortal.bridge = bridge
        cls.private_chat_portal_meta = cls.config["bridge.private_chat_portal_meta"]

    def send_text_message(self, message: GupshupMessageEvent) -> Optional["Portal"]:
        html, text = whatsapp_to_matrix(message)
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
        if html is not None:
            content.format = Format.HTML
            content.formatted_body = html
        return self.main_intent.send_message(self.mxid, content)

    async def register_gs_app(self, gs_app: GupshupApplication):

        if await DBGupshupApplication.get_by_name(gs_app):
            return

        self.log.debug(f"Registering {gs_app} GupshupApplication")

        try:
            await DBGupshupApplication.insert(name=gs_app, app_id=None, phone_number=None)
        except Exception as e:
            self.log.exception(f"Error registering {gs_app} {e}")

    async def create_matrix_room(self, message: GupshupMessageEvent = None) -> RoomID:
        await self.register_gs_app(gs_app=message.app)
        if self.mxid:
            return self.mxid
        async with self._create_room_lock:
            try:
                self.number = message.payload.sender.phone
                return await self._create_matrix_room(message)
            except Exception:
                self.log.exception("Failed to create portal")

    async def _create_matrix_room(self, message: GupshupMessageEvent = None) -> RoomID:
        self.log.debug("Creating Matrix room")
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False
        power_levels = await self._get_power_levels(is_initial=True)
        initial_state = [
            {
                "type": str(StateBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
            # TODO remove this once https://github.com/matrix-org/matrix-doc/pull/2346 is in spec
            {
                "type": str(StateHalfShotBridge),
                "state_key": self.bridge_info_state_key,
                "content": self.bridge_info,
            },
            {
                "type": str(EventType.ROOM_POWER_LEVELS),
                "content": power_levels.serialize(),
            },
        ]
        invites = []
        creation_content = {}
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False
        self.mxid = await self.main_intent.create_room(
            name=f"{message.payload.sender.name} ({self.number})",
            is_direct=self.is_direct,
            initial_state=initial_state,
            invitees=invites,
            creation_content=creation_content,
            # Make sure the power level event in initial_state is allowed
            # even if the server sends a default power level event before it.
            # TODO remove this if the spec is changed to require servers to
            #      use the power level event in initial_state
            power_level_override={"users": {self.main_intent.mxid: 9001}},
        )
        if not self.mxid:
            raise Exception("Failed to create room: no mxid returned")

        self.log.debug(self.number)
        puppet: p.Puppet = await p.Puppet.get_by_number(self.number)
        await self.main_intent.invite_user(
            self.mxid, puppet.mxid, extra_content=self._get_invite_content(puppet)
        )
        if puppet:
            try:
                await puppet.intent.join_room_by_id(self.mxid)
            except MatrixError:
                self.log.debug(
                    "Failed to join custom puppet into newly created portal", exc_info=True
                )
        await self.update()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self
        return self.mxid

    def _get_invite_content(self, double_puppet: p.Puppet | None) -> dict[str, Any]:
        invite_content = {}
        if double_puppet:
            invite_content["fi.mau.will_auto_accept"] = True
        if self.is_direct:
            invite_content["is_direct"] = True
        return invite_content

    async def _get_power_levels(
        self, levels: PowerLevelStateEventContent | None = None, is_initial: bool = False
    ) -> PowerLevelStateEventContent:
        levels = levels or PowerLevelStateEventContent()
        levels.events_default = 0
        levels.ban = 99
        levels.kick = 99
        levels.invite = 99
        levels.state_default = 0
        meta_edit_level = 0
        levels.events[EventType.REACTION] = 0
        levels.events[EventType.ROOM_NAME] = meta_edit_level
        levels.events[EventType.ROOM_AVATAR] = meta_edit_level
        levels.events[EventType.ROOM_TOPIC] = meta_edit_level
        levels.events[EventType.ROOM_ENCRYPTION] = 50 if self.matrix.e2ee else 99
        levels.events[EventType.ROOM_TOMBSTONE] = 99
        levels.users_default = 0
        # Remote delete is only for your own messages
        levels.redact = 99
        if self.main_intent.mxid not in levels.users:
            levels.users[self.main_intent.mxid] = 9001 if is_initial else 100
        return levels

    @property
    def bridge_info_state_key(self) -> str:
        return f"com.github.gupshup://gupshup/{self.number}"

    @property
    def bridge_info(self) -> Dict[str, Any]:
        return {
            "bridgebot": self.az.bot_mxid,
            "creator": self.main_intent.mxid,
            "protocol": {
                "id": "facebook",
                "displayname": "Gupshup Bridge",
                "avatar_url": self.config["appservice.bot_avatar"],
            },
            "channel": {
                "id": str(self.number),
                "displayname": None,
                "avatar_url": None,
            },
        }

    async def delete(self) -> None:
        # if self.mxid:
        #     await DBMessage.delete_all_by_room(self.mxid)
        # self.by_fbid.pop(self.fbid_full, None)
        # self.by_mxid.pop(self.mxid, None)
        # await super().delete()
        pass

    async def get_dm_puppet(self) -> p.Puppet | None:
        if not self.is_direct:
            return None
        return await p.Puppet.get_by_number(self.number)

    async def save(self) -> None:
        # await self.update()
        pass

    async def handle_gupshup_message(self, message: GupshupMessageEvent) -> None:
        if not await self.create_matrix_room(message):
            return

        mxid = None
        msgtype = MessageType.TEXT

        if message.payload.body.url:
            resp = await self.az.http_session.get(message.payload.body.url)
            data = await resp.read()
            mxc = await self.main_intent.upload_media(data)

            if message.payload.type in ("image", "video"):
                msgtype = (
                    MessageType.IMAGE if message.payload.type == "image" else MessageType.VIDEO
                )
                msgbody = message.payload.body.caption if message.payload.body.caption else ""

                content_image = MediaMessageEventContent(
                    body="", msgtype=msgtype, url=mxc, info=FileInfo(size=len(data))
                )
                mxid = await self.main_intent.send_message(self.mxid, content_image)
                await self.send_text_message(msgbody)

            elif message.payload.type in ("audio", "file"):
                msgtype = (
                    MessageType.AUDIO if message.payload.type == "audio" else MessageType.FILE
                )
                msgbody = message.payload.body.caption if message.payload.body.caption else ""

                content = MediaMessageEventContent(
                    body=msgbody,
                    msgtype=msgtype,
                    url=mxc,
                    info=FileInfo(size=len(data)),
                )
                mxid = await self.main_intent.send_message(self.mxid, content)

            elif message.payload.type == "sticker":
                msgtype = MessageType.STICKER
                info = FileInfo(size=len(data))
                mxid = await self.main_intent.send_sticker(room_id=self.mxid, url=mxc, info=info)

        elif message.payload.type == "contact":

            for contact in message.payload.body.contacts:
                if contact:
                    message_data = ""
                    message_data += "<div><br />  *Contacto:* "
                    name = contact["name"]
                    phones = contact["phones"]
                    message_data += name["formatted_name"]
                    message_data += "<br />  *Número:*"
                    for phone in phones:
                        message_data += " " + phone["phone"]
                    message_data += "</div>"
                    mxid = await self.send_text_message(message_data)

        elif message.payload.type == "text" and not message.payload.context:
            mxid = await self.send_text_message(message.payload.body.text)

        elif message.payload.type in ["button_reply", "list_reply"]:
            if message.payload.type == "button_reply":
                # Separamos el contenido que llega de gupshup y obtenemos el último elemento
                # que contiene el número de la opción seleccionada
                body_parts = message.payload.body.reply_message.split()
                body = body_parts[-1]
            elif message.payload.type == "list_reply":
                body = message.payload.body.postback_text

            mxid = await self.send_text_message(body)

        # A esta opción se ingresa cuando es un mensaje que responde a un mensaje previo
        elif message.payload.context and message.payload.body.text:
            if message.payload.context.msg_gsId:
                mgs_id = message.payload.context.msg_gsId
            else:
                mgs_id = message.payload.context.msg_id

            body = message.payload.body.text

            evt = DBMessage.get_by_gsid(number=mgs_id, gs_receiver=self.number)
            if evt:
                content = await whatsapp_reply_to_matrix(body, evt, self.main_intent, self.log)
                content.external_url = content.external_url
                mxid = await self.main_intent.send_message(self.mxid, content)

        if message.payload.type == "location":
            text = ""
            location = self.google_maps_url.replace(
                "{latitude}", message.payload.body.latitude
            ).replace("{longitude}", message.payload.body.longitude)
            text += location
            mxid = await self.send_text_message(text)

        if not mxid:
            mxid = await self.main_intent.send_notice(self.mxid, "Contenido no aceptado")

        sender: UserID = p.Puppet.get_mxid_from_number(message.payload.sender.phone)

        msg = DBMessage(
            mxid=mxid,
            mx_room=self.mxid,
            sender=sender,
            receiver=self.relay_user_id,
            gsid=message.payload.id,
            gs_app=message.app,
        )
        await msg.insert()

    async def handle_gupshup_status(self, status: GupshupStatusEvent) -> None:
        if not self.mxid:
            return
        async with self._send_lock:
            msg = DBMessage.get_by_gsid(status.id, self.number)
            if status.type == GupshupMessageStatus.DELIVERED:
                msg = DBMessage.get_by_gsid(status.number, self.number)
                if msg:
                    await self.az.intent.mark_read(self.mxid, msg.mxid)
                else:
                    self.log.debug(f"Ignoring the null message")
            elif status.type == GupshupMessageStatus.READ:
                msg = DBMessage.get_by_gsid(status.number, self.number)
                if msg:
                    await self.main_intent.mark_read(self.mxid, msg.mxid)
                else:
                    self.log.debug(f"Ignoring the null message")
            elif status.type == GupshupMessageStatus.ENQUEUED:
                self.log.debug(f"Ignoring the enqueued message-event")
            elif status.type == GupshupMessageStatus.FAILED:
                reason_es = "<strong>Mensaje fallido, por favor intente nuevamente</strong>"
                if status.body.code in self.error_codes.keys():
                    reason_es = self.error_codes.get(status.body.code).get("reason_es")
                    reason_es = f"<strong>{reason_es}</strong>"
                if msg:
                    await self.az.intent.react(self.mxid, msg.mxid, "\u274c")
                await self.az.intent.send_notice(self.mxid, None, html=reason_es)

    async def handle_matrix_message(
        self,
        sender: "u.User",
        message: MessageEventContent,
        event_id: EventID,
        is_gupshup_template: bool = False,
        additional_data: Optional[dict] = None,
    ) -> None:
        orig_sender = sender
        sender, is_relay = await self.get_relay_sender(sender, f"message {event_id}")
        if is_relay:
            await self.apply_relay_message_format(orig_sender, message)

        if message.get_reply_to():
            await DBMessage.get_by_mxid(message.get_reply_to(), self.mxid)

        if message.msgtype in (MessageType.TEXT, MessageType.NOTICE):
            text = matrix_to_whatsapp(html)

            if message.format == Format.HTML:
                # only font styles from element
                html = message.formatted_body
            else:
                html = escape(message.body)
                html = html.replace("\n", "<br />")

            if additional_data:
                resp = await self.gsc.send_message(
                    self.number,
                    additional_data=additional_data,
                )
            else:
                resp = await self.gsc.send_message(
                    self.number,
                    body=text,
                    is_gupshup_template=is_gupshup_template,
                )

        elif message.msgtype in (
            MessageType.AUDIO,
            MessageType.VIDEO,
            MessageType.IMAGE,
            MessageType.FILE,
        ):
            url = f"{self.homeserver_address}/_matrix/media/r0/download/{message.url[6:]}"
            resp = await self.gsc.send_message(
                self.number, media=url, body=message.body, msgtype=message.msgtype
            )
        elif message.msgtype == MessageType.LOCATION:
            resp = await self.gsc.send_location(
                self.number, body=message.body, additional_data=additional_data
            )

        else:
            self.log.debug(f"Ignoring unknown message {message}")
            return
        self.log.debug(f"Gupshup send response: {resp}")

        receiver: UserID = p.Puppet.get_mxid_from_number(self.number)

        DBMessage(
            mxid=event_id,
            mx_room=self.mxid,
            sender=self.relay_user_id,
            receiver=receiver,
            gsid=GupshupMessageID(resp.get("messageId")),
            gs_app=GupshupApplication(resp.get("gs_app")),
        ).insert()

    async def postinit(self) -> None:
        self.by_chat_id[self.number] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self

        self._main_intent = (
            (await p.Puppet.get_by_number(self.number)).default_mxid_intent
            if self.is_direct
            else self.az.intent
        )

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        portal = cast(cls, await super().get_by_mxid(mxid))
        if portal:
            return portal

        return None

    @classmethod
    async def get_by_chat_id(cls, chat_id: str, create: bool = True) -> Optional["Portal"]:
        try:
            return cls.by_chat_id[chat_id]
        except KeyError:
            pass

        portal = cast(cls, await super().get_by_chat_id(chat_id))
        if portal:
            await portal.postinit()
            return portal

        if create:
            portal = cls(chat_id)
            await portal.insert()
            await portal.postinit()
            return portal

        return None
