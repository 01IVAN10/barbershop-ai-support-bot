"""
Усе, що не впіймали кнопки, — вільні питання.

Порядок:
0. Медичний режим і невідкладний стан? → телефон ОДРАЗУ, без моделі, без лімітів.
1. Відкрите звернення до адміна? → повідомлення йде адміну, AI мовчить.
2. Інакше відповідає AI; рішення про передачу людині приймає КОД (guards.resolve).

Цей роутер підключається ОСТАННІМ: aiogram перевіряє роутери по черзі
і віддає повідомлення першому, чий фільтр підійшов.
"""
import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from bot import history, limits
from bot.guards import pre_check, resolve
from bot.handoff import HANDOFF_MARK, forward_to_admin, request_handoff
from bot.keyboards import main_menu
from bot.knowledge import KB
from bot.llm import LLMError, Reason, ask_llm
from bot.prompts import build_system_prompt

log = logging.getLogger(__name__)
router = Router(name="fallback")

MAX_QUESTION_LEN = 1000  # захист від "простирадл" тексту, які з'їдають ліміт


@router.message(F.text)
async def ai_answer(message: Message) -> None:
    user_id = message.from_user.id
    question = message.text.strip()[:MAX_QUESTION_LEN]

    # 0. Невідкладний стан — раніше за все: навіть якщо клієнт зараз «у адміна»
    #    (адмін вночі може не читати), ліміт вичерпано чи модель недоступна.
    pre = pre_check(question)
    if pre is not None:
        await request_handoff(message, pre, question)  # телефон клієнту + картка адміну
        await history.add(user_id, "user", question)
        await history.add(user_id, "assistant", HANDOFF_MARK)
        return

    # 1. Клієнт уже розмовляє з адміном — не втручаємося.
    if await forward_to_admin(message):
        return

    # 2. Ліміти AI. Перевіряємо ДО запиту до моделі — саме він коштує грошей.
    #    Кнопки меню і передача адміну працюють і далі: обмежуємо AI, а не сервіс.
    limit_text = await limits.check_ai_quota(message.bot, user_id)
    if limit_text:
        await message.answer(limit_text, reply_markup=main_menu)
        return

    await history.add(user_id, "user", question)

    try:
        # Показує "друкує..." у чаті, поки чекаємо модель — клієнт бачить, що бот живий.
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            reply = await ask_llm(build_system_prompt(), await history.get(user_id))
    except LLMError:
        await history.drop_last(user_id)  # невдалий обмін не залишаємо в історії
        await message.answer(
            "Вибачте, зараз не можу відповісти 😔\n"
            f"Зателефонуйте нам: {KB['business']['phone']}",
            reply_markup=main_menu,
        )
        return

    # Що побачить клієнт і чи потрібна людина — вирішує КОД, а не модель (guards.resolve).
    reason, client_text = resolve(question, reply.answer, reply.reason)

    # В історію пишемо те, що клієнт РЕАЛЬНО побачив. Якби там лишилося «передам заявку»,
    # модель бачила б власний приклад і повторювала його.
    await history.add(user_id, "assistant", client_text or HANDOFF_MARK)
    log.info("user=%s | Q: %s | A: %s | model=%s | final=%s",
             user_id, question[:80], reply.answer[:80], reply.reason.value, reason.value)

    # parse_mode=None: відповідь моделі — звичайний текст. Якщо модель випадково
    # напише "<" чи "&", HTML-режим Telegram зламався б і повідомлення не пішло б.
    if client_text:
        await message.answer(client_text, parse_mode=None)

    if reason != Reason.NONE:
        await request_handoff(message, reason, question)


@router.message()
async def non_text(message: Message) -> None:
    """Фото, стікери, голосові: адміну — якщо звернення відкрите, інакше підказка."""
    if await forward_to_admin(message):
        return
    await message.answer(
        "Поки що я розумію лише текст 🙂 Напишіть питання або оберіть пункт меню.",
        reply_markup=main_menu,
    )
