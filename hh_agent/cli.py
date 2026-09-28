from __future__ import annotations

import asyncio
import click
from rich.console import Console
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
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, "\nНажмите ENTER в этой консоли, когда завершите вход в аккаунт hh.ru...\n")
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
@click.option("--query", type=str, default="AI-инженер", help="Поисковый запрос на hh.ru")
@click.option("--limit", type=int, default=3, help="Сколько вакансий обработать в сессии")
def live(query, limit):
    """
    Запустить в реале с открытием вкладки браузера на экране (Headful).
    Логи терминала синхронизированы со стадиями и HUD в браузере.
    """
    from hh_agent.core.live_runner import LiveVisualRunner
    runner = LiveVisualRunner()
    asyncio.run(runner.run(query=query, max_vacancies=limit))


@cli.command()
@click.option("--mode", type=click.Choice(["auto", "semi_auto"]), default=None, help="Режим откликов")
@click.option("--max-vacancies", type=int, default=None, help="Лимит вакансий за сессию")
@click.option("--live/--silent", default=False, help="Показывать окно браузера и HUD в живую")
@click.option("--query", type=str, default="AI-инженер", help="Поисковый запрос")
def run(mode, max_vacancies, live, query):
    """Запустить сессию анализа (вчера + сегодня) и отправки сводки."""
    if live:
        from hh_agent.core.live_runner import LiveVisualRunner
        runner = LiveVisualRunner()
        asyncio.run(runner.run(query=query, max_vacancies=max_vacancies or 3))
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
        console.print("[green]✔ Дайджест отправлен![/green]")

    asyncio.run(_digest())


if __name__ == "__main__":
    cli()
