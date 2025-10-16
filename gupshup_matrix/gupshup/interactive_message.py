import re

from attr import dataclass, ib
from mautrix.types import BaseMessageEventContent, SerializableAttrs


@dataclass
class TextReply(SerializableAttrs):
    """
    Contains a text message.

    - text: The text of the obj.

    """

    text: str = ib(metadata={"json": "text"}, default="")

    @classmethod
    def from_dict(cls, data: dict):
        text_objt = data.get("text", "")
        text_objt = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text_objt)
        return cls(text=text_objt)


@dataclass
class ContentQuickReplay(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    header: str = ib(default=None, metadata={"json": "header"})
    text: str = ib(default=None, metadata={"json": "text"})
    caption: str = ib(default=None, metadata={"json": "caption"})
    filename: str = ib(default=None, metadata={"json": "filename"})
    url: str = ib(default=None, metadata={"json": "url"})

    @classmethod
    def from_dict(cls, data: dict):
        header_data = None
        text_data = None
        caption_data = None

        if data.get("header"):
            header_data = TextReply.from_dict({"text": data.get("header")})
        if data.get("text"):
            text_data = TextReply.from_dict(data)
        if data.get("caption"):
            caption_data = TextReply.from_dict({"text": data.get("caption")})

        return cls(
            type=data.get("type"),
            header=header_data.text if header_data else None,
            text=text_data.text if text_data else None,
            caption=caption_data.text if caption_data else None,
            filename=data.get("filename"),
            url=data.get("url"),
        )


@dataclass
class InteractiveMessageOption(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    listId: str = ib(metadata={"json": "listId"}, default="")
    buttonId: str = ib(metadata={"json": "buttonId"}, default="")
    title: str = ib(default=None, metadata={"json": "title"})
    description: str = ib(default=None, metadata={"json": "description"})
    postback_text: str = ib(default=None, metadata={"json": "postbackText"})

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type"),
            listId=data.get("listId", ""),
            buttonId=data.get("buttonId", ""),
            title=data.get("title"),
            description=data.get("description"),
            postback_text=data.get("postbackText"),
        )


@dataclass
class ItemListReplay(SerializableAttrs):
    title: str = ib(default=None, metadata={"json": "title"})
    subtitle: str = ib(default=None, metadata={"json": "subtitle"})
    options: list[InteractiveMessageOption] = ib(metadata={"json": "options"}, factory=list)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            title=data.get("title"),
            subtitle=data.get("subtitle"),
            options=[
                InteractiveMessageOption.from_dict(option) for option in data.get("options", [])
            ],
        )


@dataclass
class GlobalButtonsListReplay(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    title: str = ib(default=None, metadata={"json": "title"})

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type"),
            title=data.get("title"),
        )


@dataclass
class InteractiveMessage(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    content: ContentQuickReplay = ib(default=None, metadata={"json": "content"})
    options: list[InteractiveMessageOption] = ib(metadata={"json": "options"}, factory=list)
    title: str = ib(default=None, metadata={"json": "title"})
    body: str = ib(default=None, metadata={"json": "body"})
    msgid: str = ib(default=None, metadata={"json": "msgid"})
    global_buttons: list[GlobalButtonsListReplay] = ib(
        metadata={"json": "globalButtons"}, factory=list
    )
    items: list[ItemListReplay] = ib(metadata={"json": "items"}, factory=list)

    @property
    def message(self) -> str:
        msg = ""

        if self.type == "quick_reply":
            msg = ""
            if self.content.header:
                msg = f"{self.content.header}\n"
            if self.content.text:
                msg = f"{msg}{self.content.text}"

            for option in self.options:
                msg = f"{msg}\n{self.options.index(option) + 1}. {option.title}"

        elif self.type == "list":
            msg = ""
            if self.title:
                msg = f"{self.title}\n"
            if self.body:
                msg = f"{msg}{self.body}"

            for item in self.items:
                for option in item.options:
                    msg = f"{msg}\n{option.postback_text}. {option.title}"

        return re.sub(r"\*(.+?)\*", r"**\1**", msg)

    @classmethod
    def from_dict(cls, data: dict):
        if data["type"] == "quick_reply":
            return cls(
                type=data["type"],
                content=ContentQuickReplay.from_dict(data["content"]),
                options=[InteractiveMessageOption.from_dict(option) for option in data["options"]],
            )
        elif data["type"] == "list":
            body_text = TextReply.from_dict({"text": data["body"]})
            title = TextReply.from_dict({"text": data["title"]})
            return cls(
                type=data["type"],
                title=title.text if title else None,
                body=body_text.text if body_text else None,
                global_buttons=[
                    GlobalButtonsListReplay.from_dict(item) for item in data["global_buttons"]
                ],
                items=[ItemListReplay.from_dict(item) for item in data["items"]],
            )


@dataclass
class TemplateMessage(SerializableAttrs, BaseMessageEventContent):
    msgtype: str = ib(default=None, metadata={"json": "msgtype"})
    body: str = ib(default="", metadata={"json": "body"})
    template_message: list = ib(factory=list, metadata={"json": "template_message"})

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            msgtype=data.get("msgtype", ""),
            body=data.get("body", ""),
            template_message=data.get("template_message", []),
        )
