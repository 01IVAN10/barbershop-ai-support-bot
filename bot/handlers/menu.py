"""Кнопки меню: відповіді прямо з бази знань, без AI.

Що робить кожна кнопка, описано в YAML бізнесу (ui.menu):
  render  — текст будує код із даних (ціни, графік...) — 100% точність;
  reply   — готовий текст із YAML;
  handoff — передача адміністратору (запис або «покличте людину»).
Прайс із by_sections: true — спершу кнопки розділів, ціни — по одному розділу.
"""
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.handoff import BUTTON_PREFIX, request_handoff
from bot.keyboards import BUTTONS, PriceSection, price_back_keyboard, price_sections_keyboard
from bot.knowledge import (KB, RENDERERS, format_price_section, format_price_sections_intro,
                           prices_version)
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
    if btn.get("by_sections"):
        text, keyboard = price_sections_view()
        await message.answer(text, reply_markup=keyboard)
    elif "render" in btn or "reply" in btn:
        text = RENDERERS[btn["render"]]() if "render" in btn else btn["reply"].rstrip("\n")
        for part in split_message(text):
            await message.answer(part, disable_web_page_preview=True)
    else:
        # Запис і адміністратор — та сама функція передачі, що й для AI.
        await request_handoff(message, Reason(btn["handoff"]), f"{BUTTON_PREFIX} «{message.text}»")


# ---------- прайс по розділах ----------
# Мітка рахується один раз при старті: прайс читається з YAML лише при запуску бота.
PRICES = KB.get("prices", {})
PRICES_VERSION = prices_version(PRICES) if PRICES else ""


def price_sections_view(outdated: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Текст і кнопки списку розділів."""
    url = KB["business"].get("price_list_url")
    return (format_price_sections_intro(PRICES, outdated),
            price_sections_keyboard(PRICES, PRICES_VERSION, url))


def price_callback_view(data: PriceSection) -> tuple[str, InlineKeyboardMarkup]:
    """Що показати після натискання: розділ, список розділів або «прайс оновився»."""
    if data.version != PRICES_VERSION:
        return price_sections_view(outdated=True)
    if data.index == -1:
        return price_sections_view()
    text = format_price_section(PRICES, data.index)
    if text is None:
        return price_sections_view(outdated=True)
    return text, price_back_keyboard(PRICES_VERSION)


@router.callback_query(PriceSection.filter())
async def price_section(query: CallbackQuery, callback_data: PriceSection) -> None:
    text, keyboard = price_callback_view(callback_data)
    if isinstance(query.message, Message):
        # «message is not modified» — клієнт двічі натиснув ту саму кнопку; це не помилка.
        with suppress(TelegramBadRequest):
            await query.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    else:  # повідомлення надто старе, Telegram його вже не віддає — надсилаємо нове
        await query.bot.send_message(query.from_user.id, text, reply_markup=keyboard,
                                     disable_web_page_preview=True)
    await query.answer()  # прибирає «годинник» на кнопці
