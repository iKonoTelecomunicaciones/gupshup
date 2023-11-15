from __future__ import annotations

import asyncio
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from markdown import markdown
from mautrix.appservice import AppService, IntentAPI
from mautrix.bridge import BasePortal
from mautrix.errors import MUnknown
from mautrix.types import (
    EventID,
    EventType,
    FileInfo,
    Format,
    MessageType,
    PowerLevelStateEventContent,
    RoomID,
    UserID,
)
from mautrix.types.event import (
    LocationMessageEventContent,
    MediaMessageEventContent,
    MessageEventContent,
    TextMessageEventContent,
)

from gupshup_matrix.formatter.from_matrix import matrix_to_whatsapp
from gupshup_matrix.gupshup.data import ChatInfo, GupshupPayload

from . import puppet as p
from . import user as u
from .db import GupshupApplication as DBGupshupApplication
from .db import Message as DBMessage
from .db import Portal as DBPortal
from .formatter import whatsapp_reply_to_matrix, whatsapp_to_matrix
from .gupshup import (
    GupshupClient,
    GupshupMessageEvent,
    GupshupMessageID,
    GupshupMessageStatus,
    InteractiveMessage,
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

    message_template: Template
    federate_rooms: bool
    invite_users: List[UserID]
    initial_state: Dict[str, Dict[str, Any]]
    auto_change_room_name: bool

    az: AppService
    private_chat_portal_meta: bool
    gsc: GupshupClient

    _main_intent: Optional[IntentAPI] | None
    _create_room_lock: asyncio.Lock
    _send_lock: asyncio.Lock

    gs_source: str
    gs_app: str

    def __init__(
        self,
        chat_id: str,
        phone: Optional[str] = None,
        mxid: Optional[RoomID] = None,
        relay_user_id: UserID | None = None,
    ) -> None:
        super().__init__(chat_id, phone, mxid, relay_user_id)
        BasePortal.__init__(self)
        self._create_room_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self.log = self.log.getChild(self.chat_id or self.phone)
        self._main_intent: IntentAPI = None
        self._relay_user = None
        self.error_codes = self.config["gupshup.error_codes"]
        self.homeserver_address = self.config["homeserver.public_address"]

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be postinit()ed before main_intent can be used")
        return self._main_intent

    @property
    async def main_data_gs(self) -> Dict:
        gs_app_name, _ = self.chat_id.split("-")
        try:
            gs_app = await DBGupshupApplication.get_by_name(name=gs_app_name)
        except Exception as e:
            self.log.exception(e)
            return

        self.gs_source = gs_app.phone_number
        self.gs_app = gs_app.name

        return {
            "channel": "whatsapp",
            "source": gs_app.phone_number,
            "destination": self.phone,
            "src.name": gs_app_name,
            "headers": {
                "Content-Type": "application/x-www-form-urlencoded",
                "apikey": gs_app.api_key,
            },
        }

    @property
    def is_direct(self) -> bool:
        return self.phone is not None

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        BasePortal.bridge = bridge
        cls.private_chat_portal_meta = cls.config["bridge.private_chat_portal_meta"]
        cls.gsc = bridge.gupshup_client

    def send_text_message(self, message: GupshupMessageEvent) -> Optional["Portal"]:
        html, text = whatsapp_to_matrix(message)
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
        if html is not None:
            content.format = Format.HTML
            content.formatted_body = html
        return self.main_intent.send_message(self.mxid, content)

    async def create_matrix_room(self, source: u.User, info: ChatInfo) -> RoomID:
        if self.mxid:
            return self.mxid
        async with self._create_room_lock:
            try:
                self.phone = info.sender.phone
                return await self._create_matrix_room(source=source, info=info)
            except Exception:
                self.log.exception("Failed to create portal")

    async def _create_matrix_room(self, source: u.User, info: ChatInfo) -> RoomID:
        self.log.debug("Creating Matrix room")
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

        invites = [self.az.intent.mxid]
        creation_content = {}
        if not self.config["bridge.federate_rooms"]:
            creation_content["m.federate"] = False

        room_name_template = self.config["bridge.room_name_template"].format(
            username=info.sender.name, phone=self.phone
        )
        self.mxid = await self.main_intent.create_room(
            name=room_name_template,
            is_direct=self.is_direct,
            initial_state=initial_state,
            invitees=invites,
            topic="WhatsApp private chat",
            creation_content=creation_content,
        )

        if not self.mxid:
            raise Exception("Failed to create room: no mxid returned")

        await self.update()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self

        puppet: p.Puppet = await p.Puppet.get_by_phone(self.phone)
        await puppet.update_info(info)

        await self.main_intent.invite_user(
            self.mxid, source.mxid, extra_content=self._get_invite_content(puppet)
        )

        return self.mxid

    async def handle_matrix_leave(self, user: u.User) -> None:
        if self.is_direct:
            self.log.info(f"{user.mxid} left private chat portal with {self.chat_id}")
            if f"{user.gs_app}-{user.phone}" == self.chat_id:
                self.log.info(
                    f"{user.mxid} was the recipient of this portal. Cleaning up and deleting..."
                )
                await self.cleanup_and_delete()
        else:
            self.log.debug(f"{user.mxid} left portal to {self.chat_id}")

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
        return f"com.github.gupshup://gupshup/{self.phone}"

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
                "id": str(self.phone),
                "displayname": None,
                "avatar_url": None,
            },
        }

    async def delete(self) -> None:
        await DBMessage.delete_all(self.mxid)
        self.by_mxid.pop(self.mxid, None)
        self.mxid = None
        await self.update()

    async def get_dm_puppet(self) -> p.Puppet | None:
        if not self.is_direct:
            return None
        return await p.Puppet.get_by_phone(self.phone)

    async def save(self) -> None:
        await self.update()

    async def handle_gupshup_message(
        self, source: u.User, info: ChatInfo, message: GupshupMessageEvent
    ) -> None:
        if not await self.create_matrix_room(source=source, info=info):
            return

        mxid = None
        msgtype = MessageType.TEXT

        if message.payload.body.url:
            resp = await self.az.http_session.get(message.payload.body.url)
            data = await resp.read()
            try:
                mxc = await self.main_intent.upload_media(data=data)
            except MUnknown as e:
                self.log.exception(f"{message} :: error {e}")
                return
            except Exception as e:
                self.log.exception(f"Message not receive :: error {e}")
                return

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
                if self.config["quick_reply.send_option_index"]:
                    # Separamos el contenido que llega de gupshup y obtenemos el último elemento
                    # que contiene el número de la opción seleccionada
                    body = message.payload.body.reply_message.split()[-1]
                else:
                    body = message.payload.body.title.lower()
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

            evt = await DBMessage.get_by_gsid(gsid=mgs_id)
            if evt:
                content = await whatsapp_reply_to_matrix(body, evt, self.main_intent, self.log)
                content.external_url = content.external_url
                mxid = await self.main_intent.send_message(self.mxid, content)

        if message.payload.type == "location":
            # Get the latitude and longitude
            latitude = float(message.payload.body.latitude)
            longitude = float(message.payload.body.longitude)

            # Set the location message content and send it to Gupshup
            # The geo_uri is the way to send a location in Matrix
            location_message = LocationMessageEventContent(
                msgtype=MessageType.LOCATION,
                body=f"{message.payload.body.name} {message.payload.body.address}",
                geo_uri=f"geo:{latitude},{longitude}",
            )
            # Send the message to Matrix
            self.log.debug(f"Sending location message {location_message} to {self.mxid}")
            mxid = await self.main_intent.send_message(room_id=self.mxid, content=location_message)

        if not mxid:
            mxid = await self.main_intent.send_notice(self.mxid, "Contenido no aceptado")

        puppet: p.Puppet = await self.get_dm_puppet()
        msg = DBMessage(
            mxid=mxid,
            mx_room=self.mxid,
            sender=puppet.mxid,
            gsid=message.payload.id,
            gs_app=message.app,
        )
        await msg.insert()
        asyncio.create_task(puppet.update_info(info))

    async def handle_matrix_join(self, user: u.User) -> None:
        if self.is_direct or not await user.is_logged_in():
            return

    async def handle_gupshup_status(self, status: GupshupPayload) -> None:
        if not self.mxid:
            return

        async with self._send_lock:
            msg = await DBMessage.get_by_gsid(status.gsid)
            if status.type == GupshupMessageStatus.DELIVERED:
                pass
            elif status.type == GupshupMessageStatus.READ:
                if msg:
                    await self.main_intent.mark_read(self.mxid, msg.mxid)
                else:
                    self.log.debug(f"Ignoring the null message")
            elif status.type == GupshupMessageStatus.ENQUEUED:
                self.log.debug(f"Ignoring the enqueued message-event")
            elif status.type == GupshupMessageStatus.FAILED:
                msg = await DBMessage.get_by_gsid(status.id)
                reason_es = "<strong>Mensaje fallido, por favor intente nuevamente</strong>"
                if status.body.code in self.error_codes.keys():
                    reason_es = self.error_codes.get(status.body.code).get("reason_es")
                    reason_es = f"<strong>{reason_es}</strong>"
                if msg:
                    await self.main_intent.react(self.mxid, msg.mxid, "\u274c")
                await self.main_intent.send_notice(self.mxid, None, html=reason_es)

    async def handle_matrix_message(
        self,
        sender: "u.User",
        message: MessageEventContent,
        event_id: EventID,
        is_gupshup_template: bool = False,
        additional_data: Optional[dict] = None,
    ) -> None:
        if message.msgtype == "m.interactive_message":
            interactive_message = message.get("interactive_message", {}).serialize()
            event_content: InteractiveMessage = InteractiveMessage.from_dict(
                data=interactive_message
            )
            await self.handle_interactive_message(
                sender=sender, interactive_message=event_content, event_id=event_id
            )
            return

        orig_sender = sender
        sender, is_relay = await self.get_relay_sender(sender, f"message {event_id}")
        if is_relay:
            await self.apply_relay_message_format(orig_sender, message)
        self.log.critical(f"message: {message}")
        self.log.critical(f"event_id: {event_id}")
        self.log.critical(f"message.get_reply_to(): {message.get_reply_to()}")
        if message.get_reply_to():
            reply_message = await DBMessage.get_by_mxid(message.get_reply_to(), self.mxid)
            if reply_message:
                additional_data = {
                    "context": {
                        "msgId": reply_message.gsid,
                    }
                }

        if message.msgtype == MessageType.NOTICE and not self.config["bridge.bridge_notices"]:
            return

        if message.msgtype in (MessageType.TEXT, MessageType.NOTICE):
            if message.format == Format.HTML:
                text = await matrix_to_whatsapp(message.formatted_body)
            else:
                text = text = message.body

            if additional_data:
                resp = await self.gsc.send_message(
                    data=await self.main_data_gs,
                    additional_data=additional_data,
                )
            else:
                resp = await self.gsc.send_message(
                    data=await self.main_data_gs,
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
                data=await self.main_data_gs, media=url, body=message.body, msgtype=message.msgtype
            )
        elif message.msgtype == MessageType.LOCATION:
            resp = await self.gsc.send_location(
                data=await self.main_data_gs, data_location=message
            )
            if resp.get("status", "") not in (200, 201, 202):
                self.log.error(f"Error sending location: {resp}")
                await self.main_intent.send_notice(
                    room_id=self.mxid,
                    html=f"<h4>{resp.get('message')}</h4>",
                )
                return
        else:
            self.log.debug(f"Ignoring unknown message {message}")
            return
        self.log.debug(f"Gupshup send response: {resp}")

        await DBMessage(
            mxid=event_id,
            mx_room=self.mxid,
            sender=self.gs_source,
            gsid=GupshupMessageID(resp.get("messageId")),
            gs_app=self.gs_app,
        ).insert()

    async def postinit(self) -> None:
        if self.mxid:
            self.by_mxid[self.mxid] = self

        if self.phone:
            self.by_mxid[self.phone] = self

        if self.is_direct:
            puppet = await self.get_dm_puppet()
            self._main_intent = puppet.default_mxid_intent
        elif not self.is_direct:
            self._main_intent = self.az.intent

    @classmethod
    async def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        portal = cast(cls, await super().get_by_mxid(mxid))
        if portal is not None:
            await portal.postinit()
            return portal

        return None

    @classmethod
    async def get_by_chat_id(cls, chat_id: str, create: bool = True) -> Optional["Portal"]:
        try:
            return cls.by_chat_id[chat_id]
        except KeyError:
            pass

        _, phone = chat_id.split("-")

        portal = cast(cls, await super().get_by_chat_id(chat_id))
        if portal:
            portal.phone = phone
            await portal.postinit()
            return portal

        if create:
            portal = cls(chat_id)
            portal.phone = phone
            await portal.insert()
            await portal.postinit()
            return portal

        return None

    async def handle_interactive_message(
        self, sender: u.User, interactive_message: InteractiveMessage, event_id: EventID
    ) -> None:
        msg = TextMessageEventContent(
            body=interactive_message.message,
            msgtype=MessageType.TEXT,
            formatted_body=markdown(interactive_message.message.replace("\n", "<br>")),
            format=Format.HTML,
        )
        msg.trim_reply_fallback()

        # Send message in matrix format
        await self.az.intent.send_message(self.mxid, msg)

        # Send message in whatsapp format
        resp = await self.gsc.send_message(
            data=await self.main_data_gs,
            additional_data=interactive_message.serialize(),
        )

        await DBMessage(
            mxid=event_id,
            mx_room=self.mxid,
            sender=self.gs_source,
            gsid=GupshupMessageID(resp.get("messageId")),
            gs_app=self.gs_app,
        ).insert()
