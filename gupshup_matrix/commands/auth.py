from mautrix.bridge.commands import HelpSection, command_handler

from .typehint import CommandEvent

SECTION_AUTH = HelpSection("Authentication", 10, "")


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_AUTH,
    help_text="Link the bridge to a Gupshup application",
    help_args="[app_name] [phone]",
)
async def link(evt: CommandEvent) -> None:
    if len(evt.args) < 2:
        return await evt.reply("")
