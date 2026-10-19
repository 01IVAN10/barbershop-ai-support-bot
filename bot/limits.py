"""
Ліміти AI-відповідей — захист публічного демо (і гаманця клієнта).

Чому ліміти саме на AI: кожна AI-відповідь — платний запит до моделі
(а на безкоштовному тарифі — частина денної квоти). Кнопки меню нічого
не коштують, тому їх не обмежуємо. Передачу адміну теж: клієнт, який
вичерпав ліміт, усе одно може отримати допомогу.

Два рівні:
- на клієнта за годину — щоб одна людина не "з'їла" все;
- на всіх за добу — щоб навіть багато людей разом не вичерпали квоту
  і не перетворили демо на рахунок.

Рахуємо по таблиці messages (питання там уже є) — окремі лічильники не потрібні,
і ліміти переживають перезапуск бота.
"""
import logging
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot import db
from bot.config import load_config

log = logging.getLogger(__name__)
_cfg = load_config()

_admin_warned_on: date | None = None  # щоб попередити адміна про денний ліміт лише раз на день


async def check_ai_quota(bot: Bot, user_id: int) -> str | None:
    """None — можна відповідати. Рядок — текст для клієнта, чому AI зараз не відповідає."""
    used_global = await db.count_questions(since_hours=24)
    if used_global >= _cfg.ai_limit_global_day:
        log.warning("Денний ліміт AI вичерпано: %s/%s", used_global, _cfg.ai_limit_global_day)
        await _warn_admin_once(bot, used_global)
        return ("Зараз помічник перевантажений 🙏\n"
                "Скористайтеся кнопками меню — там ціни, графік і адреса, — "
                "або натисніть «👤 Адміністратор».")

    used_user = await db.count_questions(since_hours=1, user_id=user_id)
    if used_user >= _cfg.ai_limit_user_hour:
        log.info("Ліміт клієнта %s: %s/%s за годину", user_id, used_user, _cfg.ai_limit_user_hour)
        return ("Ви поставили багато питань за останню годину 🙂\n"
                "Ціни, графік і адреса — у кнопках меню, а на інші питання "
                "відповість адміністратор: «👤 Адміністратор».")
    return None


async def _warn_admin_once(bot: Bot, used: int) -> None:
    """Власник має дізнатися про це від бота, а не від незадоволеного клієнта."""
    global _admin_warned_on
    if _cfg.admin_chat_id is None or _admin_warned_on == date.today():
        return
    _admin_warned_on = date.today()
    try:
        await bot.send_message(
            _cfg.admin_chat_id,
            f"⚠️ Вичерпано ліміт AI-відповідей: {used} за 24 години "
            f"(ліміт {_cfg.ai_limit_global_day}).\n"
            "Поки ліміт не звільниться, бот відповідає лише кнопками і передає клієнтів вам.\n"
            "Змінити ліміт: AI_LIMIT_GLOBAL_DAY у .env.",
        )
    except TelegramAPIError:
        log.exception("Не вдалося попередити адміна про ліміт")
