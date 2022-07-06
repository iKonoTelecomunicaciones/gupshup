from typing import Any, Dict, List, NamedTuple, Tuple

from mautrix.bridge.config import BaseBridgeConfig, ConfigUpdateHelper
from mautrix.types import UserID
from mautrix.util.config import ForbiddenDefault, ForbiddenKey

Permissions = NamedTuple("Permissions", relay=bool, user=bool, admin=bool, level=str)

class Config(BaseBridgeConfig):

    @property
    def forbidden_defaults(self) -> List[ForbiddenDefault]:
        return [
            *super().forbidden_defaults,
            ForbiddenDefault("appservice.database", "postgres://username:password@hostname/db"),
            ForbiddenDefault("bridge.permissions", ForbiddenKey("example.com")),
        ]

    def do_update(self, helper: ConfigUpdateHelper) -> None:
        super().do_update(helper)

        copy, copy_dict, _ = helper

        copy("homeserver.public_address")

        copy("appservice.community_id")

        copy("bridge.username_template")
        copy("bridge.displayname_template")
        copy("bridge.auto_change_room_name")
        copy("bridge.command_prefix")
        copy("bridge.google_maps_url")

        copy("bridge.invite_users")

        copy("bridge.federate_rooms")
        copy("bridge.initial_state")

        copy_dict("bridge.permissions")

        copy("gupshup.base_url")
        copy("gupshup.app_name")
        copy("gupshup.api_key")
        copy("gupshup.sender")
        copy("gupshup.webhook_path")
        copy("gupshup.error_codes")

    def _get_permissions(self, key: str) -> Tuple[bool, bool]:
        level = self["bridge.permissions"].get(key, "")
        admin = level == "admin"
        user = level == "user" or admin
        relay = level == "relay" or user
        return relay, user, admin, level

    def get_permissions(self, mxid: UserID) -> Tuple[bool, bool]:
        permissions = self["bridge.permissions"] or {}
        if mxid in permissions:
            return self._get_permissions(mxid)

        homeserver = mxid[mxid.index(":") + 1 :]
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")
