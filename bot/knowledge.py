"""
База знань: завантаження business.yaml і форматування відповідей для кнопок.

Логіка: на часті питання (ціни, графік, адреса) відповідають КНОПКИ,
а не AI. Чому:
- 0 грн за запит і миттєва відповідь;
- 100% точність — текст береться прямо з файлу, моделі нема де помилитися;
- AI лишається для вільних питань («а можна з собакою?»).
Такий гібрид — аргумент для клієнта: дешевше і надійніше, ніж «усе через AI».
"""
from html import escape as _escape
from pathlib import Path

import yaml

def escape(text: str) -> str:
    """Екранує <, > і & — інакше текст типу "<5 хв" зламав би HTML-розмітку Telegram.
    Лапки й апострофи не чіпаємо: у тексті повідомлення вони безпечні."""
    return _escape(str(text), quote=False)


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "business.yaml"

DAYS_UA = {
    "monday": "Пн", "tuesday": "Вт", "wednesday": "Ср", "thursday": "Чт",
    "friday": "Пт", "saturday": "Сб", "sunday": "Нд",
}


def load_knowledge() -> dict:
    """Читає YAML один раз при старті. Зміни у файлі — перезапустити бота."""
    with open(DATA_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Завантажуємо при імпорті модуля: якщо YAML зламаний — бот впаде одразу (fail fast).
KB = load_knowledge()


def format_prices() -> str:
    lines = ["<b>💈 Послуги і ціни</b>", ""]
    for s in KB["services"]:
        prices = " / ".join(f"{level}: {price} грн" for level, price in s["price"].items())
        lines.append(f"<b>{escape(s['name'])}</b> — {s['duration']} хв")
        lines.append(f"   {escape(prices)}")
        if s.get("note"):
            lines.append(f"   <i>{escape(s['note'])}</i>")
    lines += ["", "Ціна залежить від рівня майстра."]
    return "\n".join(lines)


def format_schedule() -> str:
    sch = KB["schedule"]
    lines = ["<b>🕐 Графік роботи</b>", ""]
    for day, hours in sch["regular"].items():
        lines.append(f"{DAYS_UA[day]}: {hours}")
    lines += ["", escape(sch["last_booking"])]
    if sch.get("exceptions"):
        lines += ["", "<b>Особливі дні:</b>"]
        for ex in sch["exceptions"]:
            lines.append(f"{ex['date']}: {escape(ex['hours'])}")
    return "\n".join(lines)


def format_masters() -> str:
    lines = ["<b>✂️ Наші майстри</b>", ""]
    for m in KB["masters"]:
        lines.append(f"<b>{escape(m['name'])}</b> — {escape(m['level'])}, {m['experience_years']} р. досвіду")
        lines.append(f"   {escape(m['specialty'])}")
        lines.append(f"   Працює: {escape(m['works'])}")
    return "\n".join(lines)


def format_contacts() -> str:
    b = KB["business"]
    return "\n".join([
        "<b>📍 Як нас знайти</b>",
        "",
        f"{escape(b['city'])}, {escape(b['address'])}",
        escape(b["landmark"]),
        "",
        f"📞 {escape(b['phone'])}",
        f"Instagram: {escape(b['instagram'])}",
    ])

def format_payment() -> str:
    lines = ["<b>💵 Способи оплати</b>", ""]
    for method in KB["payment"]["methods"]:
        lines.append(f"• {escape(method)}")
    return "\n".join(lines)