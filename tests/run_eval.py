"""
Автоматичний тест AI-відповідей на реальній моделі.

Запуск (з кореня проєкту, з активованим .venv):
    python -m tests.run_eval                 # усі сценарії, кожен 3 рази
    python -m tests.run_eval --repeat 5      # стабільніше, але довше
    python -m tests.run_eval --only who_shaves,injection

Інший бізнес — свої дані і свій набір сценаріїв (звіт пишеться поруч із ними):
    BUSINESS_FILE=private/<бізнес>/business.yaml \
        python -m tests.run_eval --cases private/<бізнес>/eval_cases.yaml

Навіщо повтори: модель відповідає трохи по-різному щоразу. Вигадка може
трапитися раз на 5 спроб — один ручний тест її не побачить.

Що перевіряємо — те, що побачить КЛІЄНТ: ті самі функції, що й у боті
(guards.pre_check → модель → guards.resolve → handoff.client_notice), а не копія
логіки — інакше тест і бот колись розійдуться.

Результат: таблиця в терміналі + eval_report.md поруч із файлом сценаріїв.
"""
import argparse
import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from bot.config import load_config
from bot.guards import PRICE_RE, pre_check, resolve, strip_promises
from bot.handoff import client_notice
from bot.knowledge import facts
from bot.llm import LLMError, Reason, ask_llm
from bot.prompts import build_system_prompt

CASES_FILE = Path(__file__).parent / "eval_cases.yaml"


def _collect_prices(node, inside_price: bool = False) -> set[int]:
    """Усі числа під ключами «price» — у будь-якій схемі YAML:
    барбершоп services[].price {рівень: ціна}, клініка sections[].items[].price, рядки «від 3800 ₴».
    Лише значення price, не назви послуг: там вага й години («до 10 кг», «20:00–7:00»)."""
    found: set[int] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found |= _collect_prices(value, inside_price or str(key).lower() == "price")
    elif isinstance(node, list):
        for value in node:
            found |= _collect_prices(value, inside_price)
    elif inside_price and isinstance(node, int) and not isinstance(node, bool):
        found.add(node)
    elif inside_price and isinstance(node, str):
        found |= {int(re.sub(r"\s", "", n)) for n in re.findall(r"\d[\d ]*\d|\d", node)}
    return found


# Реальні ціни з бази знань: будь-яка інша «N грн» у відповіді — вигадка.
KNOWN_PRICES = _collect_prices(facts())


def _norm(text: str) -> str:
    """Нижній регістр і один вид апострофа — щоб «Лук’янівська» = «Лук'янівська»."""
    return text.lower().replace("’", "'").replace("ʼ", "'")


async def client_sees(question: str, history: list[dict]) -> tuple[Reason, str, bool]:
    """Шлях повідомлення як у боті (handlers/fallback.py). Повертає
    (остаточна причина, увесь текст, який побачить клієнт, чи фільтр вирізав обіцянку)."""
    reason = pre_check(question)
    if reason is not None:  # невідкладний стан — модель не викликається взагалі
        return reason, client_notice(reason), False
    reply = await ask_llm(build_system_prompt(), history)
    reason, text = resolve(question, reply.answer, reply.reason)
    notice = client_notice(reason) if reason != Reason.NONE else ""
    promise_cut = strip_promises(reply.answer) != reply.answer.strip()
    return reason, "\n".join(t for t in (text, notice) if t), promise_cut


def check(case: dict, reason: Reason, text: str) -> list[str]:
    """Повертає список проблем. Порожній список = сценарій пройдено."""
    problems = []
    t = _norm(text)
    needs_human = reason != Reason.NONE

    if needs_human != case["needs_human"]:
        problems.append(f"needs_human={needs_human}, очікувалось {case['needs_human']}")

    expected_reason = case.get("reason")
    if expected_reason and needs_human:
        allowed = expected_reason if isinstance(expected_reason, list) else [expected_reason]
        if reason.value not in allowed:
            problems.append(f"reason={reason.value}, очікувалось {'/'.join(allowed)}")

    for item in case.get("must_contain", []):
        options = item if isinstance(item, list) else [item]
        if not any(_norm(o) in t for o in options):
            problems.append(f"немає «{' / '.join(options)}»")

    for bad in case.get("must_not_contain", []):
        # "re:..." — регулярний вираз (коли простого підрядка мало, напр. «барбер Андрій»,
        # але НЕ «топ-барбер Андрій»); інакше — звичайний підрядок.
        found = (re.search(bad[3:], t) if bad.startswith("re:") else _norm(bad) in t)
        if found:
            problems.append(f"є заборонене «{bad}»")

    # Вигадані ціни — перевіряємо в КОЖНОМУ сценарії.
    # Обмеження: ціна іншої послуги (напр. 500 замість 550) сюди не потрапить —
    # такі помилки ловить must_contain конкретного сценарію.
    for raw in PRICE_RE.findall(text):
        price = int(re.sub(r"\s", "", raw))
        if price not in KNOWN_PRICES:
            problems.append(f"вигадана ціна {price} грн")

    return problems


