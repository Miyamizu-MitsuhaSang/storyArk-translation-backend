from .schemas import TranslationTemplateResponse


TEMPLATES = {
    "rpg": TranslationTemplateResponse(
        id="rpg",
        name="游戏本地化 · RPG",
        description="适用于角色扮演游戏的世界观、角色语气和文化规则模板。",
    ),
}


__all__ = ["TEMPLATES"]
