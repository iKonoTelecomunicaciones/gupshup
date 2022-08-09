from __future__ import annotations

import json

from markdown import markdown
from mautrix.bridge.commands import HelpSection, command_handler
from mautrix.types import EventID, Format, MessageType, TextMessageEventContent

from .. import portal as po
from .. import puppet as pu
from ..gupshup.data import ChatInfo, GupshupMessageSender
from ..util import normalize_number
from .typehint import CommandEvent

SECTION_MISC = HelpSection("Miscellaneous", 40, "")


async def _get_puppet_from_cmd(evt: CommandEvent) -> pu.Puppet | None:
    try:
        phone = normalize_number("".join(evt.args))
    except Exception:
        await evt.reply(
            f"**Usage:** `$cmdprefix+sp {evt.command} <phone>` "
            "(enter phone number in international format)"
        )
        return None

    puppet: pu.Puppet = await pu.Puppet.get_by_phone(phone.replace("+", ""))

    return puppet


@command_handler(
    needs_auth=True,
    management_only=False,
    help_section=SECTION_MISC,
    help_args="<_phone_>",
    help_text="Open a private chat portal with a specific phone number",
)
async def pm(evt: CommandEvent) -> EventID:
    puppet = await _get_puppet_from_cmd(evt)
    if not puppet:
        return

    portal: po.Portal = await po.Portal.get_by_chat_id(
        chat_id=f"{evt.sender.gs_app}-{puppet.phone}"
    )

    chat_customer = {"phone": puppet.phone, "name": puppet.name or puppet.custom_mxid}
    customer = GupshupMessageSender.deserialize(chat_customer)

    chat_info = {
        "app": evt.sender.gs_app,
    }
    info = ChatInfo.deserialize(chat_info)
    info.sender = customer

    if portal.mxid:
        await evt.reply(
            f"You already have a private chat with {puppet.name}: "
            f"[{portal.mxid}](https://matrix.to/#/{portal.mxid})",
        )
        await portal.main_intent.invite_user(portal.mxid, evt.sender.mxid)
        return

    await portal.create_matrix_room(evt.sender, info)

    return await evt.reply("Created portal room and invited you to it.")


@command_handler(
    needs_auth=False,
    help_section=SECTION_MISC,
    help_args='{"room_id": "", "template_message": ""}',
    help_text="Send a Gupshup template",
)
async def template(evt: CommandEvent) -> EventID:

    if evt.is_portal:
        return await evt.reply("You must use this command in management room.")

    prefix_length = len(f"{evt.command_prefix} {evt.command}")
    incoming_params = (evt.content.body[prefix_length:]).strip()
    incoming_params = json.loads(incoming_params)

    room_id = incoming_params.get("room_id")
    template_message = incoming_params.get("template_message")

    if not room_id:
        return await evt.reply("You must specify a room ID.")

    if not template_message:
        return await evt.reply("You must specify a template.")

    msg = TextMessageEventContent(body=template_message, msgtype=MessageType.TEXT)
    msg.trim_reply_fallback()

    portal: po.Portal = await po.Portal.get_by_mxid(room_id)
    if not portal:
        return await evt.reply(f"Failed to get room {room_id}")

    msg_event_id = await portal.az.intent.send_message(
        portal.mxid, msg
    )  # only be visible to the agent
    await portal.handle_matrix_message(
        sender=evt.sender,
        message=msg,
        event_id=msg_event_id,
        is_gupshup_template=True,
    )


@command_handler(
    needs_auth=False,
    help_section=SECTION_MISC,
    help_args='{"room_id": "", "interactive_message": dict}',
    help_text="Send a Gupshup interactive message",
)
async def interactive_message(evt: CommandEvent) -> EventID:
    """Command that allows sending interactive WhatsApp messages.

    Args
    ----------
    dict
        {"room_id": "", "message": "", "interactive_message": dict}
        Doc url: https://www.gupshup.io/developer/docs/bot-platform/guide/whatsapp-api-documentation#sessionInteractiveMessages
    """
    if evt.is_portal:
        return await evt.reply("You must use this command in management room.")

    prefix_length = len(f"{evt.command_prefix} {evt.command}")
    incoming_params = (evt.content.body[prefix_length:]).strip()
    incoming_params = json.loads(incoming_params)

    room_id = incoming_params.get("room_id")
    message = incoming_params.get("message")
    interactive_message = incoming_params.get("interactive_message")

    msg = TextMessageEventContent(
        body=message,
        msgtype=MessageType.TEXT,
        formatted_body=markdown(message),
        format=Format.HTML,
    )
    msg.trim_reply_fallback()

    if not room_id:
        return await evt.reply("You must specify a room ID.")

    if not interactive_message or not message:
        return await evt.reply("You must specify an interactive_message and message.")

    portal = await po.Portal.get_by_mxid(room_id)
    if not portal:
        return await evt.reply(f"Failed to get room {room_id}")

    msg_event_id = await portal.az.intent.send_message(
        portal.mxid, msg
    )  # only be visible to the agent
    await portal.handle_matrix_message(
        sender=evt.sender,
        message=msg,
        event_id=msg_event_id,
        additional_data=interactive_message,
    )
