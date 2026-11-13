"""
Middleware — код, який виконується ДО хендлера для кожного повідомлення.

Навіщо: записати клієнта в базу треба при будь-якому повідомленні — кнопка,
питання до AI, фото. Без middleware довелося б дописувати це в кожен хендлер
(і колись забути в одному з них).

outer_middleware (підключаємо в main.py) спрацьовує ще ДО перевірки фільтрів —
тобто навіть для повідомлень, які жоден хендлер не обробить.

Антифлуд тут НЕ middleware: раніше він стояв перед усім і відкидав повідомлення ще до
перевірки невідкладного стану й до пересилки адміну — альбом із 10 фото доходив до адміна
наполовину, а шосте повідомлення «собака не дихає» зникало. Тепер це FloodGuard, який
fallback.py питає лише перед запитом до моделі: обмежуємо AI, а не зв'язок з людиною.
"""
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from bot import db


class UserTrackingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        # Лише особисті чати: адміни в групі — не клієнти, їх у статистику не пишемо.
        if user is not None and event.chat.type == "private":
            await db.upsert_user(user.id, user.username, user.full_name)
        return await handler(event, data)  # передаємо повідомлення далі — хендлеру


log = logging.getLogger(__name__)


FLOOD_TEXT = "Ви пишете дуже швидко 🙂 Зачекайте кілька секунд і надішліть питання ще раз."


class FloodGuard:
    """Не більше `limit` запитів до моделі за `window` секунд від одного клієнта.

    Тримаємо в пам'яті, а не в БД: вікно — секунди, після перезапуску скидати не шкода.
    """

    def __init__(self, limit: int = 5, window: float = 10.0) -> None:
        self.limit = limit
        self.window = window
        self._times: dict[int, deque] = defaultdict(deque)  # user_id → час останніх запитів

    def allow(self, user_id: int, now: float | None = None) -> bool:
        """True — можна питати модель. False — флуд: клієнту треба сказати FLOOD_TEXT.
        Кажемо щоразу: клієнт має знати, на ЯКЕ повідомлення бот не відповів."""
        now = time.monotonic() if now is None else now  # monotonic: не «стрибає» при зміні часу
        times = self._times[user_id]
        while times and now - times[0] > self.window:  # викидаємо старі відмітки
            times.popleft()
        if len(times) >= self.limit:
            log.info("Флуд від %s: %s запитів за %s с", user_id, len(times), self.window)
            return False
        times.append(now)
        return True


class StaleUpdateMiddleware(BaseMiddleware):
    """Відкидає повідомлення, старші за `max_age` секунд.

    Раніше при старті бот викидав УСЕ, що надійшло, поки він перезапускався (деплой — це
    хвилина-дві): відповідь адміна в темі чи питання клієнта зникали без сліду для обох.
    Тепер ці повідомлення обробляються, а відкидаємо лише справді старі — щоб після довгої
    перерви бот не відповідав пачкою на питання годинної давності.
    """

    def __init__(self, max_age: float = 600) -> None:
        self.max_age = max_age

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        age = (datetime.now(timezone.utc) - event.date).total_seconds()
        if age > self.max_age:
            log.info("Пропускаю старе повідомлення (%.0f хв) у чаті %s", age / 60, event.chat.id)
            return None
        return await handler(event, data)
