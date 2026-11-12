"""
Клавіатури бота.

ReplyKeyboard (кнопки замість клавіатури телефона), а не Inline:
меню завжди перед очима клієнта, а натискання приходить як звичайний текст.

Кнопки описані в YAML бізнесу (ui.menu), а не в коді: в іншого бізнесу — інші кнопки,
код той самий. Тут лише перевіряємо опис і будуємо клавіатуру.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.knowledge import RENDERERS, UI

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
