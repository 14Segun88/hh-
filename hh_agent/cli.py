from __future__ import annotations

import asyncio
import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from hh_agent.config import settings
from hh_agent.core.browser.harness import BrowserHarness
from hh_agent.core.orchestrator import AgentOrchestrator
from hh_agent.core.storage.db import Database

console = Console()


@click.group()
def cli():
    """HH.ru Harness Agent: Автономный ассистент поиска работы на Qwen 2.5 + NVIDIA NIM."""
    pass


@cli.command()
def demo():
    """Интерактивная демонстрация работы всех 6 стадий Harness-агента (кухня и блендер)."""
    from hh_agent.core.demo import HarnessDemoRunner
    runner = HarnessDemoRunner()
    asyncio.run(runner.run_interactive_demo())


@cli.command()
def login():
    """
    Открыть браузер для ручной авторизации на hh.ru.
    Сессия и cookies сохранятся в data/browser_profile.
    """
    async def _login():
        console.print("[bold cyan]Запуск браузера для авторизации на hh.ru...[/bold cyan]")
        console.print("[dim]Войдите по SMS/паролю. После успешного входа закройте браузер или нажмите Enter здесь.[/dim]")

        # Launch in headful mode explicitly for interactive login
        harness = BrowserHarness(headless=False)
        context = await harness.start()
        page = await context.new_page()
        await page.goto("https://hh.ru/account/login")

        # Keep alive until user completes login
        try:
            from hh_agent.core.live_runner import async_timed_input
            await async_timed_input("\nНажмите ENTER в этой консоли, когда завершите вход в аккаунт hh.ru (таймаут 180с)...\n", timeout=180.0, default="")
        finally:
            await harness.close()
            console.print("[bold green]✔ Сессия успешно сохранена в persistent profile![/bold green]")

    asyncio.run(_login())


@cli.command("test-llm")
def test_llm():
    """Проверить доступность локального LM Studio и облачного NVIDIA NIM."""
    async def _test():
        orchestrator = AgentOrchestrator()
        await orchestrator.test_llm_connectivity()

    asyncio.run(_test())


@cli.command("live")
@click.option("--query", type=str, default="AI-инженер", help="Основной поисковый запрос на hh.ru (баланс 50/50: AI-инженер + LLM)")
@click.option("--pool-size", type=int, default=35, help="Сколько свежих вакансий собрать в пул (по умолчанию 35)")
@click.option("--limit", type=int, default=3, help="Сколько вакансий обработать и откликнуться (по умолчанию 3)")
@click.option("--days", type=int, default=7, help="За какой период искать вакансии (в днях, по умолчанию 7)")
@click.option("--confirm/--auto-submit", default=False, help="Подтверждать отклики и ответы [Y/n] или слать автоматически")
@click.option("--loop/--once", default=False, help="Работать в непрерывном цикле (мониторинг чатов -> отклики -> пауза -> повтор)")
@click.option("--interval", type=int, default=30, help="Интервал между итерациями цикла в минутах (по умолчанию 30)")
def live(query, pool_size, limit, days, confirm, loop, interval):
    """
    Запустить боевой цикл в видимом браузере (Headful Chromium):
    1. Мониторинг откликов и переписка с работодателями в цикле вопрос-ответ.
    2. Поиск свежих вакансий (с исключением всех известных из БД).
    3. Подача откликов с целевым резюме AI-инженера и авторскими письмами.
    """
    from hh_agent.core.live_runner import LiveVisualRunner
    runner = LiveVisualRunner()
    asyncio.run(
        runner.run(
            target_pool_size=pool_size,
            apply_limit=limit,
            search_period_days=days,
            confirm=confirm,
            initial_query=query,
            loop=loop,
            interval_minutes=interval,
        )
    )


@cli.command()
@click.option("--mode", type=click.Choice(["auto", "semi_auto"]), default=None, help="Режим откликов")
@click.option("--max-vacancies", type=int, default=None, help="Лимит вакансий за сессию")
@click.option("--live/--silent", default=False, help="Показывать окно браузера и HUD в живую")
@click.option("--query", type=str, default="AI-инженер", help="Поисковый запрос")
@click.option("--confirm/--auto-submit", default=True, help="Безопасная песочница: подтверждать отправку")
def run(mode, max_vacancies, live, query, confirm):
    """Запустить сессию анализа (вчера + сегодня) и отправки сводки."""
    if live:
        from hh_agent.core.live_runner import LiveVisualRunner
        runner = LiveVisualRunner()
        asyncio.run(runner.run(query=query, max_vacancies=max_vacancies or 3, confirm=confirm))
        return

    if mode:
        settings.application_mode = mode
    if max_vacancies:
        settings.max_vacancies_per_batch = max_vacancies

    async def _run():
        orchestrator = AgentOrchestrator()
        await orchestrator.run_batch_session()

    asyncio.run(_run())