async def run(repeat: int, delay: float, only: set[str] | None,
              cases_file: Path, report_file: Path) -> None:
    cases = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    if only:
        cases = [c for c in cases if c["id"] in only]
    model = load_config().gemini_model
    print(f"Модель: {model} | сценаріїв: {len(cases)} | повторів: {repeat} | "
          f"запитів: {len(cases) * repeat} (~{len(cases) * repeat * (delay + 1.5) / 60:.0f} хв)\n")

    results = []  # (case, [(ok, problems, reply_text, promise_cut), ...])
    for i, case in enumerate(cases, 1):
        history = [*case.get("history", []), {"role": "user", "text": case["question"]}]
        runs = []
        for _ in range(repeat):
            try:
                reason, text, promise_cut = await client_sees(case["question"], history)
                problems = check(case, reason, text)
                runs.append((not problems, problems, text or f"[{reason.value}]", promise_cut))
            except LLMError as e:
                runs.append((False, [f"помилка API: {e}"[:120]], "", False))
            time.sleep(delay)  # не впираємося в ліміт безкоштовного тарифу (запитів на хвилину)
        passed = sum(r[0] for r in runs)
        mark = "✅" if passed == repeat else ("⚠️" if passed else "❌")
        print(f"{mark} {i:2}. [{case['category']}] {case['id']}: {passed}/{repeat}")
        for ok, problems, _, _ in runs:
            if not ok:
                print(f"       ↳ {'; '.join(problems)}")
        results.append((case, runs))

    write_report(results, repeat, model, report_file)


def write_report(results, repeat: int, model: str, report_file: Path) -> None:
    total = sum(len(runs) for _, runs in results)
    ok_total = sum(r[0] for _, runs in results for r in runs)
    stable = sum(all(r[0] for r in runs) for _, runs in results)
    promises = sum(r[3] for _, runs in results for r in runs)

    by_cat = defaultdict(lambda: [0, 0])
    for case, runs in results:
        by_cat[case["category"]][0] += sum(r[0] for r in runs)
        by_cat[case["category"]][1] += len(runs)

    lines = [
        "# Звіт тестування AI-відповідей",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Модель: `{model}`",
        f"- Сценаріїв: {len(results)}, кожен {repeat} раз(и) — {total} відповідей",
        f"- **Правильних відповідей: {ok_total}/{total} ({ok_total / total:.0%})**",
        f"- Сценаріїв, пройдених у всіх повторах: {stable}/{len(results)}",
        f"- Обіцянок дій, вирізаних фільтром: {promises}",
        "",
        "## За категоріями",
        "",
        "| Категорія | Результат |",
        "|---|---|",
        *[f"| {cat} | {ok}/{n} ({ok / n:.0%}) |" for cat, (ok, n) in by_cat.items()],
        "",
        "## Сценарії",
        "",
        "| # | Сценарій | Питання | Пройдено |",
        "|---|---|---|---|",
    ]
    for i, (case, runs) in enumerate(results, 1):
        passed = sum(r[0] for r in runs)
        mark = "✅" if passed == len(runs) else ("⚠️" if passed else "❌")
        q = case["question"].replace("|", "/")
        lines.append(f"| {i} | {case['id']} | {q} | {mark} {passed}/{len(runs)} |")

    failures = [(c, r) for c, runs in results for r in runs if not r[0]]
    if failures:
        lines += ["", "## Помилки (відповіді, які побачив би клієнт)", ""]
        for case, (_, problems, text, _) in failures:
            lines.append(f"- **{case['id']}** — {'; '.join(problems)}  ")
            lines.append(f"  > {text.replace(chr(10), ' ')[:300]}")

    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nПравильних: {ok_total}/{total} ({ok_total / total:.0%}) | "
          f"стабільних сценаріїв: {stable}/{len(results)} | вирізано обіцянок: {promises}")
    print(f"Звіт: {report_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Тест AI-відповідей бота")
    parser.add_argument("--repeat", type=int, default=3, help="скільки разів ганяти кожен сценарій")
    parser.add_argument("--delay", type=float, default=4.0, help="пауза між запитами, с")
    parser.add_argument("--only", type=str, default="", help="id сценаріїв через кому")
    parser.add_argument("--cases", type=Path, default=CASES_FILE, help="файл сценаріїв (YAML)")
    parser.add_argument("--report", type=Path, default=None,
                        help="куди записати звіт (за замовчуванням eval_report.md поруч зі сценаріями)")
    args = parser.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    report = args.report or args.cases.parent / "eval_report.md"
    # Лише помилки: попередження фільтра обіцянок і так рахуються у звіті.
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run(args.repeat, args.delay, only, args.cases, report))


if __name__ == "__main__":
    main()
