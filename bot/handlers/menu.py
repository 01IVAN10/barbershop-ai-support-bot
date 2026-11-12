"""Кнопки меню: відповіді прямо з бази знань, без AI.

Що робить кожна кнопка, описано в YAML бізнесу (ui.menu):
  render  — текст будує код із даних (ціни, графік...) — 100% точність;
  reply   — готовий текст із YAML;
  handoff — передача адміністратору (запис або «покличте людину»).
"""
from aiogram import F, Router
from aiogram.types import Message

from bot.handoff import BUTTON_PREFIX, request_handoff
from bot.keyboards import BUTTONS
from bot.knowledge import RENDERERS
from bot.llm import Reason

router = Router(name="menu")

TELEGRAM_LIMIT = 4000  # ліміт Telegram — 4096 символів; беремо із запасом


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Довгий текст (напр. прайс) → кілька повідомлень, розрізаючи між абзацами."""
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:  # один абзац довший за ліміт — ріжемо по рядках
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        current = block
    if current:
        parts.append(current)
    return parts


# F.text.in_(...) — "магічний фільтр" aiogram: хендлер спрацює,
# лише якщо текст повідомлення збігається з текстом однієї з кнопок.
@router.message(F.text.in_(BUTTONS))
async def menu_button(message: Message) -> None:
    btn = BUTTONS[message.text]
    if "render" in btn or "reply" in btn:
        text = RENDERERS[btn["render"]]() if "render" in btn else btn["reply"].rstrip("\n")
        for part in split_message(text):
            await message.answer(part, disable_web_page_preview=True)
    else:
        # Запис і адміністратор — та сама функція передачі, що й для AI.
        await request_handoff(message, Reason(btn["handoff"]), f"{BUTTON_PREFIX} «{message.text}»")