@cli.command()
@click.option("--min-score", type=int, default=60, help="Минимальный балл")
def vacancies(min_score):
    """Показать список найденных вакансий из локальной базы SQLite."""
    async def _list():
        db = Database()
        await db.init_db()
        items = await db.get_vacancies_for_review(min_score=min_score)

        if not items:
            console.print(f"[yellow]Нет вакансий с баллом >= {min_score} в базе данных.[/yellow]")
            return

        table = Table(title=f"Топ вакансий (Балл >= {min_score})")
        table.add_column("Балл", style="bold green", width=6)
        table.add_column("Позиция", style="cyan")
        table.add_column("Компания", style="white")
        table.add_column("Зарплата", style="magenta")
        table.add_column("Статус", style="bold")
        table.add_column("Вердикт NIM", style="dim")

        for item in items:
            table.add_row(
                str(item.get("score", 0)),
                item.get("title", "")[:35],
                item.get("company_name", "")[:20],
                item.get("salary_raw", "")[:20] or "Не указана",
                item.get("status", ""),
                (item.get("verdict", "") or "")[:40],
            )
        console.print(table)

    asyncio.run(_list())


@cli.command()
def digest():
    """Сформировать и отправить текущий дайджест в Telegram без сканирования."""
    async def _digest():
        orchestrator = AgentOrchestrator()
        await orchestrator.initialize()
        stats = await orchestrator.db.get_stats_summary()
        top_vacs = await orchestrator.db.get_vacancies_for_review(min_score=70)
        chats = await orchestrator.db.get_unread_negotiations()

        await orchestrator.telegram.send_session_digest(
            stats=stats,
            top_vacancies=top_vacs,
            incoming_chats=chats,
        )
@cli.command("bot")
def bot():
    """Запустить Telegram CRM-бота (Битрикс24) для интерактивного управления и дашборда."""
    from hh_agent.core.telegram.crm_bot import TelegramCrmBot
    crm_bot = TelegramCrmBot()
    token_status = "настроен (.env)" if crm_bot.bot_token else "не задан (.env)"
    console.print(
        Panel.fit(
            "[bold cyan]🏢 ЗАПУСК TELEGRAM CRM-БОТА (БИТРИКС24)[/bold cyan]\n"
            f"[dim]Токен: {token_status}[/dim]\n"
            "[green]Откройте Telegram и напишите /start боту для авторизации.[/green]",
            border_style="cyan",
        )
    )
    try:
        asyncio.run(crm_bot.poll_updates_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Бот остановлен пользователем.[/yellow]")


@cli.command("crm")
def crm():
    """Показать текущий Bitrix24 / CRM дашборд в консоли и отправить в Telegram."""
    from hh_agent.core.telegram.crm_bot import TelegramCrmBot
    crm_bot = TelegramCrmBot()

    async def _show():
        txt = await crm_bot.get_crm_dashboard_text()
        console.print(Panel(txt, title="🏢 CRM Битрикс24 (HH.RU + TG)", border_style="cyan"))
        sent = await crm_bot.send_dashboard()
        if sent:
            console.print("[bold green]✔ Дашборд успешно отправлен в Telegram![/bold green]")
        else:
            console.print("[dim yellow]ℹ Сообщение выведено в консоль (напишите /start боту для связки).[/dim yellow]")

    asyncio.run(_show())


@cli.command("tg")
@click.option("--days", type=int, default=1, help="За сколько дней сканировать посты (по умолчанию 1)")
@click.option("--notify/--no-notify", default=True, help="Отправлять найденные карточки в Telegram CRM бот")
def tg(days, notify):
    """Сканировать Telegram-каналы (careerspace, datasciencejobs, GetIT, it_hr_vacancy) на AI/LLM вакансии."""
    from hh_agent.core.telegram.hunter import TelegramVacancyHunter
    from hh_agent.core.telegram.crm_bot import TelegramCrmBot

    hunter = TelegramVacancyHunter()
    crm_bot = TelegramCrmBot()

    async def _run_tg():
        vacancies = await hunter.scan_all_channels(days_back=days)
        if vacancies and notify and crm_bot.bot_token and crm_bot.chat_id:
            console.print("  📲 [cyan]Отправка карточек с питчами в Telegram CRM...[/cyan]")
            for vac in vacancies[:5]:
                await crm_bot.send_tg_vacancy_card(vac)
                await asyncio.sleep(0.4)
            await crm_bot.notify_if_crm_updated(force=True)
            console.print("  ✔ [bold green]Карточки успешно доставлены в Telegram![/bold green]")

    asyncio.run(_run_tg())


if __name__ == "__main__":
    cli()

