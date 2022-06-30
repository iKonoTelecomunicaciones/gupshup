import json
from typing import Dict, List

from markdown import markdown
from mautrix.bridge.commands.handler import (
    SECTION_GENERAL,
    CommandEvent,
    HelpCacheKey,
    HelpSection,
    command_handler,
    command_handlers,
)
from mautrix.types import EventID, Format, MessageType, TextMessageEventContent

from .. import portal as po


@command_handler(
    help_section=SECTION_GENERAL,
    help_args="<international phone number>",
    help_text="Open a private chat with the given phone number.",
)
async def pm(evt: CommandEvent) -> EventID:
    if evt.is_portal:
        return await evt.reply("You must use this command in management room.")

    if len(evt.args) == 0:
        return await evt.reply("**Usage:** `$cmdprefix+sp pm <international phone number>`")

    phone_number = "".join(evt.args).translate({ord(c): None for c in "+()- "})
    try:
        int(phone_number)
    except ValueError:
        return await evt.reply("Invalid phone number.")

    portal = po.Portal.get_by_gsid(gsid=phone_number)

    if portal.mxid:
        return await evt.reply(
            f"You already have a private chat portal with that user at "
            f'<a href="https://matrix.to/#/{portal.mxid}">{portal.mxid}</a>',
            allow_html=True,
            render_markdown=False,
        )

    try:
        await portal.create_matrix_room()
    except Exception as err:
        return await evt.reply(f"Failed to create portal room: {err}")

    return await evt.reply("Created portal room and invited you to it.")


@command_handler(
    help_section=SECTION_GENERAL,
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

    portal = po.Portal.get_by_mxid(room_id)
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
    help_section=SECTION_GENERAL,
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

    portal = po.Portal.get_by_mxid(room_id)
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


@command_handler()
async def unknown_command(evt: CommandEvent) -> EventID:
    return await evt.reply("Unknown command. Try `$cmdprefix+sp help` for help.")


help_cache: Dict[HelpCacheKey, str] = {}


async def _get_help_text(evt: CommandEvent) -> str:
    cache_key = await evt.get_help_key()
    if cache_key not in help_cache:
        help_sections: Dict[HelpSection, List[str]] = {}
        for handler in command_handlers.values():
            if handler.has_help and handler.has_permission(cache_key):
                help_sections.setdefault(handler.help_section, [])
                help_sections[handler.help_section].append(handler.help + "  ")
        help_sorted = sorted(help_sections.items(), key=lambda item: item[0].order)
        helps = ["#### {}\n{}\n".format(key.name, "\n".join(value)) for key, value in help_sorted]
        help_cache[cache_key] = "\n".join(helps)
    return help_cache[cache_key]


def _get_management_status(evt: CommandEvent) -> str:
    if evt.is_management:
        return "This is a management room: prefixing commands with `$cmdprefix` is not required."
    elif evt.is_portal:
        return (
            "**This is a portal room**: you must always prefix commands with `$cmdprefix`.\n"
            "Management commands will not be bridged."
        )
    return "**This is not a management room**: you must prefix commands with `$cmdprefix`."


@command_handler(name="help", help_section=SECTION_GENERAL, help_text="Show this help message.")
async def help_cmd(evt: CommandEvent) -> EventID:
    return await evt.reply(_get_management_status(evt) + "\n" + await _get_help_text(evt))
