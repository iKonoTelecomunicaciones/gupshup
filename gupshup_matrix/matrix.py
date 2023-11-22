from __future__ import annotations

from typing import TYPE_CHECKING

from mautrix.bridge import BaseMatrixHandler, RejectMatrixInvite
from mautrix.types import Event, EventID, EventType, ReactionEvent, RedactionEvent, RoomID, UserID

from . import portal as po
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

    async def handle_invite(
        self, room_id: RoomID, user_id: UserID, inviter: u.User, event_id: EventID
    ) -> None:
        user = await u.User.get_by_mxid(user_id, create=False)
        if not user or not await user.is_logged_in():
            return
        portal = await po.Portal.get_by_mxid(room_id)
        if portal and not portal.is_direct:
            try:
                await portal.handle_matrix_invite(inviter, user)
            except RejectMatrixInvite as e:
                await portal.main_intent.send_notice(
                    portal.mxid, f"Failed to invite {user.mxid} on Gupshup: {e}"
                )

    async def send_welcome_message(self, room_id: RoomID, inviter: u.User) -> None:
        await super().send_welcome_message(room_id, inviter)
        if not inviter.notice_room:
            inviter.notice_room = room_id
            await inviter.update()
            await self.az.intent.send_notice(
                room_id, "This room has been marked as your Gupshup bridge notice room."
            )

    async def handle_join(self, room_id: RoomID, user_id: UserID, event_id: EventID) -> None:
        portal: po.Portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return

        user = await u.User.get_by_mxid(user_id, create=False)
        if not user:
            return

        await portal.handle_matrix_join(user)

    @staticmethod
    async def handle_redaction(
        room_id: RoomID, user_id: UserID, event_id: EventID, redaction_event_id: EventID
    ) -> None:
        user = await u.User.get_by_mxid(user_id)
        if not user:
            return

        portal = await po.Portal.get_by_mxid(room_id)
        if not portal:
            return

        await portal.handle_matrix_redaction(user, event_id, redaction_event_id)

    async def allow_message(self, user: u.User) -> bool:
        return user.relay_whitelisted

    async def allow_bridging_message(self, user: u.User, portal: po.Portal) -> bool:
        return portal.has_relay or await user.is_logged_in()
