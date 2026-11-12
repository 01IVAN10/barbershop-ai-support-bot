"""
Обгортка над AI-моделлю. Решта бота не знає, що всередині Gemini.

Навіщо обгортка: щоб змінити постачальника (Gemini → Claude, OpenAI),
переписується лише цей файл. Бот викликає ask_llm() і отримує текст.
Для клієнта це аргумент: "ми не прив'язані до однієї компанії".
"""
import asyncio
import logging
from enum import Enum

from pydantic import BaseModel, Field, ValidationError, create_model

from google import genai
from google.genai import errors, types

from bot.config import load_config
from bot.knowledge import SAFETY

log = logging.getLogger(__name__)

_config = load_config()
# Клієнт створюємо один раз: він тримає з'єднання, створювати його на кожне
# повідомлення — повільно і марнотратно.
_client = genai.Client(api_key=_config.gemini_api_key)


# Тимчасові збої, після яких має сенс повторити запит:
# 503 — модель перевантажена, 500 — збій у Google, 429 — короткочасний ліміт запитів.
# 400/401/404 НЕ повторюємо: неправильний ключ чи модель не виправляться самі.
RETRY_CODES = {429, 500, 503}
RETRY_DELAYS = [1.5, 4]  # секунди перед 2-ю і 3-ю спробою; разом клієнт чекає максимум ~6 с


class Reason(str, Enum):
    """Чому потрібна людина. Фіксований список — щоб код міг на це реагувати."""
    NONE = "none"                    # людина не потрібна
    NO_INFO = "no_info"              # відповіді немає в базі знань
    BOOKING = "booking"              # запис, перенесення, скасування
    HUMAN_REQUEST = "human_request"  # клієнт сам просить живу людину
    COMPLAINT = "complaint"          # скарга, конфлікт, негатив
    # Лише для бізнесів із safety.medical: true (ветклініка тощо):
    EMERGENCY = "emergency"          # невідкладний стан — клієнту одразу телефон, без «чекайте»
    MEDICAL = "medical_question"     # симптоми, стан, ліки, лікування — тільки людина


MEDICAL_REASONS = {Reason.EMERGENCY, Reason.MEDICAL}
# Медичний режим вмикається в YAML бізнесу. Без нього модель навіть не бачить цих причин.
MEDICAL_MODE = bool(SAFETY.get("medical"))

_ANSWER_DESC = (
    "Текст для клієнта. Без обіцянок дій: не пиши «передам», «запишу», "
    "«з вами зв'яжуться» — про передачу людині повідомить система."
)
_NEEDS_HUMAN_DESC = "true, якщо потрібен адміністратор"
_REASON_DESC = "Чому потрібен адміністратор; none, якщо не потрібен"


class BotReply(BaseModel):
    """Формат, у якому модель ЗОБОВ'ЯЗАНА відповісти (Gemini гарантує це через схему).

    Описи полів (description) теж ідуть моделі — це частина інструкції.
    """
    answer: str = Field(description=_ANSWER_DESC)
    needs_human: bool = Field(description=_NEEDS_HUMAN_DESC)
    reason: Reason = Field(description=_REASON_DESC)


def _response_schema() -> type[BaseModel]:
    """Схема для Gemini: та сама BotReply, але лише з причинами, доступними цьому бізнесу.

    Барбершоп отримує рівно ту схему, що й раніше (без emergency / medical_question),
    тож його поведінка не змінюється.
    """
    allowed = [r for r in Reason if MEDICAL_MODE or r not in MEDICAL_REASONS]
    reason_enum = Enum("Reason", {r.name: r.value for r in allowed}, type=str)
    reason_enum.__doc__ = Reason.__doc__  # описи теж ідуть моделі — лишаємо їх як були
    return create_model(
        "BotReply",
        __doc__=BotReply.__doc__,
        answer=(str, Field(description=_ANSWER_DESC)),
        needs_human=(bool, Field(description=_NEEDS_HUMAN_DESC)),
        reason=(reason_enum, Field(description=_REASON_DESC)),
    )


_RESPONSE_SCHEMA = _response_schema()


class LLMError(Exception):
    """Будь-яка проблема з моделлю. Хендлер ловить саме її і не знає деталей Gemini."""


async def ask_llm(system_prompt: str, history: list[dict]) -> BotReply:
    """
    history — список повідомлень у нашому форматі:
        [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}]
    Повертає BotReply: текст + рішення, чи потрібна людина.
    """
    # Перекладаємо наш формат у формат Gemini. У Gemini роль бота називається "model".
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["text"])],
        )
        for m in history
    ]
    response = await _generate_with_retry(system_prompt, contents)
    _log_usage(response)

    # response.parsed — SDK уже перетворив JSON на об'єкт схеми.
    # Якщо ні (рідко: обірвана відповідь) — пробуємо розібрати текст самі.
    parsed = response.parsed
    if not isinstance(parsed, _RESPONSE_SCHEMA):
        try:
            parsed = _RESPONSE_SCHEMA.model_validate_json(response.text or "")
        except ValidationError as e:
            log.error("Модель повернула не той формат: %r", (response.text or "")[:300])
            raise LLMError("Неправильний формат відповіді") from e
    reply = BotReply(answer=parsed.answer, needs_human=parsed.needs_human,
                     reason=Reason(parsed.reason.value))

    # Захист від суперечностей: «людина не потрібна», але причина вказана — і навпаки.
    if reply.needs_human and reply.reason == Reason.NONE:
        reply.reason = Reason.NO_INFO
    if not reply.needs_human:
        reply.reason = Reason.NONE
    return reply


async def _generate_with_retry(system_prompt: str, contents: list):
    """Викликає Gemini; при тимчасовому збої чекає і пробує ще (до 3 спроб загалом)."""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            # client.aio — асинхронна версія: поки чекаємо відповідь Gemini (1–3 с),
            # бот обслуговує інших клієнтів, а не "зависає".
            return await _client.aio.models.generate_content(
                model=_config.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    # "Температура" = міра фантазії. 0 — модель обирає найімовірніші слова.
                    # Для підтримки потрібна точність, а не креативність (було 0.2 —
                    # тест-набір показав випадкові вигадки).
                    temperature=0,
                    max_output_tokens=1024,
                    # Структурована відповідь: модель повертає JSON рівно за схемою BotReply.
                    # Це надійніше, ніж просити «відповідай у JSON» у промпті.
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                ),
            )
        except errors.APIError as e:
            if e.code in RETRY_CODES and attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                log.warning("Gemini %s, спроба %d, повтор через %.1f с", e.code, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            log.exception("Помилка Gemini (код %s)", e.code)
            raise LLMError(str(e)) from e
        except Exception as e:  # мережа тощо
            log.exception("Помилка зв'язку з Gemini")
            raise LLMError(str(e)) from e


def _log_usage(response) -> None:
    """Пишемо в лог, скільки токенів пішло на запит, — так рахується реальна вартість."""
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        log.info("Токени: вхід=%s, вихід=%s",
                 usage.prompt_token_count, usage.candidates_token_count)
