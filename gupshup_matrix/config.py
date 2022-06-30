from typing import Any, Dict, List, Tuple

from mautrix.bridge.config import BaseBridgeConfig, ConfigUpdateHelper
from mautrix.types import UserID


class Config(BaseBridgeConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        super().do_update(helper)

        copy, copy_dict = helper.copy, helper.copy_dict

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
        return user, admin

    def get_permissions(self, mxid: UserID) -> Tuple[bool, bool]:
        permissions = self["bridge.permissions"] or {}
        if mxid in permissions:
            return self._get_permissions(mxid)

        homeserver = mxid[mxid.index(":") + 1 :]
        if homeserver in permissions:
            return self._get_permissions(homeserver)

        return self._get_permissions("*")

    @property
    def namespaces(self) -> Dict[str, List[Dict[str, Any]]]:
        homeserver = self["homeserver.domain"]

        username_format = self["bridge.username_template"].lower().format(userid=".+")
        group_id = (
            {"group_id": self["appservice.community_id"]}
            if self["appservice.community_id"]
            else {}
        )

        return {
            "users": [
                {
                    "exclusive": True,
                    "regex": f"@{username_format}:{homeserver}",
                    **group_id,
                }
            ],
        }
