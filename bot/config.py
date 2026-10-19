"""
Налаштування бота.

Логіка: секрети (токени, ключі) живуть у файлі .env, а не в коді.
- Код можна викласти на GitHub (портфоліо!), і ключі не витечуть.
- На сервері (Railway) ті самі змінні задаються в панелі, а код не змінюється.
- Клієнту віддаєш код + .env.example, і він вставляє свої ключі.

Запуск перевірки:  python -m bot.config
"""
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

# Шукає файл .env у поточній папці і кладе значення в os.environ.
# Якщо змінна вже задана в оточенні (як на сервері) — .env її НЕ перезапише.
load_dotenv()


@dataclass(frozen=True)  # frozen = налаштування не можна випадково змінити під час роботи
class Config:
    bot_token: str
    gemini_api_key: str
    gemini_model: str
    admin_chat_id: int | None  # ID адмін-групи; None → передача адміну лише телефоном
    db_path: str
    # Ліміти AI-відповідей (крок 7). Кнопки меню й передача адміну — без лімітів.
    ai_limit_user_hour: int    # скільки AI-відповідей один клієнт може отримати за годину
    ai_limit_global_day: int   # скільки AI-відповідей бот дає всім разом за 24 години
    # Демо (необов'язково): показуються в /demo. У боті для реального клієнта — порожні.
    demo_video_url: str
    developer_contact: str


def _require(name: str) -> str:
    """Повертає змінну або зупиняє програму з зрозумілою помилкою.

    Принцип "fail fast": краще впасти одразу при старті з чітким
    повідомленням, ніж через годину на першому повідомленні клієнта.
    """
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"❌ Не задано {name}. Заповни його у файлі .env (див. .env.example)")
    return value


def _optional_int(name: str) -> int | None:
    """Необов'язкове число: порожньо → None; не число → зрозуміла помилка при старті."""
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        sys.exit(f"❌ {name} має бути цілим числом, а зараз: {value!r}")


def _int_with_default(name: str, default: int) -> int:
    value = _optional_int(name)
    return default if value is None else value


def load_config() -> Config:
    return Config(
        bot_token=_require("BOT_TOKEN"),
        gemini_api_key=_require("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        admin_chat_id=_optional_int("ADMIN_CHAT_ID"),
        db_path=os.getenv("DB_PATH", "storage/bot.db"),
        ai_limit_user_hour=_int_with_default("AI_LIMIT_USER_HOUR", 20),
        ai_limit_global_day=_int_with_default("AI_LIMIT_GLOBAL_DAY", 300),
        demo_video_url=os.getenv("DEMO_VIDEO_URL", "").strip(),
        developer_contact=os.getenv("DEVELOPER_CONTACT", "").strip(),
    )


if __name__ == "__main__":
    cfg = load_config()
    # Ніколи не друкуємо секрети повністю — лише перші символи для перевірки.
    print("✅ Конфіг завантажено")
    print(f"   BOT_TOKEN:      {cfg.bot_token[:6]}…")
    print(f"   GEMINI_API_KEY: {cfg.gemini_api_key[:6]}…")
    print(f"   GEMINI_MODEL:   {cfg.gemini_model}")
    print(f"   ADMIN_CHAT_ID:  {cfg.admin_chat_id or 'не задано (передача адміну — телефоном)'}")
