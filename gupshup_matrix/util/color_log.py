# from mautrix.util.color_log import ColorFormatter as BaseColorFormatter, PREFIX, RESET
from mautrix.util.logging.color import MXID_COLOR, PREFIX, RESET
from mautrix.util.logging.color import ColorFormatter as BaseColorFormatter

GUPSHUP_COLOR = PREFIX + "35;1m"  # magenta


class ColorFormatter(BaseColorFormatter):
    def _color_name(self, module: str) -> str:
        if module.startswith("gupshup"):
            return GUPSHUP_COLOR + module + RESET
        return super()._color_name(module)
