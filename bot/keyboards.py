"""
Клавіатури бота.

Головне меню — ReplyKeyboard (кнопки замість клавіатури телефона), а не Inline:
меню завжди перед очима клієнта, а натискання приходить як звичайний текст.
Inline-кнопки (під повідомленням) — лише для прайсу по розділах.

Кнопки описані в YAML бізнесу (ui.menu), а не в коді: в іншого бізнесу — інші кнопки,
код той самий. Тут лише перевіряємо опис і будуємо клавіатуру.
"""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.knowledge import RENDERERS, UI, price_section_label

HANDOFF_ACTIONS = {"booking", "human_request"}


def _load_buttons() -> dict[str, dict]:
    """Текст кнопки → її опис. Помилка в YAML — зупинка при старті, а не мовчазна кнопка."""
    buttons = {}
    for row in UI.get("menu", []):
        for btn in row:
            text = btn.get("text")
            actions = [k for k in ("render", "reply", "handoff") if k in btn]
            if not text or len(actions) != 1:
                raise SystemExit(f"❌ ui.menu: кнопка має мати text і ОДНУ дію (render/reply/handoff): {btn}")
            if "render" in btn and btn["render"] not in RENDERERS:
                raise SystemExit(f"❌ ui.menu: невідомий render {btn['render']!r} (є: {', '.join(RENDERERS)})")
            if "handoff" in btn and btn["handoff"] not in HANDOFF_ACTIONS:
                raise SystemExit(f"❌ ui.menu: handoff має бути booking або human_request: {btn}")
            if btn.get("by_sections") and btn.get("render") != "price_list":
                raise SystemExit(f"❌ ui.menu: by_sections працює лише з render: price_list: {btn}")
            buttons[text] = btn
    if not buttons:
        raise SystemExit("❌ ui.menu порожнє: опишіть кнопки в YAML бізнесу")
    return buttons


BUTTONS = _load_buttons()

main_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=btn["text"]) for btn in row] for row in UI["menu"]],
    resize_keyboard=True,  # компактні кнопки, а не на пів екрана
    input_field_placeholder=UI.get("menu_placeholder", "Оберіть пункт або напишіть питання"),
)


# ---------- прайс по розділах ----------
# Inline-кнопки (під повідомленням): натискання приходить як callback, а не як текст,
# і бот замінює текст того самого повідомлення — чат не засмічується.

class PriceSection(CallbackData, prefix="prices"):
    """Дані кнопки: мітка прайсу + номер розділу (-1 — список розділів).

    Telegram дозволяє лише 64 байти, тому номер, а не назва розділу.
    """
    version: str
    index: int


HALF_ROW_CHARS = 17  # стільки символів влазить у пів ширини телефона; довший підпис — на весь ряд


def price_sections_keyboard(prices: dict, version: str, url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, section in enumerate(prices["sections"]):
        button = InlineKeyboardButton(text=price_section_label(section),
                                      callback_data=PriceSection(version=version, index=i).pack())
        last = rows[-1] if rows else []
        # Коротка кнопка стає поруч із попередньою, якщо та теж коротка і сама в ряду.
        if len(last) == 1 and max(len(last[0].text), len(button.text)) <= HALF_ROW_CHARS:
            last.append(button)
        else:
            rows.append([button])
    if url:
        rows.append([InlineKeyboardButton(text="📄 Повний прайс на сайті", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def price_back_keyboard(version: str) -> InlineKeyboardMarkup:
    back = InlineKeyboardButton(text="← Усі розділи", callback_data=PriceSection(version=version, index=-1).pack())
    return InlineKeyboardMarkup(inline_keyboard=[[back]])
