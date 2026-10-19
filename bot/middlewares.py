"""
Middleware — код, який виконується ДО хендлера для кожного повідомлення.

Навіщо: записати клієнта в базу треба при будь-якому повідомленні — кнопка,
питання до AI, фото. Без middleware довелося б дописувати це в кожен хендлер
(і колись забути в одному з них).

outer_middleware (підключаємо в main.py) спрацьовує ще ДО перевірки фільтрів —
тобто навіть для повідомлень, які жоден хендлер не обробить.
"""
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
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


class AntiFloodMiddleware(BaseMiddleware):
    """Захист від флуду: не більше `limit` повідомлень за `window` секунд від одного клієнта.

    Решту повідомлень просто ігноруємо (хендлер не викликається), попередивши один раз.
    Тримаємо в пам'яті, а не в БД: вікно — секунди, після перезапуску скидати не шкода.
    Для кожного повідомлення це кілька мікросекунд — на відміну від запиту в базу.
    """

    def __init__(self, limit: int = 5, window: float = 10.0) -> None:
        self.limit = limit
        self.window = window
        self._times: dict[int, deque] = defaultdict(deque)  # user_id → час останніх повідомлень
        self._warned_until: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None or event.chat.type != "private":  # адмін-групу не обмежуємо
            return await handler(event, data)

        now = time.monotonic()  # monotonic: не "стрибає" при зміні системного часу
        times = self._times[user.id]
        while times and now - times[0] > self.window:  # викидаємо старі відмітки
            times.popleft()
        times.append(now)

        if len(times) <= self.limit:
            return await handler(event, data)

        # Флуд: повідомлення НЕ обробляємо. Попереджаємо один раз за вікно.
        if self._warned_until.get(user.id, 0) < now:
            self._warned_until[user.id] = now + self.window
            log.info("Флуд від %s: %s повідомлень за %s с", user.id, len(times), self.window)
            await event.answer("Ви пишете дуже швидко 🙂 Зачекайте кілька секунд.")
        return None
