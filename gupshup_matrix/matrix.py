from __future__ import annotations

from typing import TYPE_CHECKING

from mautrix.bridge import BaseMatrixHandler
from mautrix.types import (
    Event,
    EventID,
    EventType,
    PresenceEvent,
    ReactionEvent,
    ReceiptEvent,
    RedactionEvent,
    RoomID,
    TypingEvent,
    UserID,
)

# DON'T REMOVE COMMAND FROM THIS IMPORT, BRIDGE COMMANDS CAN FAIL
from . import commands
from . import portal as po
from . import puppet as pu
from . import user as u

if TYPE_CHECKING:
    from .__main__ import GupshupBridge

class MatrixHandler(BaseMatrixHandler):
    def __init__(self, bridge: "GupshupBridge") -> None:
        prefix, suffix = bridge.config["bridge.username_template"].format(userid=":").split(":")
        homeserver = bridge.config["homeserver.domain"]
        self.user_id_prefix = f"@{prefix}"
        self.user_id_suffix = f"{suffix}:{homeserver}"

        super().__init__(bridge=bridge)

    async def handle_leave(self, room_id: RoomID, user_id: UserID, event_id: EventID) -> None:
        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return

        user = await u.User.get_by_mxid(user_id, create=False)
        if not user:
            return

        await portal.handle_matrix_leave(user)

    async def handle_event(self, evt: Event) -> None:
        if evt.type == EventType.ROOM_REDACTION:
            evt: RedactionEvent
            await self.handle_redaction(evt.room_id, evt.sender, evt.redacts, evt.event_id)
        elif evt.type == EventType.REACTION:
            evt: ReactionEvent
            await self.handle_reaction(
                evt.room_id, evt.sender, evt.event_id, evt.content, evt.timestamp
            )

    async def handle_ephemeral_event(
        self, evt: ReceiptEvent | PresenceEvent | TypingEvent
    ) -> None:
        if evt.type == EventType.TYPING:
            await self.handle_typing(evt.room_id, evt.content.user_ids)
        else:
            await super().handle_ephemeral_event(evt)
