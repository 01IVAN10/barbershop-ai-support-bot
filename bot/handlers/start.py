"""Привітання, довідка і гід для тих, хто тестує демо.

Тексти — з YAML бізнесу (ui.start_text, ui.help_text, ui.demo_text): у кожного бізнесу свої.
"""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.config import load_config
from bot.keyboards import main_menu
from bot.knowledge import UI

router = Router(name="start")
_cfg = load_config()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    # Привітання — «клієнтське». Інструкція для тестувальника — окремо, у /demo.
    await message.answer(UI["start_text"], reply_markup=main_menu, disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(UI["help_text"], reply_markup=main_menu)


@router.message(Command("demo"))
async def cmd_demo(message: Message) -> None:
    """Гід для потенційного замовника: що спитати, щоб за 2 хвилини побачити суть."""
    lines = [UI["demo_text"].rstrip("\n")]
    if _cfg.demo_video_url:
        lines.append(f'🎥 <a href="{_cfg.demo_video_url}">Відео: як це бачить адміністратор</a>')
    if _cfg.developer_contact:
        lines += ["", f"У демо адміністратор — розробник бота. Хочете такого для свого бізнесу? "
                      f"Пишіть: {_cfg.developer_contact}"]
    await message.answer("\n".join(lines), reply_markup=main_menu, disable_web_page_preview=True)
