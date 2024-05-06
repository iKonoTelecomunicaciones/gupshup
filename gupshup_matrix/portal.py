from __future__ import annotations

import asyncio
from datetime import datetime
from string import Template
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from aiohttp import ClientConnectorError
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
    ReactionEventContent,
    RelatesTo,
    RelationType,
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
from .db import Reaction as DBReaction
from .formatter import _add_reply_header, whatsapp_reply_to_matrix, whatsapp_to_matrix
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

        for attempt in range(10):
            self.log.debug(f"Attempt {attempt} to set power levels to {source.mxid} logged user")
            response = await self.set_member_power_level(source.mxid, 100)
            if response:
                break
            await asyncio.sleep(1)
        await self.set_relay_user(source)

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
        default_power_levels = self.config["bridge.default_power_levels"]
        default_events_levels = self.config["bridge.default_events_levels"]
        default_user_level = self.config["bridge.default_user_level"]

        for key, value in default_power_levels.items():
            setattr(levels, key, value)

        for key, value in default_events_levels.items():
            levels.events[getattr(EventType, key)] = value

        if self.main_intent.mxid not in levels.users:
            levels.users[self.main_intent.mxid] = default_user_level if is_initial else 100

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
        """
        Send a message to element and create a room if it doesn't exist.

        Parameters
        ----------
        source: User
            The user who sent the reaction
        info: ChatInfo
            The information of the user who sent the message
        message: GupshupMessageEvent
            The content of the reaction event
        """
        if not await self.create_matrix_room(source=source, info=info):
            return

        mxid = None
        msgtype = MessageType.TEXT
        evt = None
        if message.payload.context:
            # Depending on where the message comes from, the id is different, if it comes from
            # Matrix, the id is a Gupshup id (it is happend because Gupshup use an id for the
            # message that does not come from Whatsapp Api Cloud),
            # otherwise is a Whatsapp Cloud id.
            if message.payload.context.msg_gsId:
                mgs_id = message.payload.context.msg_gsId
            else:
                mgs_id = message.payload.context.msg_id

            body = message.payload.body.text

            evt = await DBMessage.get_by_gsid(gsid=mgs_id)

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

                if evt:
                    await _add_reply_header(
                        content=content_image, msg=evt, main_intent=self.main_intent, log=self.log
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

                if evt:
                    await _add_reply_header(
                        content=content, msg=evt, main_intent=self.main_intent, log=self.log
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

        elif message.payload.type == "text":
            if evt:
                content = await whatsapp_reply_to_matrix(body, evt, self.main_intent, self.log)
                mxid = await self.main_intent.send_message(self.mxid, content)
            else:
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

            if evt:
                await _add_reply_header(
                    content=location_message, msg=evt, main_intent=self.main_intent, log=self.log
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
        try:
            await msg.insert()
        except Exception as e:
            self.log.error(f"Error saving message {msg}: {e}")

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

    async def handle_gupshup_reaction(self, sender: u.User, message: GupshupMessageEvent):
        """
        Send a reaction to element.

        Parameters
        ----------
        sender: User
            The user who sent the reaction
        message: GupshupMessageEvent
            The content with the reaction event
        """
        if not self.mxid:
            return

        data_reaction = message.payload.body
        msg_id = data_reaction.msg_gsId if data_reaction.msg_gsId else data_reaction.msg_id
        msg: DBMessage = await DBMessage.get_by_gsid(gsid=msg_id)
        if msg:
            message_with_reaction: DBReaction = await DBReaction.get_by_gs_message_id(
                msg.gsid, sender.mxid
            )

            if message_with_reaction:
                await DBReaction.delete_by_event_mxid(
                    message_with_reaction.event_mxid, self.mxid, sender.mxid
                )
                has_been_sent = await self.main_intent.redact(
                    self.mxid, message_with_reaction.event_mxid
                )
                if not data_reaction.emoji:
                    return

            try:
                has_been_sent = await self.main_intent.react(
                    self.mxid,
                    msg.mxid,
                    data_reaction.emoji,
                )
            except Exception as e:
                self.log.exception(f"Error sending reaction: {e}")
                await self.main_intent.send_notice(self.mxid, "Error sending reaction")
                return

        else:
            self.log.error(f"Message id not found, mid: {msg_id}")
            await self.main_intent.send_notice(self.mxid, "Error sending reaction")
            return

        await DBReaction(
            event_mxid=has_been_sent,
            room_id=self.mxid,
            sender=sender.mxid,
            gs_message_id=msg.gsid,
            reaction=data_reaction.emoji,
            created_at=datetime.now(),
        ).insert()

    async def handle_matrix_message(
        self,
        sender: "u.User",
        message: MessageEventContent,
        event_id: EventID,
        additional_data: Optional[dict] = {},
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

        gupshup_data = await self.main_data_gs
        if message.msgtype in (MessageType.TEXT, MessageType.NOTICE):
            if message.format == Format.HTML:
                text = await matrix_to_whatsapp(message.formatted_body)
            else:
                text = text = message.body

            resp = await self.gsc.send_message(
                data=gupshup_data,
                body=text,
                additional_data=additional_data,
            )

        elif message.msgtype in (
            MessageType.AUDIO,
            MessageType.VIDEO,
            MessageType.IMAGE,
            MessageType.FILE,
        ):
            url = f"{self.homeserver_address}/_matrix/media/r0/download/{message.url[6:]}"
            resp = await self.gsc.send_message(
                data=gupshup_data,
                media=url,
                body=message.body,
                msgtype=message.msgtype,
                additional_data=additional_data,
            )
        elif message.msgtype == MessageType.LOCATION:
            resp = await self.gsc.send_location(
                data=gupshup_data,
                data_location=message,
                additional_data=additional_data,
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
            msgtype="m.interactive_message",
        )

        await DBMessage(
            mxid=event_id,
            mx_room=self.mxid,
            sender=self.gs_source,
            gsid=GupshupMessageID(resp.get("messageId")),
            gs_app=self.gs_app,
        ).insert()

    async def handle_matrix_read_receipt(self, event_id: str) -> None:
        """
        Send a read event to Gupshup
        Params
        ----------
        event_id : str
            The id of the event.
        Exceptions
        ----------
        ClientConnectorError:
            Show and error if the connection fails.
        ValueError:
            Show and error if the read event is not sent.
        """
        puppet: p.Puppet = await p.Puppet.get_by_phone(self.phone, create=False)
        gupshup_app: DBGupshupApplication = await DBGupshupApplication.get_by_admin_user(
            self.relay_user_id
        )

        if not puppet:
            self.log.error("No puppet, ignoring read")
            return

        message: DBMessage = await DBMessage.get_by_mxid(event_id, self.mxid)
        if not message:
            self.log.error(f"No message with mxid: {event_id}, ignoring read")
            return

        # We send the read event to Gupshup
        try:
            await self.gsc.mark_read(message_id=message.gsid, gupshup_app=gupshup_app)
        except ClientConnectorError as error:
            self.log.error(f"Error sending the read event for event_id {event_id}: {error}")
            return
        except ValueError as error:
            self.log.error(f"Read event error for event_id {event_id}: {error}")
            return

    async def handle_matrix_reaction(
        self,
        user: u.User,
        message_mxid: str,
        event_id: EventID,
        room_id: RoomID,
        content: ReactionEventContent,
    ):
        """
        Send a reaction to whatsapp

        Parameters
        ----------
        user: User
            The user who sent the reaction
        message_mxid: str
            The message ID of the reaction event
        event_id: EventID
            The event ID of the reaction event
        room_id: RoomID
            The room ID of the room where the reaction was sent
        content: Dict
            The content of the reaction event
        """
        message: DBMessage = await DBMessage.get_by_mxid(message_mxid, room_id)

        if not message:
            self.log.error(f"Message {message_mxid} not found when handling reaction")
            await self.main_intent.send_notice(
                self.mxid, "We couldn't find the message to react to"
            )
            return

        reaction_value = content.relates_to.key
        message_with_reaction = await DBReaction.get_by_gs_message_id(message.gsid, user.mxid)
        data = await self.main_data_gs
        if message_with_reaction:
            await DBReaction.delete_by_event_mxid(
                message_with_reaction.event_mxid, self.mxid, user.mxid
            )
            await self.main_intent.redact(self.mxid, message_with_reaction.event_mxid)

        try:
            await self.gsc.send_reaction(
                message_id=message.gsid,
                emoji=reaction_value,
                type="reaction",
                data=data,
            )
        except ClientConnectorError as e:
            self.log.error(e)
            await self.main_intent.send_notice(f"Error sending reaction: {e}")
            return
        except TypeError as e:
            self.log.error(e)
            await self.main_intent.send_notice(f"Error sending reaction: {e}")
            return
        except Exception as e:
            self.log.error(f"Error sending reaction: {e}")
            await self.main_intent.send_notice(f"Error sending reaction: {e}")
            return

        await DBReaction(
            event_mxid=event_id,
            room_id=self.mxid,
            sender=user.mxid,
            gs_message_id=message.gsid,
            reaction=reaction_value,
            created_at=datetime.now(),
        ).insert()

    async def handle_matrix_redaction(
        self,
        user: u.User,
        event_id: EventID,
    ) -> None:
        """
        When a user of Matrix redaction to a message, this function takes it and sends it to Gupshup

        Parameters
        ----------
        user : User
            The user who sent the redaction

        event_id:
            The event_id of the reaction that was redacted
        """
        self.log.debug(f"Handling redaction for {event_id}")
        data = await self.main_data_gs
        message: DBReaction = await DBReaction.get_by_event_mxid(event_id, self.mxid)

        if not message:
            self.log.error(f"Message {event_id} not found when handling redaction")
            await self.main_intent.send_notice(
                self.mxid, "We couldn't find the message when handling redaction"
            )
            return

        try:
            await self.gsc.send_reaction(
                message_id=message.gs_message_id, emoji="", type="reaction", data=data
            )
        except Exception as e:
            self.log.exception(f"Error sending reaction: {e}")
            return

        await DBReaction.delete_by_event_mxid(message.event_mxid, self.mxid, user.mxid)

    async def get_joined_users(self) -> List[UserID] | None:
        """get a list of all users in the room

        Returns
        -------
            A list of User objects.

        """
        try:
            members = await self.main_intent.get_joined_members(room_id=self.mxid)
        except Exception as e:
            self.log.error(e)
            return

        return members.keys()

    async def set_member_power_level(self, member: UserID, power_level: int) -> None:
        """It sets the power level of a member in the room

        Parameters
        ----------
        member : User
            The user ID of the member.
        power_level : int
            The power level of the member.

        """
        room_members = await self.get_joined_users()
        if member not in room_members:
            self.log.warning(
                f"Unable to set power level for {member} in {self.mxid}, user not in room"
            )
            return False

        portal_pl = await self.main_intent.get_power_levels(room_id=self.mxid)
        portal_pl.users[member] = power_level
        await self.main_intent.set_power_levels(
            room_id=self.mxid,
            content=portal_pl,
        )

        return True

    async def handle_matrix_template(
        self,
        sender: u.User,
        event_id: EventID,
        template_id: str,
        variables: Optional[list[str]] = [],
    ) -> None:
        """
        Send a template to user in WhatsApp

        Parameters
        ----------
        sender: User
            The user who sent the message
        event_id: EventID
            The id of the event of the message sended to Matrix
        template_id: str
            The id of the template that Gupshup use to send the message
        variables: Optional[list]
            The value of the variables, if the template has it
        """
        gupshup_data = await self.main_data_gs

        try:
            status, resp = await self.gsc.send_template(
                data=gupshup_data,
                template_id=template_id,
                variables=variables,
            )
        except Exception as e:
            self.log.error(f"Error sending template: {e}")
            return

        if status == 202:
            await DBMessage(
                mxid=event_id,
                mx_room=self.mxid,
                sender=self.gs_source,
                gsid=GupshupMessageID(resp.get("messageId")),
                gs_app=self.gs_app,
            ).insert()
        else:
            message = resp.get("message")

            if type(message) == dict:
                message = message.get("message")

            await self.main_intent.send_notice(self.mxid, f"Error sending template {message}")
