from typing import Dict, List

from attr import dataclass, ib
from mautrix.types import SerializableAttrs


@dataclass
class ContentQuickReplay(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    header: str = ib(default=None, metadata={"json": "header"})
    text: str = ib(default=None, metadata={"json": "text"})
    caption: str = ib(default=None, metadata={"json": "caption"})
    filename: str = ib(default=None, metadata={"json": "filename"})
    url: str = ib(default=None, metadata={"json": "url"})


@dataclass
class InteractiveMessageOption(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    title: str = ib(default=None, metadata={"json": "title"})
    description: str = ib(default=None, metadata={"json": "description"})
    postback_text: str = ib(default=None, metadata={"json": "postbackText"})


@dataclass
class ItemListReplay(SerializableAttrs):
    title: str = ib(default=None, metadata={"json": "title"})
    subtitle: str = ib(default=None, metadata={"json": "subtitle"})
    options: List[InteractiveMessageOption] = ib(metadata={"json": "options"}, factory=list)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            title=data.get("title"),
            subtitle=data.get("subtitle"),
            options=[InteractiveMessageOption(**option) for option in data.get("options", [])],
        )


@dataclass
class GlobalButtonsListReplay(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    title: str = ib(default=None, metadata={"json": "title"})


@dataclass
class InteractiveMessage(SerializableAttrs):
    type: str = ib(default=None, metadata={"json": "type"})
    content: ContentQuickReplay = ib(default=None, metadata={"json": "content"})
    options: List[InteractiveMessageOption] = ib(metadata={"json": "options"}, factory=list)
    title: str = ib(default=None, metadata={"json": "title"})
    body: str = ib(default=None, metadata={"json": "body"})
    msgid: str = ib(default=None, metadata={"json": "msgid"})
    global_buttons: List[GlobalButtonsListReplay] = ib(
        metadata={"json": "globalButtons"}, factory=list
    )
    items: List[ItemListReplay] = ib(metadata={"json": "items"}, factory=list)

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

        return msg

    @classmethod
    def from_dict(cls, data: Dict):
        if data["type"] == "quick_reply":
            return cls(
                type=data["type"],
                content=ContentQuickReplay(**data["content"]),
                options=[InteractiveMessageOption(**option) for option in data["options"]],
            )
        elif data["type"] == "list":
            return cls(
                type=data["type"],
                title=data["title"],
                body=data["body"],
                global_buttons=[
                    GlobalButtonsListReplay(**item) for item in data["global_buttons"]
                ],
                items=[ItemListReplay.from_dict(item) for item in data["items"]],
            )
