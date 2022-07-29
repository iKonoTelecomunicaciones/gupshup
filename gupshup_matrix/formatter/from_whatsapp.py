import re
from typing import Match, Optional, Tuple

from mautrix.appservice import IntentAPI
from mautrix.errors import MatrixRequestError
from mautrix.types import (
    Format,
    MessageEvent,
    MessageType,
    RelatesTo,
    RelationType,
    TextMessageEventContent,
)

from ..db import Message
from ..puppet import Puppet as pu

italic = re.compile(r"([\s>~*]|^)_(.+?)_([^a-zA-Z\d]|$)")
bold = re.compile(r"([\s>_~]|^)\*(.+?)\*([^a-zA-Z\d]|$)")
strike = re.compile(r"([\s>_*]|^)~(.+?)~([^a-zA-Z\d]|$)")
code_block = re.compile("```((?:.|\n)+?)```")


def code_block_repl(match: Match) -> str:
    text = match.group(1)
    if "\n" in text:
        return f"<pre><code>{text}</code></pre>"
    return f"<code>{text}</code>"


def whatsapp_to_matrix(text: str) -> Tuple[Optional[str], str]:
    html = italic.sub(r"\1<em>\2</em>\3", text)
    html = bold.sub(r"\1<strong>\2</strong>\3", html)
    html = strike.sub(r"\1<del>\2</del>\3", html)
    html = code_block.sub(code_block_repl, html)
    if html != text:
        return html.replace("\n", "<br/>"), text
    return None, text


async def whatsapp_reply_to_matrix(
    body: Optional[str],
    evt: Message,
    main_intent: Optional[IntentAPI] = None,
    log: Optional[str] = None,
) -> TextMessageEventContent:
    """Create content by replying to a message.

    Defines that the input message (evt) is in response to another in the db,
    returns a content with its defined parameters:

    content = TextMessageEventContent(
        msgtype=MessageType.TEXT,
        body=body,
    )

    The content type is TextMessageEventContent, this is a class of
    mautrix.types "TextMessageEventContent"

    The procedure is as follows:

    It receives the text of the message in the body, it is assigned to the body of the content.
    We define the msgtype of the content.
    We define the format of type html.

    Parameters:

    body: Message text - text
    evt: Message object - Message
    maint_Intent: IntentAPI object - IntentAPI
    """
    log.debug("Creating reply message")
    content = TextMessageEventContent(
        msgtype=MessageType.TEXT,
        body=body,
    )

    content.format = Format.HTML

    await _add_reply_header(content=content, msg=evt, main_intent=main_intent, log=log)

    if content.formatted_body:
        content.formatted_body = content.formatted_body.replace("\n", "<br/>")

    return content


async def _add_reply_header(
    content: TextMessageEventContent, msg: Message, main_intent: IntentAPI, log
):
    """The reply parameters are added to the content and the reply is made to the message

    The content is defined by a variable called relates_to, it is defined by returning
    the object of RelatesTo, to this we must specify that the type is
    RelationType.REFERENCE, this means that it is a message referring to another
    the mxid of the message to which it is going to refer is sent.

    After the event is taken from the message to which it is going to respond, this event
    is saved in the varianle event, this event is searched in the room that has
    the mx_room and the specific event is searched with the message id

    We obtain the puppet and with this we define who in the room is going to respond
    (we take the name) and assign it in the content

    Parameters:

    content: content that generates the message - TextMessageEventContent
    msg: Message to reply - Message
    maint_Intent: IntentAPI object - IntentAPI

    """
    if not msg:
        return

    content.relates_to = RelatesTo(rel_type=RelationType.REFERENCE, event_id=msg.mxid)

    try:
        event: MessageEvent = await main_intent.get_event(msg.mx_room, msg.mxid)
        if isinstance(event.content, TextMessageEventContent):
            event.content.trim_reply_fallback()
        puppet = await pu.get_by_mxid(event.sender, create=False)
        content.set_reply(event, displayname=puppet.name if puppet else event.sender)
    except MatrixRequestError:
        log.exception("Failed to get event to add reply fallback")
        pass
