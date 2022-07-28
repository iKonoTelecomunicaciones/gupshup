from typing import cast

from mautrix.util.formatter import EntityType, MarkdownString
from mautrix.util.formatter import MatrixParser as BaseMatrixParser


async def matrix_to_whatsapp(html: str) -> str:
    parsed = await MatrixParser().parse(html)
    return parsed.text


class WhatsAppFormatString(MarkdownString):
    def format(self, entity_type: EntityType, **kwargs) -> "WhatsAppFormatString":
        prefix = suffix = ""
        if entity_type == EntityType.BOLD:
            prefix = suffix = "*"
        elif entity_type == EntityType.ITALIC:
            prefix = suffix = "_"
        elif entity_type == EntityType.STRIKETHROUGH:
            prefix = suffix = "~"
        elif entity_type == EntityType.URL:
            if kwargs["url"] != self.text:
                suffix = f" ({kwargs['url']})"
        elif entity_type in (EntityType.PREFORMATTED, EntityType.INLINE_CODE):
            prefix = suffix = "```"
        elif entity_type == EntityType.BLOCKQUOTE:
            children = self.trim().split("\n")
            children = [child.prepend("> ") for child in children]
            return self.join(children, "\n")
        elif entity_type == EntityType.HEADER:
            prefix = "#" * kwargs["size"] + " "
        else:
            return self

        self.text = f"{prefix}{self.text}{suffix}"
        return self


class MatrixParser(BaseMatrixParser[WhatsAppFormatString]):
    fs = WhatsAppFormatString

    async def parse(self, data: str) -> WhatsAppFormatString:
        return cast(WhatsAppFormatString, await super().parse(data))
