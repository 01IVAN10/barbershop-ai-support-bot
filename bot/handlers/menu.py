"""Кнопки меню: відповіді прямо з бази знань, без AI."""
from aiogram import F, Router
from aiogram.types import Message

from bot import keyboards as kb
from bot import knowledge
from bot.handoff import BUTTON_PREFIX, request_handoff
from bot.llm import Reason

router = Router(name="menu")


# F.text == ... — "магічний фільтр" aiogram: хендлер спрацює,
# лише якщо текст повідомлення дорівнює тексту кнопки.
@router.message(F.text == kb.BTN_PRICES)
async def show_prices(message: Message) -> None:
    await message.answer(knowledge.format_prices())


@router.message(F.text == kb.BTN_SCHEDULE)
async def show_schedule(message: Message) -> None:
    await message.answer(knowledge.format_schedule())

@router.message(F.text == kb.BTN_PAYMENT)
async def show_payment(message: Message) -> None:
    await message.answer(knowledge.format_payment())

@router.message(F.text == kb.BTN_MASTERS)
async def show_masters(message: Message) -> None:
    await message.answer(knowledge.format_masters())


@router.message(F.text == kb.BTN_CONTACTS)
async def show_contacts(message: Message) -> None:
    await message.answer(knowledge.format_contacts())


# Запис і адміністратор — та сама функція передачі, що й для AI.
# На кроці 5 вона почне справді пересилати звернення в адмін-групу.
@router.message(F.text == kb.BTN_BOOK)
async def book(message: Message) -> None:
    await request_handoff(message, Reason.BOOKING, f"{BUTTON_PREFIX} «{message.text}»")


@router.message(F.text == kb.BTN_ADMIN)
async def call_admin(message: Message) -> None:
    await request_handoff(message, Reason.HUMAN_REQUEST, f"{BUTTON_PREFIX} «{message.text}»")
