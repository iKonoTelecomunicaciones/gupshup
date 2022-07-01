import asyncio
from html import escape
from string import Template
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from mautrix.appservice import IntentAPI
from mautrix.bridge import BasePortal
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
    StrippedStateEvent,
    TextMessageEventContent,
    UserID,
)

from . import puppet as p
from . import user as u
from .db import Message as DBMessage
from .db import Portal as DBPortal
from .formatter import matrix_to_whatsapp, whatsapp_reply_to_matrix, whatsapp_to_matrix
from .gupshup import (
    GupshupClient,
    GupshupMessageEvent,
    GupshupMessageID,
    GupshupMessageStatus,
    GupshupStatusEvent,
    GupshupUserID,
)

if TYPE_CHECKING:
    from .__main__ import GupshupBridge


InviteList = Union[UserID, List[UserID]]


class Portal(DBPortal, BasePortal):
    homeserver_address: str
    google_maps_url: str
    message_template: Template
    bridge_notices: bool
    federate_rooms: bool
    invite_users: List[UserID]
    initial_state: Dict[str, Dict[str, Any]]
    auto_change_room_name: bool
    error_codes: Dict[str, Dict[str, Any]]

    gsc: GupshupClient

    by_mxid: Dict[RoomID, "Portal"] = {}
    by_gsid: Dict[GupshupUserID, "Portal"] = {}

    gsid: GupshupUserID
    mxid: Optional[RoomID]

    _db_instance: DBPortal

    _main_intent: Optional[IntentAPI]
    _create_room_lock: asyncio.Lock
    _send_lock: asyncio.Lock

    def __init__(
        self,
        gsid: GupshupUserID,
        mxid: Optional[RoomID] = None,
    ) -> None:
        super().__init__()
        self.gsid = gsid
        self.mxid = mxid

        self._main_intent = None
        self._create_room_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self.log = self.log.getChild(self.gsid)

        self.by_gsid[self.gsid] = self
        if self.mxid:
            self.by_mxid[self.mxid] = self

    @property
    def main_intent(self) -> IntentAPI:
        if not self._main_intent:
            raise ValueError("Portal must be postinit()ed before main_intent can be used")
        return self._main_intent

    @classmethod
    def init_cls(cls, bridge: "GupshupBridge") -> None:
        cls.config = bridge.config
        cls.matrix = bridge.matrix
        cls.az = bridge.az
        cls.loop = bridge.loop
        cls.bridge = bridge
        cls.private_chat_portal_meta = cls.config["bridge.private_chat_portal_meta"]

    def send_text_message(self, message: GupshupMessageEvent) -> Optional["Portal"]:
        html, text = whatsapp_to_matrix(message)
        content = TextMessageEventContent(msgtype=MessageType.TEXT, body=text)
        if html is not None:
            content.format = Format.HTML
            content.formatted_body = html
        return self.main_intent.send_message(self.mxid, content)

    async def verify_displayname(self, contact_name) -> None:
        puppet = p.Puppet.get_by_gsid(self.gsid)
        client_displayname = await puppet.get_displayname()
        if client_displayname.isdigit():
            room_name = f"{contact_name} ({puppet.phone_number})"
            await self.main_intent.set_room_name(room_id=self.mxid, name=room_name)
        else:
            if self.auto_change_room_name:
                room_name = f"{contact_name} ({puppet.phone_number})"
                await self.main_intent.set_room_name(room_id=self.mxid, name=room_name)

        await puppet.update_displayname(contact_name)

    async def create_matrix_room(self, message: GupshupMessageEvent = None) -> RoomID:
        if self.mxid:
            return self.mxid
        async with self._create_room_lock:
            try:
                return await self._create_matrix_room(message)
            except Exception:
                self.log.exception("Failed to create portal")

    async def _create_matrix_room(self, message: GupshupMessageEvent = None) -> RoomID:
        self.log.debug("Creating Matrix room")
        puppet = p.Puppet.get_by_gsid(self.gsid)
        room_name = puppet.formatted_phone_number
        await puppet.update_displayname()
        creation_content = {"m.federate": self.federate_rooms}
        initial_state = {
            EventType.find(event_type): StrippedStateEvent.deserialize(
                {"type": event_type, "state_key": "", "content": content}
            )
            for event_type, content in self.initial_state.items()
        }
        if EventType.ROOM_POWER_LEVELS not in initial_state:
            initial_state[EventType.ROOM_POWER_LEVELS] = StrippedStateEvent(
                type=EventType.ROOM_POWER_LEVELS, content=PowerLevelStateEventContent()
            )
        plc = initial_state[EventType.ROOM_POWER_LEVELS].content
        plc.users[self.az.bot_mxid] = 100
        plc.users[self.main_intent.mxid] = 100
        for user_id in self.invite_users:
            plc.users.setdefault(user_id, 100)
        self.mxid = await self.main_intent.create_room(
            name=room_name,
            invitees=[self.az.bot_mxid, *self.invite_users],
            creation_content=creation_content,
            initial_state=list(initial_state.values()),
        )
        if not self.mxid:
            raise Exception("Failed to create room: no mxid received")
        self.save()
        self.log.debug(f"Matrix room created: {self.mxid}")
        self.by_mxid[self.mxid] = self
        await self.main_intent.join_room_by_id(self.mxid)
        return self.mxid

    async def handle_gupshup_message(self, message: GupshupMessageEvent) -> None:
        if not await self.create_matrix_room(message):
            return

        mxid = None
        msgtype = MessageType.TEXT

        if message.payload.sender.name:
            await self.verify_displayname(message.payload.sender.name)

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

            evt = DBMessage.get_by_gsid(gsid=mgs_id, gs_receiver=self.gsid)
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

        msg = DBMessage(
            mxid=mxid, mx_room=self.mxid, gs_receiver=self.gsid, gsid=message.payload.id
        )
        msg.insert()

    async def handle_gupshup_status(self, status: GupshupStatusEvent) -> None:
        if not self.mxid:
            return
        async with self._send_lock:
            msg = DBMessage.get_by_gsid(status.id, self.gsid)
            if status.type == GupshupMessageStatus.DELIVERED:
                msg = DBMessage.get_by_gsid(status.gsid, self.gsid)
                if msg:
                    await self.az.intent.mark_read(self.mxid, msg.mxid)
                else:
                    self.log.debug(f"Ignoring the null message")
            elif status.type == GupshupMessageStatus.READ:
                msg = DBMessage.get_by_gsid(status.gsid, self.gsid)
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
        async with self._send_lock:
            if message.msgtype == MessageType.TEXT or (
                message.msgtype == MessageType.NOTICE and self.bridge_notices
            ):
                localpart, _ = self.az.intent.parse_user_id(sender.mxid)

                if message.format == Format.HTML:
                    # only font styles from element
                    html = message.formatted_body
                else:
                    html = escape(message.body)
                    html = html.replace("\n", "<br />")

                if not is_gupshup_template:
                    # if it's not a gupshup template messages can be sent with displayname
                    displayname = await self.az.intent.get_room_displayname(self.mxid, sender.mxid)
                    html = self.message_template.safe_substitute(
                        message=html,
                        mxid=sender.mxid,
                        localpart=localpart,
                        displayname=displayname,
                    )

                text = matrix_to_whatsapp(html)

                if additional_data:
                    resp = await self.gsc.send_message(
                        self.gsid,
                        additional_data=additional_data,
                    )
                else:
                    resp = await self.gsc.send_message(
                        self.gsid,
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
                    self.gsid, media=url, body=message.body, msgtype=message.msgtype
                )
            elif message.msgtype == MessageType.LOCATION:
                resp = await self.gsc.send_location(
                    self.gsid, body=message.body, additional_data=additional_data
                )

            else:
                self.log.debug(f"Ignoring unknown message {message}")
                return
            self.log.debug(f"Gupshup send response: {resp}")
            DBMessage(
                mxid=event_id,
                mx_room=self.mxid,
                gs_receiver=self.gsid,
                gsid=GupshupMessageID(resp.get("messageId")),
            ).insert()

    @classmethod
    def get_by_mxid(cls, mxid: RoomID) -> Optional["Portal"]:
        try:
            return cls.by_mxid[mxid]
        except KeyError:
            pass

        db_portal = DBPortal.get_by_mxid(mxid)
        if db_portal:
            return cls.from_db(db_portal)

        return None

    @classmethod
    def get_by_gsid(cls, gsid: GupshupUserID, create: bool = True) -> Optional["Portal"]:
        try:
            return cls.by_gsid[gsid]
        except KeyError:
            pass

        db_portal = DBPortal.get_by_gsid(gsid)
        if db_portal:
            return cls.from_db(db_portal)

        if create:
            portal = cls(gsid=gsid)
            portal.db_instance.insert()
            return portal

        return None


# def init(context: "Context") -> None:
#     Portal.az, config, Portal.loop = context.core
#     Portal.gsc = context.gsc
#     Portal.homeserver_address = config["homeserver.public_address"]
#     Portal.google_maps_url = config["bridge.google_maps_url"]
#     Portal.message_template = Template(config["bridge.message_template"])
#     Portal.bridge_notices = config["bridge.bridge_notices"]
#     Portal.federate_rooms = config["bridge.federate_rooms"]
#     Portal.invite_users = config["bridge.invite_users"]
#     Portal.initial_state = config["bridge.initial_state"]
#     Portal.auto_change_room_name = config["bridge.auto_change_room_name"]
#     Portal.error_codes = config["gupshup.error_codes"]
