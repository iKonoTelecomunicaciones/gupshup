from mautrix.bridge.db import SQLStateStore as BaseSQLStateStore
from mautrix.types import UserID

from . import puppet as pu


class SQLStateStore(BaseSQLStateStore):
    def is_registered(self, user_id: UserID) -> bool:
        puppet = pu.Puppet.get_by_mxid(user_id, create=False)
        if puppet:
            return puppet.is_registered
        return super().is_registered(user_id)

    def registered(self, user_id: UserID) -> None:
        puppet = pu.Puppet.get_by_mxid(user_id, create=True)
        if puppet:
            puppet.is_registered = True
            puppet.save()
        else:
            super().registered(user_id)
