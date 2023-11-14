from typing import NewType

import attr
from attr import dataclass
from mautrix.types import SerializableAttrs

GupshupMessageID = NewType("GupshupMessageID", str)
GupshupUserID = NewType("GupshupUserID", str)
GupshupAccountID = NewType("GupshupAccountID", str)
GupshupApplication = NewType("GupshupApplication", str)


class GupshupEventType(str):
    MESSAGE = "message"
    MESSAGE_EVENT = "message-event"
    USER_EVENT = "user-event"


class GupshupMessageStatus(str):
    # Statuses that can come from the status webhook
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"
    ENQUEUED = "enqueued"


@dataclass
class GupshupMessageData(SerializableAttrs):
    text: str = attr.ib(default=None, metadata={"json": "text"})
    url: str = attr.ib(default=None, metadata={"json": "url"})
    content_type: str = attr.ib(default=None, metadata={"json": "contentType"})
    caption: str = attr.ib(default=None, metadata={"json": "caption"})
    latitude: str = attr.ib(default=None, metadata={"json": "latitude"})
    longitude: str = attr.ib(default=None, metadata={"json": "longitude"})
    # Parameters for menus with buttons
    title: str = attr.ib(default=None, metadata={"json": "title"})
    reply_message: str = attr.ib(default=None, metadata={"json": "reply"})
    # Parameter for menu with lists
    postback_text: str = attr.ib(default=None, metadata={"json": "postbackText"})
    # Error response
    code: str = attr.ib(default=None, metadata={"json": "code"})
    reason: str = attr.ib(default=None, metadata={"json": "reason"})
    contacts: str = attr.ib(default=None, metadata={"json": "contacts"})
    # Context's id from message
    msg_id: str = attr.ib(default=None, metadata={"json": "id"})
    msg_gsId: str = attr.ib(default=None, metadata={"json": "gsId"})
    emoji: str = attr.ib(default=None, metadata={"json": "emoji"})


@dataclass
class GupshupMessageSender(SerializableAttrs):
    phone: str = attr.ib(default=None, metadata={"json": "phone"})
    name: str = attr.ib(default=None, metadata={"json": "name"})
    country_code: str = attr.ib(default=None, metadata={"json": "country_code"})
    dial_code: str = attr.ib(default=None, metadata={"json": "dial_code"})


@dataclass
class GupshupPayload(SerializableAttrs):
    id: GupshupMessageID = attr.ib(default=None, metadata={"json": "id"})
    # gsid come only on GupshupStatusEvent - delivered and read events
    gsid: GupshupMessageID = attr.ib(default=None, metadata={"json": "gsId"})
    source: str = attr.ib(default=None, metadata={"json": "source"})
    type: str = attr.ib(default=None, metadata={"json": "type"})
    sender: GupshupMessageSender = attr.ib(default=None, metadata={"json": "sender"})
    destination: GupshupUserID = attr.ib(default=None, metadata={"json": "destination"})
    body: GupshupMessageData = attr.ib(default=None, metadata={"json": "payload"})
    context: GupshupMessageData = attr.ib(default=None, metadata={"json": "context"})


@dataclass
class GupshupMessageEvent(SerializableAttrs):
    app: GupshupApplication = attr.ib(metadata={"json": "app"})
    timestamp: str = attr.ib(metadata={"json": "timestamp"})
    event_type: str = attr.ib(metadata={"json": "type"})
    payload: GupshupPayload = attr.ib(metadata={"json": "payload"})


@dataclass
class GupshupStatusEvent(SerializableAttrs):
    app: str = attr.ib(metadata={"json": "app"})
    timestamp: str = attr.ib(metadata={"json": "timestamp"})
    event_type: str = attr.ib(metadata={"json": "type"})
    payload: GupshupPayload = attr.ib(metadata={"json": "payload"})


@dataclass
class ChatInfo(SerializableAttrs):
    sender: GupshupMessageSender = None
    app: GupshupApplication = ""
