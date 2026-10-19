"""
Клавіатури бота.

ReplyKeyboard (кнопки замість клавіатури телефона), а не Inline:
меню завжди перед очима клієнта, а натискання приходить як звичайний текст.
"""
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Тексти кнопок — константи. Хендлери порівнюють текст саме з ними,
# тож змінити назву кнопки можна в одному місці, і нічого не зламається.
BTN_PRICES = "💈 Послуги і ціни"
BTN_SCHEDULE = "🕐 Графік"
BTN_MASTERS = "✂️ Майстри"
BTN_CONTACTS = "📍 Адреса"
BTN_BOOK = "📅 Записатися"
BTN_ADMIN = "👤 Адміністратор"
BTN_PAYMENT = "💵 Оплата"

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_PRICES), KeyboardButton(text=BTN_SCHEDULE)],
        [KeyboardButton(text=BTN_MASTERS), KeyboardButton(text=BTN_CONTACTS)],
        [KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_ADMIN)],
        [KeyboardButton(text=BTN_PAYMENT)]
    ],
    resize_keyboard=True,  # компактні кнопки, а не на пів екрана
    input_field_placeholder="Оберіть пункт або напишіть питання",
)
