from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from rich.console import Console
from rich.table import Table
from hh_agent.config import (
    CandidateProfile,
    SearchRules,
    load_candidate_profile,
    load_search_rules,
    settings,
)
from hh_agent.core.analyzer.chat_agent import ChatNegotiationAgent
from hh_agent.core.analyzer.vacancy_eval import VacancyEvaluator
from hh_agent.core.browser.apply import VacancyApplicant
from hh_agent.core.browser.harness import BrowserHarness
from hh_agent.core.browser.negotiations import NegotiationsBrowser
from hh_agent.core.browser.vacancies import VacancyBrowser
from hh_agent.core.llm.local_client import LocalQwenClient
from hh_agent.core.llm.nim_client import NvidiaNimClient
from hh_agent.core.storage.db import Database
from hh_agent.core.telegram.notifier import TelegramNotifier

logger = logging.getLogger(__name__)
console = Console()


class AgentOrchestrator:
    """Coordinates the two-tier LLM pipeline, browser automation, and Telegram reporting."""

    def __init__(self):
        self.profile: CandidateProfile = load_candidate_profile()
        self.rules: SearchRules = load_search_rules()
        self.db = Database()
        self.local_client = LocalQwenClient()
        self.nim_client = NvidiaNimClient()
        self.telegram = TelegramNotifier()

        # Agents
        self.vacancy_evaluator = VacancyEvaluator(
            local_client=self.local_client,
            nim_client=self.nim_client,
            db=self.db,
            profile=self.profile,
            rules=self.rules,
        )
        self.chat_agent = ChatNegotiationAgent(
            local_client=self.local_client,
            nim_client=self.nim_client,
            db=self.db,
            profile=self.profile,
        )

    async def initialize(self) -> None:
        """Initialize database and verify services."""
        await self.db.init_db()

    async def test_llm_connectivity(self) -> Dict[str, Any]:
        """Test both Local LM Studio and NVIDIA NIM endpoints."""
        console.print("[cyan]Проверка доступности языковых моделей...[/cyan]")
        local_ok = await self.local_client.check_health()
        nim_ok = await self.nim_client.check_health()

        local_models = await self.local_client.get_available_models() if local_ok else []

        table = Table(title="Статус LLM Движков")
        table.add_column("Уровень", style="bold")
        table.add_column("Движок / Модель")
        table.add_column("Эндпоинт")
        table.add_column("Статус", style="bold")

        table.add_row(
            "Tier 1 (Локальный)",
            f"LM Studio ({settings.lm_studio_model})",
            settings.lm_studio_url,
            "[green]ДОСТУПЕН[/green]" if local_ok else "[red]НЕ ЗАПУЩЕН (запустите LM Studio)[/red]",
        )
        table.add_row(
            "Tier 2 (Облачный)",
            f"NVIDIA NIM ({settings.nvidia_model})",
            settings.nvidia_base_url,
            "[green]ДОСТУПЕН[/green]" if nim_ok else "[yellow]ОШИБКА КЛЮЧА / СЕТИ[/yellow]",
        )
        console.print(table)

        return {
            "local_ok": local_ok,
            "local_models": local_models,
            "nim_ok": nim_ok,
        }

    async def run_batch_session(self) -> Dict[str, Any]:
        """
        Run on-demand batch session (processing yesterday + today data):
        1. Process negotiations and chats
        2. Search and analyze vacancies
        3. Send Telegram digest
        """
        await self.initialize()

        stats = {
            "processed_count": 0,
            "skipped_count": 0,
            "top_matches_count": 0,
            "applied_count": 0,
        }
        top_vacancies: List[Dict[str, Any]] = []
        processed_chats: List[Dict[str, Any]] = []

        console.print("[bold green]▶ Запуск сессии hh.ru Harness Агента...[/bold green]")

        async with BrowserHarness() as harness:
            page = await harness.new_page()

            # -----------------------------------------------------------------
            # 1. Обработка входящих откликов, сообщений и приглашений
            # -----------------------------------------------------------------
            console.print("[cyan]1/2 Проверка сообщений и приглашений на hh.ru...[/cyan]")
            try:
                neg_browser = NegotiationsBrowser(page)
                threads = await neg_browser.fetch_recent_negotiations()
                console.print(f"Найдено активных переписок: {len(threads)}")

                for thread in threads[:10]:
                    if thread.get("is_unread"):
                        console.print(f"Обработка непрочитанного сообщения от [bold]{thread.get('company_name')}[/bold]...")
                        chat_result = await self.chat_agent.process_incoming_thread(thread)
                        processed_chats.append(chat_result["record"])

                        if chat_result.get("is_urgent") or chat_result["classification"].category == "INVITATION":
                            await self.telegram.alert_invitation(
                                company=thread.get("company_name", ""),
                                vacancy=thread.get("vacancy_title", ""),
                                last_msg=thread.get("last_message_text", ""),
                                drafted_reply=chat_result.get("drafted_reply", ""),
                            )
            except Exception as e:
                console.print(f"[yellow]Предупреждение при проверке сообщений: {e}[/yellow]")

            # -----------------------------------------------------------------
            # 2. Поиск и скоринг вакансий за вчера + сегодня
            # -----------------------------------------------------------------
            console.print("[cyan]2/2 Поиск вакансий (вчера + сегодня)...[/cyan]")
            vac_browser = VacancyBrowser(page)
            applicant = VacancyApplicant(page)

            for query in self.rules.search.queries:
                if stats["processed_count"] >= settings.max_vacancies_per_batch:
                    break

                search_url = vac_browser.build_search_url(
                    query=query,
                    config=self.rules.search,
                    search_period_days=2,
                )
                console.print(f"Поиск по запросу: [bold]{query}[/bold]")
                found_items = await vac_browser.fetch_search_results(search_url)

                for item in found_items:
                    if stats["processed_count"] >= settings.max_vacancies_per_batch:
                        break

                    hh_id = item["hh_id"]
                    # Skip already processed
                    if await self.db.vacancy_exists(hh_id):
                        continue

                    # Extract full details
                    details = await vac_browser.extract_vacancy_details(item["url"])
                    if not details or details.get("is_blocked"):
                        continue

                    stats["processed_count"] += 1

                    # 2-Tier Evaluation (Qwen Tier 1 -> NIM Tier 2)
                    eval_result = await self.vacancy_evaluator.evaluate_vacancy(details)
                    rec = eval_result["record"]
                    score = rec.get("score", 0)

                    if eval_result["status"] == "SKIPPED":
                        stats["skipped_count"] += 1
                        console.print(f"  [-] {details['title'][:35]}... Пропущено (Балл: {score})")
                    else:
                        stats["top_matches_count"] += 1
                        console.print(f"  [+] [bold green]{details['title'][:35]}[/bold green] (Балл: {score}/100) - {details['company_name']}")
                        top_vacancies.append(rec)

                        # Auto-apply if configured
                        if settings.application_mode == "auto" and score >= self.rules.thresholds.min_score_for_nim_dossier:
                            cover_letter = eval_result.get("cover_letter", "")
                            console.print(f"      Отправка отклика с письмом от NIM...")
                            apply_res = await applicant.apply_to_vacancy(
                                vacancy_url=details["url"],
                                cover_letter=cover_letter,
                            )
                            if apply_res.get("success"):
                                stats["applied_count"] += 1
                                await self.db.update_vacancy_status(hh_id, "APPLIED", applied=True)
                                console.print(f"      [green]Отклик успешно доставлен![/green]")

                    await BrowserHarness.human_delay(1.5, 3.0)

        # -----------------------------------------------------------------
        # 3. Отправка сводки в Telegram и сохранение локального дайджеста
        # -----------------------------------------------------------------
        console.print("[cyan]Формирование и отправка сводки в Telegram...[/cyan]")
        await self.telegram.send_session_digest(
            stats=stats,
            top_vacancies=top_vacancies,
            incoming_chats=processed_chats,
        )

        console.print("[bold green]✔ Сессия успешно завершена![/bold green]")
        return {
            "stats": stats,
            "top_vacancies": top_vacancies,
            "processed_chats": processed_chats,
        }
