from typing import List, NamedTuple

from mautrix.bridge.config import BaseBridgeConfig, ConfigUpdateHelper
from mautrix.client import Client
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

        copy, copy_dict, base = helper

        copy("homeserver.public_address")

        copy("appservice.community_id")

        copy("bridge.default_user_level")
        copy_dict("bridge.default_power_levels")
        copy_dict("bridge.default_events_levels")
        copy("bridge.username_template")
        copy("bridge.displayname_template")
        copy("bridge.room_name_template")
        copy("bridge.private_chat_name_template")
        copy("bridge.command_prefix")

        copy("bridge.periodic_reconnect.interval")
        copy("bridge.periodic_reconnect.resync")
        copy("bridge.periodic_reconnect.always")

        copy("bridge.federate_rooms")
        copy("bridge.initial_state")
        copy("bridge.bridge_notices")

        copy("bridge.provisioning.enabled")
        copy("bridge.provisioning.prefix")
        copy("bridge.provisioning.shared_secret")
        if base["bridge.provisioning.shared_secret"] == "generate":
            base["bridge.provisioning.shared_secret"] = self._new_token()

        copy_dict("bridge.permissions")

        copy("bridge.relay.enabled")
        copy_dict("bridge.relay.message_formats")

        copy("gupshup.base_url")
        copy("gupshup.webhook_path")

        copy_dict("quick_reply")

    def _get_permissions(self, key: str) -> Permissions:
        level = self["bridge.permissions"].get(key, "")
        admin = level == "admin"
        user = level == "user" or admin
        relay = level == "relay" or user
        return Permissions(relay, user, admin, level)

    def get_permissions(self, mxid: UserID) -> Permissions:
        permissions = self["bridge.permissions"]
        if mxid in permissions:
            return self._get_permissions(mxid)

        _, homeserver = Client.parse_user_id(mxid)
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")
