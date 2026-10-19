"""
Точка входу. Запуск:  python -m bot.main

Порядок: налаштування логів → конфіг → бот → диспетчер з роутерами → polling.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import db, history
from bot.config import load_config
from bot.handoff import check_admin_chat
from bot.handlers import admin, fallback, menu, start
from bot.middlewares import AntiFloodMiddleware, UserTrackingMiddleware


async def daily_cleanup() -> None:
    """Фонова задача: раз на добу видаляє старе листування.

    Не лише при старті: на сервері бот може працювати тижнями без перезапуску.
    """
    while True:
        deleted = await history.purge_old()
        if deleted:
            logging.info("Видалено старих повідомлень: %s", deleted)
        await asyncio.sleep(24 * 60 * 60)


async def main() -> None:
    # Логи з часом і назвою модуля: на сервері це єдиний спосіб зрозуміти, що сталося.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        # stdout, а не stderr (за замовчуванням): хостинги на кшталт Railway фарбують
        # увесь stderr у червоне як помилки — і справжні помилки губляться серед INFO.
        stream=sys.stdout,
    )
    config = load_config()

    # parse_mode=HTML за замовчуванням: можна писати <b>жирний</b> у будь-якій відповіді.
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Клієнтські роутери — ЛИШЕ для особистих чатів. Інакше бот відповідав би AI
    # на кожне повідомлення адміна в адмін-групі.
    for r in (start.router, menu.router, fallback.router):
        r.message.filter(F.chat.type == "private")

    # Middleware виконуються в порядку підключення, ДО будь-якого хендлера (див. middlewares.py):
    # 1) антифлуд — першим, щоб флуд не доходив навіть до бази;
    # 2) запис клієнта в базу.
    dp.message.outer_middleware(AntiFloodMiddleware(limit=5, window=10))
    dp.message.outer_middleware(UserTrackingMiddleware())

    # ПОРЯДОК ВАЖЛИВИЙ: admin — для групи; fallback ловить усе, тому він останній.
    dp.include_routers(admin.router, start.router, menu.router, fallback.router)

    await db.init(config.db_path)
    logging.info("Ліміти AI: %s/год на клієнта, %s/добу на всіх",
                 config.ai_limit_user_hour, config.ai_limit_global_day)
    if config.admin_chat_id is None:
        logging.warning("ADMIN_CHAT_ID не задано: передача адміну працюватиме лише через телефон")
    else:
        await check_admin_chat(bot)  # помилка в ID чи правах — видно одразу при старті

    # Ігноруємо повідомлення, що прийшли, поки бот був вимкнений,
    # щоб після перезапуску він не відповідав на старе пачкою.
    await bot.delete_webhook(drop_pending_updates=True)
    cleanup_task = asyncio.create_task(daily_cleanup())
    logging.info("Бот запущено")
    try:
        await dp.start_polling(bot)
    finally:
        cleanup_task.cancel()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот зупинено")
