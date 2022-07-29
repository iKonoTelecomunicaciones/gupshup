from mautrix.bridge.commands import HelpSection, command_handler

from ..db.gupshup_application import GupshupApplication
from .typehint import CommandEvent

SECTION_ACCOUNT = HelpSection("Account", 40, "")


@command_handler(
    help_section=SECTION_ACCOUNT,
    help_args="<gs_app_name> <gs_app_phone> <api_key> <app_id>",
    help_text="Register a new gupshup application.",
    management_only=True,
    needs_auth=False,
)
async def register_app(evt: CommandEvent):

    await evt.redact(reason="Security reasons")

    if len(evt.args) < 4:
        await evt.reply(
            "**Usage:** `$cmdprefix+sp register <gs_app_name> <gs_app_phone> <api_key> <app_id>`"
        )

    gs_app_name = evt.args[0]
    gs_app_phone = evt.args[1]
    api_key = evt.args[2]
    app_id = evt.args[3]

    try:
        if await GupshupApplication.get_by_admin_user(admin_user=evt.sender.mxid):
            await evt.reply("You already have a registered gs_app")
            return

        if await GupshupApplication.get_by_number(number=gs_app_phone):
            await evt.reply(f"This gs_app {gs_app_name} is already registered")
            return

        await GupshupApplication.insert(
            name=gs_app_name,
            admin_user=evt.sender.mxid,
            app_id=app_id,
            api_key=api_key,
            phone_number=gs_app_phone,
        )
    except Exception as e:
        evt.log.exception(e)

    evt.sender.phone = gs_app_phone
    evt.sender.gs_app = gs_app_name
    await evt.sender.update()
    await evt.reply("Application a has been successfully registered")
