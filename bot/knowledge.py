"""
База знань: завантаження business.yaml і форматування відповідей для кнопок.

Логіка: на часті питання (ціни, графік, адреса) відповідають КНОПКИ,
а не AI. Чому:
- 0 грн за запит і миттєва відповідь;
- 100% точність — текст береться прямо з файлу, моделі нема де помилитися;
- AI лишається для вільних питань («а можна з собакою?»).
Такий гібрид — аргумент для клієнта: дешевше і надійніше, ніж «усе через AI».
"""
import hashlib
from html import escape as _escape

import yaml

from bot.config import business_yaml


def escape(text: str) -> str:
    """Екранує <, > і & — інакше текст типу "<5 хв" зламав би HTML-розмітку Telegram.
    Лапки й апострофи не чіпаємо: у тексті повідомлення вони безпечні."""
    return _escape(str(text), quote=False)


DAYS_UA = {
    "monday": "Пн", "tuesday": "Вт", "wednesday": "Ср", "thursday": "Чт",
    "friday": "Пт", "saturday": "Сб", "sunday": "Нд",
}


# Службові розділи YAML: тексти інтерфейсу, правила для промпту, налаштування безпеки.
# Це НЕ факти про бізнес, тому моделі як «база знань» вони не передаються.
SERVICE_KEYS = ("ui", "prompt", "safety")


def load_knowledge() -> dict:
    """Читає YAML один раз при старті. Зміни у файлі — перезапустити бота."""
    text, source = business_yaml()
    kb = yaml.safe_load(text)
    if not isinstance(kb, dict) or "business" not in kb:
        raise SystemExit(f"❌ База знань ({source}) має містити розділ business")
    kb["_source"] = source
    return kb


# Завантажуємо при імпорті модуля: якщо YAML зламаний — бот впаде одразу (fail fast).
KB = load_knowledge()
UI: dict = KB.get("ui") or {}
SAFETY: dict = KB.get("safety") or {}


def facts() -> dict:
    """Лише факти про бізнес — те, що бачить модель (без службових розділів)."""
    return {k: v for k, v in KB.items() if k not in SERVICE_KEYS and not k.startswith("_")}


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


def format_price_list() -> str:
    """Прайс у форматі prices.sections[].items[] — {name, price}.

    price — число (грн) або рядок як у прайсі («від 3800»). Текст береться
    з файлу як є: кнопка не може «помилитися» з ціною.
    """
    p = KB["prices"]
    lines = [_price_title(p)]
    for section in p["sections"]:
        lines += ["", *_section_lines(section)]
    return "\n".join(lines + _price_notes(p))


# ---------- прайс по розділах (кнопка з by_sections: true) ----------
# Функції приймають прайс параметром — так їх можна перевірити тестами на будь-яких даних.

def _price_title(prices: dict) -> str:
    return f"<b>{escape(prices.get('title', 'Ціни'))}</b>"


def _section_lines(section: dict) -> list[str]:
    lines = [f"<b>{escape(section['name'])}</b>"]
    for item in section["items"]:
        price = item["price"]
        price_text = f"{price} ₴" if isinstance(price, int) else str(price)
        lines.append(f"• {escape(item['name'])} — {escape(price_text)}")
    return lines


def _price_notes(prices: dict) -> list[str]:
    lines = []
    for note in prices.get("notes", []):
        lines += ["", f"<i>{escape(note)}</i>"]
    return lines


def price_section_label(section: dict) -> str:
    """Підпис кнопки розділу: `button` з YAML або назва без уточнення в дужках.

    «Стаціонар (24 години; категорію визначає лікар…)» → «Стаціонар».
    """
    return section.get("button") or section["name"].split(" (")[0]


def prices_version(prices: dict) -> str:
    """Коротка «мітка» прайсу. Змінився прайс у YAML — змінилася мітка,
    і стара кнопка в чаті вже не покаже не той розділ."""
    raw = yaml.safe_dump(prices, allow_unicode=True, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def format_price_sections_intro(prices: dict, outdated: bool = False) -> str:
    hint = "Прайс оновився — оберіть розділ ще раз:" if outdated else "Оберіть розділ:"
    return f"{_price_title(prices)}\n\n{hint}"


def format_price_section(prices: dict, index: int) -> str | None:
    """Один розділ прайсу + загальні примітки. None — такого розділу немає."""
    sections = prices["sections"]
    if not 0 <= index < len(sections):
        return None
    return "\n".join([_price_title(prices), "", *_section_lines(sections[index]), *_price_notes(prices)])


def format_emergency() -> str:
    """Той самий текст, що бот дає при невідкладному стані (safety.emergency_text)."""
    return escape(SAFETY.get("emergency_text", "").strip())


# Кнопки з `render:` у YAML → функція, що будує відповідь із даних.
RENDERERS = {
    "emergency": format_emergency,
    "prices": format_prices,
    "schedule": format_schedule,
    "masters": format_masters,
    "contacts": format_contacts,
    "payment": format_payment,
    "price_list": format_price_list,
}
